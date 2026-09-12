"""Turn a file, a patch, or a git diff into a Change: touched files and their
added or modified regions. Tolerant by design; it does not need a grammar.

Oracles read added regions via ``change.added_regions()``; each Region yields
``(lineno, text)`` for its added lines and, when the whole new content of the
file is known (``from_file``/``from_text``), carries it in ``full_text`` so an
oracle can parse the file properly instead of guessing from fragments.

Standard library only.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DIFF_GIT = re.compile(r'^diff --git (?:"?a/)?(.*?)"? (?:"?b/)?(.*?)"?$')


@dataclass
class Region:
    file: str
    _lines: list[tuple[int, str]] = field(default_factory=list)
    full_text: str | None = None  # whole new file content when known

    def add(self, lineno: int, text: str) -> None:
        self._lines.append((lineno, text))

    def lines(self) -> list[tuple[int, str]]:
        return self._lines

    @property
    def whole_file(self) -> bool:
        return self.full_text is not None

    def text(self) -> str:
        """The added lines joined, or the full file when known."""
        if self.full_text is not None:
            return self.full_text
        return "\n".join(t for _, t in self._lines)


@dataclass
class Change:
    regions: list[Region] = field(default_factory=list)

    def added_regions(self) -> list[Region]:
        return self.regions

    def files(self) -> list[str]:
        seen: dict[str, None] = {}
        for r in self.regions:
            seen.setdefault(r.file, None)
        return list(seen)

    def is_empty(self) -> bool:
        return not any(r.lines() for r in self.regions)

    @classmethod
    def combine(cls, changes: Iterable[Change]) -> Change:
        out = cls()
        for ch in changes:
            out.regions.extend(ch.regions)
        return out

    def relative_to(self, repo_root: str) -> Change:
        """The same change with every file path repo-relative and POSIX-separated."""
        root = os.path.abspath(repo_root)
        out = Change()
        for r in self.regions:
            path = r.file
            if os.path.isabs(path):
                try:
                    rel = os.path.relpath(path, root)
                except ValueError:  # pragma: no cover - different drives on Windows
                    rel = path
                path = path if rel.startswith("..") else rel
            path = path.replace(os.sep, "/")
            if path.startswith("./"):
                path = path[2:]
            out.regions.append(Region(file=path, _lines=list(r.lines()), full_text=r.full_text))
        return out

    # --- constructors ----------------------------------------------------------

    @classmethod
    def from_text(cls, path: str, text: str) -> Change:
        """Treat the whole of ``text`` as the new content of ``path`` (the file need
        not exist yet: this is what a PreToolUse hook sees before a Write lands)."""
        r = Region(file=path, full_text=text)
        for i, line in enumerate(text.splitlines(), 1):
            r.add(i, line)
        return cls(regions=[r])

    @classmethod
    def from_file(cls, path: str, repo_root: str | None = None) -> Change:
        """Treat an entire file as added (used by ``weft check <file>`` and audit)."""
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        change = cls.from_text(path, text)
        return change.relative_to(repo_root) if repo_root else change

    @classmethod
    def from_unified_diff(cls, text: str) -> Change:
        """Parse a unified diff (git or plain), keeping only added lines with their
        new-file line numbers. Handles renames, new/deleted files, binary hunks,
        ``--no-prefix`` diffs, and the "no newline" marker."""
        change = cls()
        cur: Region | None = None
        new_lineno = 0
        in_hunk = False
        pending_git_path: str | None = None
        for line in text.splitlines():
            if line.startswith("diff --git "):
                m = _DIFF_GIT.match(line)
                pending_git_path = m.group(2) if m else None
                cur, in_hunk = None, False
                continue
            if line.startswith("+++ ") and not in_hunk:
                path = _clean_path(line[4:])
                if path is None:  # deleted file: nothing added
                    cur, pending_git_path = None, None
                else:
                    cur = Region(file=path)
                    change.regions.append(cur)
                continue
            if line.startswith("--- ") and not in_hunk:
                continue
            if line.startswith("@@@ "):  # combined diff: not supported, skip hunk
                in_hunk, cur = False, None
                continue
            hm = _HUNK.match(line)
            if hm:
                if cur is None and pending_git_path:
                    cur = Region(file=pending_git_path)
                    change.regions.append(cur)
                new_lineno = int(hm.group(3))
                in_hunk = True
                continue
            if line.startswith("Binary files") or line.startswith("GIT binary patch"):
                in_hunk = False
                continue
            if not in_hunk:
                continue
            if line.startswith("\\"):  # "\ No newline at end of file"
                continue
            if line.startswith("+"):
                if cur is not None:
                    cur.add(new_lineno, line[1:])
                new_lineno += 1
            elif line.startswith("-"):
                continue
            else:
                new_lineno += 1
        return change

    @classmethod
    def from_git(
        cls, repo_root: str, staged: bool = False, rev_range: str | None = None
    ) -> Change:
        """The working-tree diff (or ``--staged``, or a revision range) as a Change."""
        args = ["git", "diff", "--no-color", "--no-ext-diff", "--no-renames", "-U0"]
        if rev_range:
            args.append(rev_range)
        elif staged:
            args.append("--staged")
        proc = subprocess.run(args, cwd=repo_root, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"git diff failed: {proc.stderr.strip() or proc.returncode}")
        change = cls.from_unified_diff(proc.stdout)
        if not staged and not rev_range:
            # Untracked files are new content too: include them whole.
            listing = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=repo_root, capture_output=True, text=True, check=False,
            )
            for rel in sorted(p for p in listing.stdout.split("\0") if p):
                full = os.path.join(repo_root, rel)
                if os.path.isfile(full) and _looks_texty(full):
                    change.regions.extend(cls.from_file(full, repo_root).regions)
        return change

    @classmethod
    def from_path_or_diff(
        cls, arg: str, stdin_text: str | None = None, repo_root: str | None = None
    ) -> Change:
        if arg == "-":
            return cls.from_unified_diff(stdin_text or "")
        if os.path.isfile(arg):
            return cls.from_file(arg, repo_root)
        if os.path.isdir(arg):
            change = cls()
            for dirpath, dirnames, filenames in os.walk(arg):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                                     and d not in ("node_modules", "__pycache__", "venv"))
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    if _looks_texty(full):
                        change.regions.extend(cls.from_file(full, repo_root).regions)
            return change
        # Fall back to treating the argument itself as diff text.
        return cls.from_unified_diff(arg)


def _clean_path(raw: str) -> str | None:
    """Strip git's a/ b/ prefixes, tabs, timestamps and quotes; None for /dev/null."""
    path = raw.split("\t", 1)[0].strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    if path == "/dev/null":
        return None
    if path.startswith("b/") or path.startswith("a/"):
        path = path[2:]
    return path


def _looks_texty(path: str, sample: int = 4096) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(sample)
    except OSError:
        return False
    return b"\0" not in chunk
