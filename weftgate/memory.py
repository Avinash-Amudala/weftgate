"""The recall consumer's half of the graph (docs/ADDENDUM section A5): anchors and
self-invalidation for verified memory, and weftgate's oracles offered to mnemo's
verify registry.

A memory that says "the API reads DATABASE_URL and POST /orders is handled by
create_order" is grounded on graph nodes. This module:

- ``anchor``   turns a memory's claims (and, conservatively, its prose) into
               anchors: node id, locator, content hash, the commit it was
               grounded on, and a state (valid | unverifiable).
- ``check``    re-derives each anchor's state now: valid, stale (the artifact's
               content changed), or invalid (the node no longer resolves).
- ``changes``  the changed-node ledger since a sequence number, so a memory
               store can flip affected memories to stale in O(changes).
- ``register`` the mnemo plugin entry point: ``api.register_oracle(kind,
               extract, check)`` for env vars, imports, and routes, so a false
               claim is refused before it becomes a memory. A claim read from
               prose is a guess and never hard-rejects (mnemo enforces this too).

Standard library only. Every function is pure over a :class:`Session`; the CLI
and the MCP tools call the same ones.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from collections.abc import Callable, Iterable
from typing import Any

from .gate import Session
from .types import Claim, Finding, Level, Location

ANCHOR_KINDS = ("file", "env", "route", "import", "symbol")
_ENV_NAME = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")
_ROUTE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[\w./{}\-:]*)")
_FILE = re.compile(r"(?<![\w/])((?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,8})")
_IMPORT = re.compile(r"(?:^|[\s`(])(?:import|from)\s+([A-Za-z_][\w]*)(?:[.\s`)]|$)", re.M)
_BACKTICK_MODULE = re.compile(r"`([a-z][a-z0-9_]{2,})`")


# --- anchors --------------------------------------------------------------------------------------


def anchor(
    session: Session, text: str = "", claims: dict[str, Any] | None = None, sync: bool = True
) -> dict[str, Any]:
    """Anchors for one memory. ``claims`` may carry ``files``, ``env`` (or
    ``env_vars``), ``routes``, ``imports``, ``symbols``; prose is scanned for the
    same kinds but only nodes that resolve *now* become anchors (prose is a guess)."""
    if sync:
        session.sync()
    claims = claims or {}
    wanted: dict[str, set[str]] = {k: set() for k in ANCHOR_KINDS}
    for key, kind in (
        ("files", "file"),
        ("file", "file"),
        ("env", "env"),
        ("env_vars", "env"),
        ("routes", "route"),
        ("imports", "import"),
        ("symbols", "symbol"),
    ):
        for value in claims.get(key) or []:
            if isinstance(value, str) and value.strip():
                wanted[kind].add(value.strip())
    prose = _extract_prose(text)
    anchors: list[dict[str, Any]] = []
    commit = session.ctx.git_commit
    for kind in ANCHOR_KINDS:
        for value in sorted(wanted[kind]):
            anchors.append(_make_anchor(session, kind, value, commit, declared=True))
        for value in sorted(prose.get(kind, set()) - wanted[kind]):
            a = _make_anchor(session, kind, value, commit, declared=False)
            if a["state"] == "valid":
                anchors.append(a)
    return {
        "commit": commit,
        "seq": session.store.head_seq(),
        "anchors": anchors,
        "nodes": sorted({a["node"] for a in anchors}),
    }


def check(session: Session, anchors: Iterable[dict[str, Any]], sync: bool = True) -> dict[str, Any]:
    """Re-derive every anchor's state now. ``summary`` is the memory's overall
    state: invalid if any anchor is invalid, else stale if any is stale, else
    valid. Unverifiable anchors keep the memory stale for review."""
    if sync:
        session.sync()
    commit = session.ctx.git_commit
    out: list[dict[str, Any]] = []
    for a in anchors:
        kind, value = str(a.get("kind", "")), str(a.get("locator", ""))
        if kind not in ANCHOR_KINDS or not value:
            out.append({**a, "state": "unverifiable", "reason": "malformed anchor"})
            continue
        fresh = _make_anchor(session, kind, value, commit, declared=True)
        state = fresh["state"]
        if (
            state == "valid"
            and a.get("content_hash")
            and fresh.get("content_hash")
            and a["content_hash"] != fresh["content_hash"]
        ):
            state = "stale"
            fresh["reason"] = "content changed since the memory was grounded"
        # Checking is observation, not permission to replace the grounding evidence.
        # Retain the original hash so repeated checks cannot silently validate stale prose.
        out.append(
            {
                **a,
                **fresh,
                "state": state,
                "content_hash": a.get("content_hash"),
                "commit": a.get("commit"),
                "observed_hash": fresh.get("content_hash"),
                "observed_commit": commit,
            }
        )
    states = [a["state"] for a in out]
    summary = (
        "invalid"
        if "invalid" in states
        else ("stale" if any(state != "valid" for state in states) else "valid")
    )
    return {"commit": commit, "seq": session.store.head_seq(), "summary": summary, "anchors": out}


def changes(session: Session, since: int = 0, sync: bool = True) -> dict[str, Any]:
    """Changed nodes with seq greater than ``since``."""
    if sync:
        session.sync()
    rows = session.store.changes_since(since)
    nodes: dict[str, str] = {}
    for _seq, node, op, _commit in rows:
        nodes[node] = op
    return {
        "since": since,
        "seq": rows[-1][0] if rows else since,
        "head_seq": session.store.head_seq(),
        "has_more": bool(rows and rows[-1][0] < session.store.head_seq()),
        "commit": session.ctx.git_commit,
        "changes": [{"node": n, "op": op} for n, op in sorted(nodes.items())],
    }


def _make_anchor(
    session: Session, kind: str, value: str, commit: str | None, declared: bool
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": kind,
        "locator": value,
        "oracle": "weftgate",
        "commit": commit,
        "declared": declared,
    }
    match kind:
        case "file":
            from .context import safe_path

            rel = value.replace(os.sep, "/")
            while rel.startswith("./"):
                rel = rel[2:]
            full = os.path.join(session.store.repo_root, rel)
            if (
                os.path.isabs(value)
                or ".." in rel.split("/")
                or safe_path(session.store.repo_root, rel) is None
            ):
                return {
                    **base,
                    "node": f"file:{rel}",
                    "state": "unverifiable",
                    "reason": "not a repo-relative path",
                }
            if not os.path.isfile(full):
                return {
                    **base,
                    "node": f"file:{rel}",
                    "state": "invalid",
                    "reason": "file not in the repo now",
                }
            return {
                **base,
                "node": f"file:{rel}",
                "state": "valid",
                "reason": "present",
                "content_hash": _file_hash(full),
            }
        case "env":
            f = _check_via(session, "env_var", value)
            decl = _env_declaration_hash(session, value)
            return {
                **base,
                "node": f"env:{value}",
                "oracle": "weftgate.env_vars",
                **_state_of(f, "declared"),
                **({"content_hash": decl} if decl else {}),
            }
        case "route":
            f = _check_via(session, "route_handler", value.strip())
            return {
                **base,
                "node": f"route:{_norm_route(value)}",
                "oracle": "weftgate.routes_fastapi",
                **_state_of(f, "registered"),
                **({"content_hash": _sha(f.reason)} if f.level is Level.ACCEPT else {}),
            }
        case "import":
            top = value.split(".")[0].split("/")[0] if not value.startswith("@") else value
            f = _check_via(session, "import", value, attrs={"top": top})
            return {
                **base,
                "node": f"dist:{_lang_of(value)}:{top}",
                "oracle": "weftgate.imports_lockfile",
                **_state_of(f, "provided"),
                **(
                    {"content_hash": _import_contract_hash(session)}
                    if f.level is Level.ACCEPT
                    else {}
                ),
            }
        case _:  # symbol: "path/to/file.py:name"
            file, _, name = value.rpartition(":")
            if not file or not name:
                return {
                    **base,
                    "node": f"symbol:{value}",
                    "state": "unverifiable",
                    "reason": "expected <file>:<name>",
                }
            ns = session.store.namespace("routes_fastapi")
            if not ns.exists("symbols"):
                return {
                    **base,
                    "node": f"symbol:{file}:{name}",
                    "state": "unverifiable",
                    "reason": "symbol index not built",
                }
            rows = ns.query("SELECT kind FROM {t:symbols} WHERE file=? AND name=?", (file, name))
            if not rows:
                return {
                    **base,
                    "node": f"symbol:{file}:{name}",
                    "state": "invalid",
                    "reason": f"{file} defines no {name!r}",
                }
            span = _symbol_hash(session, file, name)
            return {
                **base,
                "node": f"symbol:{file}:{name}",
                "state": "valid",
                "reason": f"{rows[0][0]} in {file}",
                **({"content_hash": span} if span else {}),
            }


def _check_via(
    session: Session, kind: str, subject: str, attrs: dict[str, Any] | None = None
) -> Finding:
    claim = Claim(kind, subject, Location(""), dict(attrs or {}), True, "assertion")
    result = session.check_claims([claim], sync=False)
    return result.findings[0]


def _state_of(finding: Any, ok_word: str) -> dict[str, Any]:
    match finding.level:
        case Level.ACCEPT:
            return {"state": "valid", "reason": ok_word}
        case Level.REJECT:
            return {
                "state": "invalid",
                "reason": finding.reason,
                **({"did_you_mean": list(finding.suggestions)} if finding.suggestions else {}),
            }
        case Level.REVIEW:
            return {"state": "unverifiable", "reason": finding.reason}
        case _:
            return {"state": "unverifiable", "reason": finding.reason}


def _extract_prose(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {k: set() for k in ANCHOR_KINDS}
    if not text:
        return out
    out["env"] = {m.group(1) for m in _ENV_NAME.finditer(text) if len(m.group(1)) >= 4}
    out["route"] = {f"{m.group(1)} {m.group(2)}" for m in _ROUTE.finditer(text)}
    out["file"] = {m.group(1).rstrip(".,;:)") for m in _FILE.finditer(text)}
    out["import"] = {m.group(1) for m in _IMPORT.finditer(text)} | {
        m.group(1) for m in _BACKTICK_MODULE.finditer(text)
    }
    return out


def _file_hash(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return "sha256:" + h.hexdigest()


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _env_declaration_hash(session: Session, name: str) -> str:
    ns = session.store.namespace("env_vars")
    if not ns.exists("decl"):
        return ""
    rows = ns.query("SELECT file, source FROM {t:decl} WHERE name=? ORDER BY file", (name,))
    return _sha("|".join(f"{r[0]}:{r[1]}" for r in rows)) if rows else ""


def _import_contract_hash(session: Session) -> str:
    """Track dependency declarations and local import names, not installed code."""
    ns = session.store.namespace("imports_lockfile")
    if not ns.exists("sources") or not ns.exists("local"):
        return ""
    pieces = [sys.version]
    for (source,) in ns.query("SELECT DISTINCT source FROM {t:sources} ORDER BY source"):
        text = session.ctx.read_text(str(source))
        if text is None:
            return ""
        pieces.extend((str(source), text))
    pieces.extend(
        repr(tuple(row))
        for row in ns.query("SELECT lang, name, kind, source FROM {t:local} ORDER BY 1,2,3,4")
    )
    return _sha("\0".join(pieces))


def _symbol_hash(session: Session, file: str, name: str) -> str:
    """Hash of the definition's source span (the def/class block), not the file."""
    text = session.ctx.read_text(file)
    if text is None:
        return ""
    try:
        import ast

        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return ""
    lines = text.splitlines()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            return _sha("\n".join(lines[node.lineno - 1 : end]))
    return ""


def _norm_route(value: str) -> str:
    method, _, path = value.strip().partition(" ")
    path = path.strip() or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return f"{method.upper()} {path}"


def _lang_of(spec: str) -> str:
    return "node" if spec.startswith("@") or "/" in spec or "-" in spec else "python"


# --- the mnemo plugin: weftgate's oracles inside mnemo's verify gate ------------------------------
#
# mnemo loads plugins named in .mnemo.json ("oracles": ["weftgate.memory"]) and calls
# register(api); api.register_oracle(kind, extract, check) where
#   extract(text) -> [value, ...]                  candidate claims read from prose
#   check(value, declared, repo_root) -> ledger    {"type", "claim", "status", "reason", ...}
# status is one of accept | review | reject | unverifiable. A value read from prose
# (declared=False) may flag but never rejects.

_SESSIONS: dict[str, Session] = {}


def _session_for(repo_root: str) -> Session:
    root = os.path.abspath(repo_root)
    s = _SESSIONS.get(root)
    if s is None:
        s = Session(root)
        _SESSIONS[root] = s
    return s


def close_sessions() -> None:
    """Close the sessions the plugin path caches (one per repo). Call it when the
    host process is done, or before removing a repo's cache directory: an open
    SQLite file cannot be deleted on Windows."""
    for s in _SESSIONS.values():
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass
    _SESSIONS.clear()


def _ledger(
    kind: str,
    value: str,
    declared: bool,
    repo_root: str,
    claim_kind: str,
    attrs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        session = _session_for(repo_root)
        session.sync()
        f = _check_via(session, claim_kind, value, attrs)
    except Exception as exc:  # noqa: BLE001 - a broken index never rejects
        return {
            "type": kind,
            "claim": value,
            "status": "unverifiable",
            "reason": f"weftgate could not check: {exc}",
        }
    status = {
        Level.ACCEPT: "accept",
        Level.REVIEW: "review",
        Level.REJECT: "reject",
        Level.UNVERIFIABLE: "unverifiable",
    }[f.level]
    if status == "reject" and not declared:
        status = "review"
    entry: dict[str, Any] = {
        "type": kind,
        "claim": value,
        "status": status,
        "reason": f.reason,
        "oracle": f"weftgate.{f.oracle}",
    }
    if f.suggestions:
        entry["did_you_mean"] = list(f.suggestions)
    return entry


def _extract_env(text: str) -> list[str]:
    return sorted(_extract_prose(text)["env"])


def _check_env(value: str, declared: bool, repo_root: str) -> dict[str, Any]:
    return _ledger("env", value, declared, repo_root, "env_var")


def _extract_routes(text: str) -> list[str]:
    return sorted(_extract_prose(text)["route"])


def _check_route(value: str, declared: bool, repo_root: str) -> dict[str, Any]:
    return _ledger("route", value, declared, repo_root, "route_handler")


def _extract_imports(text: str) -> list[str]:
    return sorted(_extract_prose(text)["import"])


def _check_import(value: str, declared: bool, repo_root: str) -> dict[str, Any]:
    top = value.split(".")[0] if not value.startswith("@") else value
    return _ledger("import", value, declared, repo_root, "import", {"top": top})


ORACLES: dict[
    str, tuple[Callable[[str], list[str]], Callable[[str, bool, str], dict[str, Any]]]
] = {
    "env": (_extract_env, _check_env),
    "routes": (_extract_routes, _check_route),
    "imports": (_extract_imports, _check_import),
}


def register(api: Any) -> None:
    """mnemo plugin entry point."""
    for kind, (extract, check_fn) in ORACLES.items():
        api.register_oracle(kind, extract, check_fn)
