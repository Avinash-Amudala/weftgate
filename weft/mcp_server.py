"""stdio MCP server. Thin wrapper over the same gate.* functions the CLI uses, so
the two surfaces cannot drift. Tools: check_change, check_claim, audit, suggest,
index_status, index.

Standard library only: a minimal newline-delimited JSON-RPC 2.0 loop that speaks
the MCP handshake (``initialize``, ``notifications/initialized``, ``ping``,
``tools/list``, ``tools/call``). No optional extra is needed to serve; the
``weft[mcp]`` extra is only used by the tests to drive this server with the
official client. Every tool handler is a pure function (:func:`call_tool`) that
returns exactly the dict the CLI prints as JSON.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, TextIO

from . import __version__, gate, ledger
from .change import Change
from .config import find_repo_root

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "weft", "version": __version__}

_REPO_PROP = {"type": "string", "description": "repository root (default: cwd's repo)"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_change",
        "description": (
            "Verify code before it ships: extract every relational reference (env "
            "vars, imports, routes) from a file, new file content, or a unified diff "
            "and check each against the repo's own declarations. Verdict is reject "
            "only on a proven broken wire; review/unverifiable never block."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _REPO_PROP,
                "path": {
                    "type": "string",
                    "description": "file to check (repo-relative or absolute)",
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "several files or directories to check together",
                },
                "content": {
                    "type": "string",
                    "description": "new content of `path` (not yet written)",
                },
                "diff": {"type": "string", "description": "a unified diff to check"},
                "staged": {"type": "boolean", "description": "check the staged git diff"},
            },
        },
    },
    {
        "name": "check_claim",
        "description": (
            "Verify structured claims an agent states: env_var, import, route_handler "
            "references, and outcome claims (tests_pass, endpoint_status, bug_fixed) "
            "graded by evidence. Never returns proven without machine-checkable evidence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _REPO_PROP,
                "claims": {"type": "array", "items": {"type": "object"}},
                "run": {
                    "type": "boolean",
                    "description": "allow re-running named test commands / local probes",
                },
            },
            "required": ["claims"],
        },
    },
    {
        "name": "audit",
        "description": "Sweep the whole repo (or given paths) for latent broken edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _REPO_PROP,
                "paths": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "suggest",
        "description": "Did-you-mean candidates for one reference of a given claim kind.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": _REPO_PROP,
                "kind": {"type": "string"},
                "subject": {"type": "string"},
            },
            "required": ["kind", "subject"],
        },
    },
    {
        "name": "index_status",
        "description": "Which oracles are enabled and built, the detected stack, and config.",
        "inputSchema": {"type": "object", "properties": {"repo": _REPO_PROP}},
    },
    {
        "name": "index",
        "description": "Build or refresh the per-repo index (incremental unless rebuild=true).",
        "inputSchema": {
            "type": "object",
            "properties": {"repo": _REPO_PROP, "rebuild": {"type": "boolean"}},
        },
    },
]


class ToolError(ValueError):
    """A bad tool invocation; reported as an MCP tool error, never a crash."""


def call_tool(
    name: str,
    args: dict[str, Any] | None = None,
    default_repo: str | None = None,
    store_path: str | None = None,
) -> dict[str, Any]:
    """Run one tool and return the same dict the CLI prints for the same input."""
    args = dict(args or {})
    repo = _resolve_repo(args.pop("repo", None), default_repo)
    match name:
        case "check_change":
            change = _change_from_args(args, repo)
            with gate.Session(repo, store_path=store_path) as s:
                result = s.check_change(change)
            ledger.record(result, repo, "mcp")
            return result.to_dict()
        case "check_claim":
            try:
                claims = gate.claims_from_json(args.get("claims", []))
            except (ValueError, TypeError) as exc:
                raise ToolError(f"invalid claims: {exc}") from exc
            with gate.Session(repo, store_path=store_path) as s:
                result = s.check_claims(claims, run=bool(args.get("run", False)))
            ledger.record(result, repo, "mcp")
            return result.to_dict()
        case "audit":
            from .eval import audit

            paths = args.get("paths") or None
            return audit.run(repo, paths=paths, store_path=store_path).to_dict()
        case "suggest":
            kind, subject = args.get("kind"), args.get("subject")
            if not kind or not subject:
                raise ToolError("suggest needs 'kind' and 'subject'")
            with gate.Session(repo, store_path=store_path) as s:
                return {
                    "kind": kind,
                    "subject": subject,
                    "suggestions": s.suggest(str(kind), str(subject)),
                }
        case "index_status":
            with gate.Session(repo, store_path=store_path) as s:
                return s.status()
        case "index":
            return gate.index(repo, rebuild=bool(args.get("rebuild", False)), store_path=store_path)
        case _:
            raise ToolError(f"unknown tool {name!r}")


def _resolve_repo(explicit: Any, default_repo: str | None) -> str:
    if explicit:
        return os.path.abspath(str(explicit))
    if default_repo:
        return os.path.abspath(default_repo)
    return find_repo_root(os.getcwd())


def _change_from_args(args: dict[str, Any], repo: str) -> Change:
    path, content, diff = args.get("path"), args.get("content"), args.get("diff")
    if content is not None:
        if not path:
            raise ToolError("check_change with 'content' needs 'path'")
        return Change.from_text(str(path), str(content))
    if diff is not None:
        return Change.from_unified_diff(str(diff))
    if args.get("staged"):
        return Change.from_git(repo, staged=True)
    targets = [str(path)] if path else [str(p) for p in (args.get("paths") or [])]
    if targets:
        changes: list[Change] = []
        for target in targets:
            full = target if os.path.isabs(target) else os.path.join(repo, target)
            if not os.path.exists(full):
                raise ToolError(f"no such file: {target}")
            changes.append(Change.from_path_or_diff(full, None, repo))
        return Change.combine(changes)
    raise ToolError(
        "check_change needs one of 'path', 'paths', 'content'+'path', 'diff', or 'staged'"
    )


# --- JSON-RPC plumbing -----------------------------------------------------------------------


def handle_message(
    msg: dict[str, Any], default_repo: str | None = None, store_path: str | None = None
) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC message. Returns the response, or None for notifications."""
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method is None:
        return None  # a response to something we sent; we send nothing
    if msg_id is None:
        return None  # notification: initialized, cancelled, progress...
    try:
        match method:
            case "initialize":
                result: dict[str, Any] = {
                    "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER_INFO,
                    "instructions": (
                        "weft verifies that code wires to the repo's own declarations. "
                        "Call check_change before writing a file; only a 'reject' verdict "
                        "is a proven broken wire."
                    ),
                }
            case "ping":
                result = {}
            case "tools/list":
                result = {"tools": TOOLS}
            case "tools/call":
                name = str(params.get("name", ""))
                arguments = params.get("arguments") or {}
                try:
                    payload = call_tool(name, arguments, default_repo, store_path)
                    result = _tool_result(payload, is_error=False)
                except (ToolError, ValueError, OSError, RuntimeError) as exc:
                    result = _tool_result({"error": str(exc)}, is_error=True)
                except NotImplementedError as exc:
                    result = _tool_result({"error": f"not implemented: {exc}"}, is_error=True)
            case _:
                return _error(msg_id, -32601, f"method not found: {method}")
    except Exception as exc:  # noqa: BLE001 - the loop must survive anything
        return _error(msg_id, -32603, f"internal error: {exc}")
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _tool_result(payload: dict[str, Any], is_error: bool) -> dict[str, Any]:
    text = json.dumps(payload, indent=2, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(
    default_repo: str | None = None,
    store_path: str | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Newline-delimited JSON-RPC over stdio until EOF."""
    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    for raw in inp:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _write(out, _error(None, -32700, "parse error"))
            continue
        if isinstance(msg, list):  # batch
            responses = [
                r
                for r in (
                    handle_message(m, default_repo, store_path) for m in msg if isinstance(m, dict)
                )
                if r is not None
            ]
            if responses:
                _write(out, responses)
            continue
        if not isinstance(msg, dict):
            _write(out, _error(None, -32600, "invalid request"))
            continue
        response = handle_message(msg, default_repo, store_path)
        if response is not None:
            _write(out, response)
    return 0


def _write(out: TextIO, payload: Any) -> None:
    out.write(json.dumps(payload, separators=(",", ":")) + "\n")
    out.flush()


if __name__ == "__main__":
    raise SystemExit(serve())
