"""``weft setup``: detect the stack, write ``weft.toml``, build the index, and
optionally wire the git pre-commit hook, the Claude Code PreToolUse hook, and the
MCP server entry. Also the Claude Code hook adapter (``weft hook claude``).

The hook adapter reads the PreToolUse JSON on stdin, reconstructs the content
the Edit/Write/MultiEdit would produce, runs the gate on it, and exits 2 (which
Claude Code treats as "block, show stderr to the model") only on a blocking
verdict. Any internal error exits 0: a broken hook must never block work.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

from . import gate
from .change import Change
from .cli import render_text
from .config import Config, detect_stack, find_repo_root, repo_config_path
from .store import Store

PRE_COMMIT = """#!/usr/bin/env bash
# weft: block a commit only on a proven broken wire (a REJECT verdict).
if ! command -v weft >/dev/null 2>&1; then
  exit 0
fi
changed=$(git diff --cached --name-only --diff-filter=ACM)
[ -z "$changed" ] && exit 0
weft check --staged --format=github
"""

CLAUDE_HOOK = {
    "matcher": "Edit|Write|MultiEdit",
    "hooks": [{"type": "command", "command": "weft hook claude", "timeout": 60}],
}
MCP_ENTRY = {"command": "weft", "args": ["mcp"]}


# --- weft setup --------------------------------------------------------------------------


def run(
    repo_root: str,
    hooks: bool = False,
    dry_run: bool = False,
    force: bool = False,
    fmt: str = "text",
) -> int:
    repo_root = os.path.abspath(repo_root)
    stack = detect_stack(repo_root)
    plan: list[tuple[str, str, str]] = []  # (action, path, content-or-note)

    existing = repo_config_path(repo_root)
    if existing is None or force:
        plan.append(("write", "weft.toml", render_config(stack, find_fastapi_app(repo_root))))
    else:
        plan.append(("keep", os.path.relpath(existing, repo_root), "existing config kept"))

    if hooks:
        if os.path.isdir(os.path.join(repo_root, ".git")):
            plan.append(("write", ".git/hooks/pre-commit", PRE_COMMIT))
        settings_path = os.path.join(repo_root, ".claude", "settings.json")
        merged, changed = merge_claude_settings(_read_json(settings_path))
        plan.append(("write" if changed else "keep", ".claude/settings.json",
                     json.dumps(merged, indent=2) + "\n"))
        mcp_path = os.path.join(repo_root, ".mcp.json")
        mcp_cfg, changed = merge_mcp_config(_read_json(mcp_path))
        plan.append(("write" if changed else "keep", ".mcp.json",
                     json.dumps(mcp_cfg, indent=2) + "\n"))

    written: list[str] = []
    if not dry_run:
        for action, rel, content in plan:
            if action != "write":
                continue
            full = os.path.join(repo_root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(content)
            if rel.endswith("pre-commit"):
                os.chmod(full, 0o755)
            written.append(rel)
        index_report = gate.index(repo_root)
    else:
        index_report = {}

    summary: dict[str, Any] = {
        "repo_root": repo_root,
        "stack": stack,
        "dry_run": dry_run,
        "plan": [{"action": a, "path": p} for a, p, _ in plan],
        "written": written,
        "index": index_report,
    }
    if fmt == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(_render_setup(summary, plan))
    return 0


def render_config(stack: list[str], app: str | None) -> str:
    lines = [
        "# weft configuration. See docs/DESIGN.md section 12.",
        "[weft]",
        'oracles = ["env_vars", "imports_lockfile", "routes_fastapi"]',
        'block_on = "reject"                 # reject | review | never',
        'env_declared_in = [".env.example"]  # extra files/schemas that declare env vars',
    ]
    if stack:
        lines.append(f"stack = {json.dumps(stack)}")
    if app:
        lines += ["", "[weft.routes_fastapi]", f'app = "{app}"']
    return "\n".join(lines) + "\n"


def find_fastapi_app(repo_root: str) -> str | None:
    """``module:var`` of the first ``var = FastAPI(...)`` found (main/app files first)."""
    from .oracle import module_of_file

    store = Store(repo_root, path=os.path.join(_scratch(), "setup-scan.sqlite"))
    try:
        files = [f for f in store.all_files() if f.endswith(".py")]
    finally:
        store.close()
        _cleanup(os.path.join(_scratch(), "setup-scan.sqlite"))
    files.sort(key=lambda f: (0 if os.path.basename(f) in ("main.py", "app.py") else 1, f))
    pattern = re.compile(r"^\s*(\w+)\s*(?::\s*\w+\s*)?=\s*FastAPI\(", re.M)
    for rel in files:
        try:
            with open(os.path.join(repo_root, rel), encoding="utf-8", errors="ignore") as fh:
                text = fh.read(2_000_000)
        except OSError:
            continue
        m = pattern.search(text)
        module = module_of_file(rel)
        if m and module:
            return f"{module}:{m.group(1)}"
    return None


def merge_claude_settings(existing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    settings = dict(existing)
    hooks = dict(settings.get("hooks") or {})
    pre = list(hooks.get("PreToolUse") or [])
    for entry in pre:
        for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
            if isinstance(h, dict) and "weft hook claude" in str(h.get("command", "")):
                return settings, False
    pre.append(json.loads(json.dumps(CLAUDE_HOOK)))
    hooks["PreToolUse"] = pre
    settings["hooks"] = hooks
    return settings, True


def merge_mcp_config(existing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    cfg = dict(existing)
    servers = dict(cfg.get("mcpServers") or {})
    if "weft" in servers:
        return cfg, False
    servers["weft"] = dict(MCP_ENTRY)
    cfg["mcpServers"] = servers
    return cfg, True


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _scratch() -> str:
    import tempfile

    return tempfile.gettempdir()


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def _render_setup(summary: dict[str, Any], plan: list[tuple[str, str, str]]) -> str:
    lines = [f"repo:  {summary['repo_root']}",
             f"stack: {', '.join(summary['stack']) or '(not detected)'}"]
    for action, rel, note in plan:
        if action == "keep":
            lines.append(f"  keep   {rel}  ({note})")
        else:
            verb = "would write" if summary["dry_run"] else "wrote"
            lines.append(f"  {verb:10} {rel}")
    index = summary.get("index") or {}
    for name, o in sorted((index.get("oracles") or {}).items()):
        state = "built" if o.get("built") else "NOT built"
        lines.append(f"  index  {name:18} {state}")
    for name, err in sorted((index.get("sync_errors") or {}).items()):
        lines.append(f"  !      {name}: {err}")
    if not any(a == "write" and p.startswith(".claude") for a, p, _ in plan):
        lines.append("  hint   run `weft setup --hooks` to wire git pre-commit, the Claude Code "
                     "PreToolUse hook, and the MCP server entry")
    return "\n".join(lines)


# --- Claude Code PreToolUse hook adapter -------------------------------------------------


def claude_hook(repo_root: str, stdin_text: str, store_path: str | None = None) -> int:
    """Exit 2 with the findings on stderr only on a blocking verdict; otherwise 0."""
    try:
        payload = json.loads(stdin_text or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    if not file_path:
        return 0
    try:
        content = reconstruct_content(str(payload.get("tool_name") or ""), tool_input)
        if content is None:
            return 0
        root = repo_root if _inside(file_path, repo_root) else find_repo_root(file_path)
        rel = os.path.relpath(os.path.abspath(file_path), root) if os.path.isabs(
            file_path) else file_path
        with gate.Session(root, store_path=store_path) as session:
            result = session.check_change(Change.from_text(rel, content))
        config = session.config
    except Exception as exc:  # noqa: BLE001 - a broken hook must never block work
        print(f"weft hook: skipped ({exc})", file=sys.stderr)
        return 0
    if result.stats.get("blocking"):
        print("weft blocked this edit: it references something that does not resolve.\n"
              + render_text(result), file=sys.stderr)
        return 2
    notes = [f for f in result.findings if f.level.value in ("review", "unverifiable")]
    if notes:
        context = "weft notes (non-blocking):\n" + render_text(result)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": context}}))
    _ = config
    return 0


def reconstruct_content(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """The file content the tool call would produce, or None if not reconstructible."""
    file_path = str(tool_input.get("file_path") or "")
    if tool_name == "Write":
        content = tool_input.get("content")
        return str(content) if content is not None else None
    edits: list[dict[str, Any]]
    if tool_name == "Edit":
        edits = [tool_input]
    elif tool_name == "MultiEdit":
        edits = [e for e in (tool_input.get("edits") or []) if isinstance(e, dict)]
    else:
        return None
    current: str | None = None
    if os.path.isfile(file_path):
        with open(file_path, encoding="utf-8", errors="replace") as fh:
            current = fh.read()
    if current is None:
        return "\n".join(str(e.get("new_string") or "") for e in edits)
    for e in edits:
        old, new = str(e.get("old_string") or ""), str(e.get("new_string") or "")
        if not old:
            current = current + new
        elif e.get("replace_all"):
            current = current.replace(old, new)
        else:
            current = current.replace(old, new, 1)
    return current


def _inside(path: str, root: str) -> bool:
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:
        return False
    return not rel.startswith("..")


def default_config() -> Config:
    return Config()
