"""Per-repo SQLite index. One db per repo under ``~/.cache/weftgate/``. Each oracle
gets a namespaced place to write, a ``meta`` table records the schema version
and the commit the index was built at, and ``sync_files`` returns what changed
since that commit plus the working-tree diff so oracles can reindex only that.

Atomicity rules (AGENTS.md section 6, item 5): a full rebuild writes to a temp
table and swaps it in inside one transaction; a per-file update deletes and
reinserts inside one transaction. A failure rolls back and leaves the previous
index intact.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from .config import IGNORED_DIRS

SCHEMA_VERSION = 1

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_GIT_TIMEOUT = 30


def cache_dir() -> str:
    base = os.environ.get("WEFTGATE_CACHE")
    if not base:
        xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        base = os.path.join(xdg, "weftgate")
    os.makedirs(base, exist_ok=True)
    return base


def cache_path(repo_root: str) -> str:
    root = os.path.abspath(repo_root)
    h = hashlib.sha1(root.encode()).hexdigest()[:16]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", os.path.basename(root)) or "repo"
    return os.path.join(cache_dir(), f"{stem}-{h}.sqlite")


def _posix(path: str) -> str:
    return path.replace(os.sep, "/")


def _is_ignored(rel_posix: str, ignored: frozenset[str]) -> bool:
    parts = rel_posix.split("/")
    return any(p in ignored or p.endswith(".egg-info") for p in parts[:-1])


class Store:
    """SQLite-backed index for one repository."""

    def __init__(
        self,
        repo_root: str,
        path: str | None = None,
        ignored_dirs: Iterable[str] | None = None,
    ) -> None:
        self.repo_root = os.path.abspath(repo_root)
        self.path = path or cache_path(self.repo_root)
        self.ignored = IGNORED_DIRS | frozenset(ignored_dirs or ())
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:  # pragma: no cover - exotic filesystems
            pass
        self._depth = 0
        self._git_ok: bool | None = None
        self._sync_cache: dict[str | None, list[str]] = {}
        self._pending_files: dict[str, tuple[int, int]] | None = None
        self._init()

    # --- lifecycle --------------------------------------------------------------------

    def _init(self) -> None:
        with self.transaction():
            self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            stored = self.get_meta("schema_version")
            if stored is not None and stored != str(SCHEMA_VERSION):
                # Core schema changed: reset core tables, keep oracle tables (their
                # owners re-validate them through the per-oracle version key).
                self.db.execute("DROP TABLE IF EXISTS kv")
                self.db.execute("DROP TABLE IF EXISTS files")
                self.db.execute("DELETE FROM meta")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS kv "
                "(oracle TEXT, key TEXT, value TEXT, PRIMARY KEY (oracle, key))"
            )
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS files "
                "(path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER)"
            )
            # The changed-node ledger: what the graph learned changed at each sync.
            # Consumers (verified memory) ask "what changed since seq N" to
            # self-invalidate anything grounded on those nodes: O(changes), not
            # O(memories).
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS changes "
                "(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
                "commit_hash TEXT, node TEXT NOT NULL, op TEXT NOT NULL)"
            )
            self.db.execute("CREATE INDEX IF NOT EXISTS changes__node ON changes (node)")
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            self.set_meta("repo_root", self.repo_root)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- transactions ----------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Nested-safe explicit transaction. Rolls back on any exception."""
        depth = self._depth
        savepoint = f"weftgate_tx_{depth}"
        self.db.execute("BEGIN IMMEDIATE" if depth == 0 else f"SAVEPOINT {savepoint}")
        self._depth += 1
        try:
            yield
        except BaseException:
            if depth == 0:
                self.db.execute("ROLLBACK")
            else:
                self.db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self.db.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            self.db.execute("COMMIT" if depth == 0 else f"RELEASE SAVEPOINT {savepoint}")
        finally:
            self._depth -= 1

    # --- meta ------------------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def del_meta(self, key: str) -> None:
        self.db.execute("DELETE FROM meta WHERE key=?", (key,))

    def meta_with_prefix(self, prefix: str) -> dict[str, str]:
        rows = self.db.execute(
            "SELECT key, value FROM meta WHERE key LIKE ? ORDER BY key", (prefix + "%",)
        ).fetchall()
        return {str(k): str(v) for k, v in rows}

    # --- per-oracle build bookkeeping -----------------------------------------------

    def is_built(self, oracle: str) -> bool:
        return self.get_meta(f"oracle:{oracle}:built") == "1"

    def mark_built(self, oracle: str, commit: str | None, version: str = "1") -> None:
        with self.transaction():
            self.set_meta(f"oracle:{oracle}:built", "1")
            self.set_meta(f"oracle:{oracle}:version", version)
            self.set_meta(f"oracle:{oracle}:commit", commit or "")
            self.del_meta(f"oracle:{oracle}:needs_rebuild")

    def mark_unbuilt(self, oracle: str) -> None:
        with self.transaction():
            self.del_meta(f"oracle:{oracle}:built")
            self.del_meta(f"oracle:{oracle}:commit")

    def oracle_commit(self, oracle: str) -> str | None:
        value = self.get_meta(f"oracle:{oracle}:commit")
        return value or None

    def oracle_version(self, oracle: str) -> str | None:
        return self.get_meta(f"oracle:{oracle}:version")

    def mark_needs_rebuild(self, oracle: str) -> None:
        self.set_meta(f"oracle:{oracle}:needs_rebuild", "1")

    def needs_rebuild(self, oracle: str) -> bool:
        return self.get_meta(f"oracle:{oracle}:needs_rebuild") == "1"

    def oracle_status(self, oracle: str) -> dict[str, Any]:
        ns = self.namespace(oracle)
        return {
            "built": self.is_built(oracle),
            "commit": self.oracle_commit(oracle),
            "version": self.oracle_version(oracle),
            "needs_rebuild": self.needs_rebuild(oracle),
            "tables": {t: ns.count(t) for t in ns.tables()},
        }

    # --- simple set helper used by lightweight oracles ------------------------------

    def replace_set(self, oracle: str, key: str, values: Iterable[str]) -> None:
        self.db.execute(
            "INSERT INTO kv (oracle, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(oracle, key) DO UPDATE SET value=excluded.value",
            (oracle, key, json.dumps(sorted(set(values)))),
        )

    def get_set(self, oracle: str, key: str) -> set[str] | None:
        row = self.db.execute(
            "SELECT value FROM kv WHERE oracle=? AND key=?", (oracle, key)
        ).fetchone()
        return set(json.loads(row[0])) if row else None

    def drop_set(self, oracle: str, key: str) -> None:
        self.db.execute("DELETE FROM kv WHERE oracle=? AND key=?", (oracle, key))

    def namespace(self, oracle: str) -> Namespace:
        return Namespace(self, oracle)

    # --- repository files and git ---------------------------------------------------

    def _git(self, *args: str) -> str | None:
        if self._git_ok is False:
            return None
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            self._git_ok = False
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout

    def is_git_repo(self) -> bool:
        if self._git_ok is None:
            out = self._git("rev-parse", "--is-inside-work-tree")
            self._git_ok = bool(out and out.strip() == "true")
        return self._git_ok

    def current_commit(self) -> str | None:
        if not self.is_git_repo():
            return None
        out = self._git("rev-parse", "--verify", "HEAD")
        return out.strip() if out else None

    def _own_files(self) -> frozenset[str]:
        """The index's own files, in case it lives inside the repo it indexes."""
        try:
            rel = _posix(os.path.relpath(os.path.abspath(self.path), self.repo_root))
        except ValueError:  # pragma: no cover - different drives on Windows
            return frozenset()
        if rel.startswith("../"):
            return frozenset()
        return frozenset({rel, rel + "-wal", rel + "-shm", rel + "-journal"})

    def _filter(self, paths: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        own = self._own_files()
        for p in paths:
            p = _posix(p.strip())
            if not p or p in seen or p in own or _is_ignored(p, self.ignored):
                continue
            seen.add(p)
        return sorted(seen)

    def all_files(self) -> list[str]:
        """Every file in the repo worth indexing, repo-relative, POSIX separators, sorted.

        In a git repo this honours .gitignore (tracked plus untracked-unignored
        files, minus files deleted in the working tree). Otherwise it walks the
        tree skipping the well-known junk directories.
        """
        if self.is_git_repo():
            out = self._git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
            if out is not None:
                paths = [p for p in out.split("\0") if p]
                return [
                    p
                    for p in self._filter(paths)
                    if os.path.isfile(os.path.join(self.repo_root, p))
                ]
        return self._filter(self._walk().keys())

    def _walk(self) -> dict[str, tuple[int, int]]:
        found: dict[str, tuple[int, int]] = {}
        for dirpath, dirnames, filenames in os.walk(self.repo_root):
            dirnames[:] = sorted(
                d for d in dirnames if d not in self.ignored and not d.endswith(".egg-info")
            )
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                rel = _posix(os.path.relpath(full, self.repo_root))
                found[rel] = (st.st_size, st.st_mtime_ns)
        return found

    def sync_files(self, since_commit: str | None) -> list[str]:
        """Repo-relative paths changed since ``since_commit`` plus the working-tree
        diff (modified, staged, untracked, and deleted files). ``None`` or an
        unknown commit means everything. Memoised per store instance so several
        oracles syncing in one run share a single git invocation.

        Outside git, compares an mtime/size fingerprint against the ``files``
        table; call :meth:`finish_sync` once every oracle has consumed the result
        so the fingerprints advance only after a successful sync.
        """
        if since_commit in self._sync_cache:
            return list(self._sync_cache[since_commit])
        changed = self._git_changed(since_commit) if self._valid_commit(since_commit) else None
        # Compare with the state actually indexed, including uncommitted edits.
        # A diff against HEAD alone misses restoring a dirty file to HEAD and
        # deleting a previously indexed untracked file.
        if changed is None or (
            self.get_meta("fingerprints_ready") == "1"
            and since_commit == (self.get_meta("build_commit") or None)
        ):
            changed = self._scan_changed()
        self._sync_cache[since_commit] = changed
        return list(changed)

    def _valid_commit(self, commit: str | None) -> bool:
        return bool(
            commit
            and self.is_git_repo()
            and self._git("cat-file", "-e", f"{commit}^{{commit}}") is not None
        )

    def _git_changed(self, since: str | None) -> list[str] | None:
        tracked = self._git("diff", "--name-only", "--no-renames", "--relative", "-z", str(since))
        untracked = self._git("ls-files", "--others", "--exclude-standard", "-z")
        if tracked is None or untracked is None:
            return None
        paths = [p for p in tracked.split("\0") + untracked.split("\0") if p]
        return self._filter(paths)

    def _fingerprints(self) -> dict[str, tuple[int, int]]:
        """(size, mtime_ns) per indexable file; the git listing when available."""
        if not self.is_git_repo():
            scanned = self._walk()
            return {p: scanned[p] for p in self._filter(scanned)}
        out: dict[str, tuple[int, int]] = {}
        for rel in self.all_files():
            try:
                st = os.stat(os.path.join(self.repo_root, rel))
            except OSError:
                continue
            out[rel] = (st.st_size, st.st_mtime_ns)
        return out

    def _scan_changed(self) -> list[str]:
        """Fingerprint diff against the ``files`` table: the fallback when there is
        no commit to diff against (no git, no commits yet, or an unknown commit)."""
        now = self._fingerprints()
        recorded = {
            str(p): (int(s), int(m))
            for p, s, m in self.db.execute("SELECT path, size, mtime FROM files")
        }
        changed = [p for p, fp in now.items() if recorded.get(p) != fp]
        deleted = [p for p in recorded if p not in now]
        self._pending_files = now
        return self._filter(changed + deleted)

    def finish_sync(self, commit: str | None) -> None:
        """Persist the post-sync state: the build commit and, when there is no commit
        to diff against next time, the file fingerprints. Call after every oracle
        synced (or built) successfully."""
        if self._pending_files is None:
            self._pending_files = self._fingerprints()
        with self.transaction():
            self.set_meta("build_commit", commit or "")
            self.set_meta("fingerprints_ready", "1")
            if self._pending_files is not None:
                self.db.execute("DELETE FROM files")
                self.db.executemany(
                    "INSERT INTO files (path, size, mtime) VALUES (?, ?, ?)",
                    [(p, s, m) for p, (s, m) in sorted(self._pending_files.items())],
                )
        self._pending_files = None
        self._sync_cache.clear()

    def forget_sync_cache(self) -> None:
        self._sync_cache.clear()
        self._pending_files = None

    # --- changed-node ledger ----------------------------------------------------------

    def record_changes(self, commit: str | None, changed: Iterable[tuple[str, str]]) -> int:
        """Append ``(node, op)`` pairs for one sync. Returns the head seq afterwards."""
        rows = sorted(set(changed))
        if rows:
            import time

            now = int(time.time())
            with self.transaction():
                self.db.executemany(
                    "INSERT INTO changes (ts, commit_hash, node, op) VALUES (?, ?, ?, ?)",
                    [(now, commit or "", node, op) for node, op in rows],
                )
        return self.head_seq()

    def head_seq(self) -> int:
        row = self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM changes").fetchone()
        return int(row[0]) if row else 0

    def changes_since(self, seq: int, limit: int = 50_000) -> list[tuple[int, str, str, str]]:
        """``(seq, node, op, commit)`` rows with seq greater than ``seq``, oldest first."""
        rows = self.db.execute(
            "SELECT seq, node, op, commit_hash FROM changes WHERE seq > ? ORDER BY seq LIMIT ?",
            (int(seq), int(limit)),
        ).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]

    def prune_changes(self, keep: int = 200_000) -> None:
        head = self.head_seq()
        if head > keep:
            with self.transaction():
                self.db.execute("DELETE FROM changes WHERE seq <= ?", (head - keep,))

    def status(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "changes_seq": self.head_seq(),
            "repo_root": self.repo_root,
            "schema_version": self.get_meta("schema_version"),
            "build_commit": self.get_meta("build_commit") or None,
            "git": self.is_git_repo(),
        }


class Namespace:
    """An oracle's own tables, prefixed ``<oracle>__``. Every write is atomic."""

    def __init__(self, store: Store, oracle: str) -> None:
        if not _IDENT.match(oracle):
            raise ValueError(f"oracle name must match {_IDENT.pattern}: {oracle!r}")
        self.store = store
        self.oracle = oracle

    def table(self, name: str) -> str:
        if not _IDENT.match(name):
            raise ValueError(f"table name must match {_IDENT.pattern}: {name!r}")
        return f"{self.oracle}__{name}"

    def tables(self) -> list[str]:
        rows = self.store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB ? ORDER BY name",
            (f"{self.oracle}__*",),
        ).fetchall()
        prefix = f"{self.oracle}__"
        return [str(r[0])[len(prefix) :] for r in rows]

    def ensure_table(self, name: str, columns: str, indexes: Sequence[str] = ()) -> None:
        t = self.table(name)
        with self.store.transaction():
            self.store.db.execute(f"CREATE TABLE IF NOT EXISTS {t} ({columns})")
            for i, cols in enumerate(indexes):
                self.store.db.execute(f"CREATE INDEX IF NOT EXISTS {t}__ix{i} ON {t} ({cols})")

    def rebuild(
        self,
        name: str,
        columns: str,
        rows: Iterable[Sequence[Any]],
        indexes: Sequence[str] = (),
    ) -> int:
        """Replace a whole table atomically: build into a temp table, then swap.

        The previous table survives untouched if anything fails midway.
        """
        t = self.table(name)
        tmp = f"{t}__tmp"
        rows = list(rows)
        with self.store.transaction():
            self.store.db.execute(f"DROP TABLE IF EXISTS {tmp}")
            self.store.db.execute(f"CREATE TABLE {tmp} ({columns})")
            if rows:
                width = len(rows[0])
                marks = ",".join("?" * width)
                self.store.db.executemany(f"INSERT INTO {tmp} VALUES ({marks})", rows)
            self.store.db.execute(f"DROP TABLE IF EXISTS {t}")
            self.store.db.execute(f"ALTER TABLE {tmp} RENAME TO {t}")
            for i, cols in enumerate(indexes):
                self.store.db.execute(f"CREATE INDEX IF NOT EXISTS {t}__ix{i} ON {t} ({cols})")
        return len(rows)

    def replace_file(
        self, name: str, file: str, rows: Iterable[Sequence[Any]], file_column: str = "file"
    ) -> int:
        """Atomically replace every row for one file (empty rows = file deleted)."""
        t = self.table(name)
        rows = list(rows)
        with self.store.transaction():
            self.store.db.execute(f"DELETE FROM {t} WHERE {file_column}=?", (file,))
            if rows:
                marks = ",".join("?" * len(rows[0]))
                self.store.db.executemany(f"INSERT INTO {t} VALUES ({marks})", rows)
        return len(rows)

    def insert(self, name: str, rows: Iterable[Sequence[Any]]) -> int:
        t = self.table(name)
        rows = list(rows)
        if not rows:
            return 0
        marks = ",".join("?" * len(rows[0]))
        with self.store.transaction():
            self.store.db.executemany(f"INSERT INTO {t} VALUES ({marks})", rows)
        return len(rows)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run a SELECT with ``{t:name}`` placeholders expanded to namespaced tables."""
        sql = re.sub(r"\{t:([a-z][a-z0-9_]*)\}", lambda m: self.table(m.group(1)), sql)
        return [tuple(r) for r in self.store.db.execute(sql, params).fetchall()]

    def exists(self, name: str) -> bool:
        row = self.store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (self.table(name),)
        ).fetchone()
        return row is not None

    def count(self, name: str) -> int:
        if not self.exists(name):
            return 0
        row = self.store.db.execute(f"SELECT COUNT(*) FROM {self.table(name)}").fetchone()
        return int(row[0]) if row else 0

    def drop(self, name: str) -> None:
        with self.store.transaction():
            self.store.db.execute(f"DROP TABLE IF EXISTS {self.table(name)}")

    def drop_all(self) -> None:
        with self.store.transaction():
            for name in self.tables():
                self.store.db.execute(f"DROP TABLE IF EXISTS {self.table(name)}")
            self.store.db.execute("DELETE FROM kv WHERE oracle=?", (self.oracle,))
