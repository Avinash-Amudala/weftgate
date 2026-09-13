"""``weftgate doctor``: why is the gate saying what it says? Checks the setup and prints
actionable hints: config validity, enabled oracles and their index state, where env
declarations come from, which lockfiles/manifests were found (and whether any is a
real lockfile), whether a FastAPI app was found, and which hooks are installed.
Standard library only."""

from __future__ import annotations

import json
import os
from typing import Any

from .config import Config, detect_stack, repo_config_path
from .gate import Session


def run(repo_root: str, store_path: str | None = None) -> dict[str, Any]:
    repo_root = os.path.abspath(repo_root)
    report: dict[str, Any] = {"repo_root": repo_root, "checks": []}

    def add(name: str, ok: bool | None, detail: str, hint: str = "") -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail, "hint": hint})

    cfg_path = repo_config_path(repo_root)
    try:
        config = Config.load(repo_root)
        add(
            "config",
            True,
            f"{os.path.relpath(cfg_path, repo_root) if cfg_path else 'defaults'}"
            f" (block_on={config.block_on}, oracles={', '.join(config.oracles)})",
            "" if cfg_path else "run `weftgate setup` to write weftgate.toml",
        )
    except ValueError as exc:
        add(
            "config",
            False,
            str(exc),
            "fix weftgate.toml; the gate cannot run with an invalid config",
        )
        report["ok"] = False
        return report

    stack = detect_stack(repo_root, config)
    add(
        "stack",
        None,
        ", ".join(stack) or "not detected",
        "" if stack else "no packaging files found at the repo root; is this the right directory?",
    )

    with Session(repo_root, config=config, store_path=store_path) as s:
        is_git = s.store.is_git_repo()
        hook_location = s.store._git("rev-parse", "--git-path", "hooks/pre-commit")
        sync_report = s.sync()
        for name, info in sync_report.items():
            built = bool(info.get("built"))
            err = s.sync_errors.get(name, "")
            add(
                f"oracle {name}",
                built and not err,
                f"{'built' if built else 'NOT built'}; tables "
                f"{', '.join(f'{t}={n}' for t, n in sorted(info.get('tables', {}).items()))}",
                err or ("" if built else "run `weftgate index --rebuild`"),
            )
        ns = s.store.namespace("env_vars")
        if "env_vars" in s.oracles and ns.exists("decl"):
            rows = ns.query(
                "SELECT source, COUNT(DISTINCT name) FROM {t:decl} GROUP BY source ORDER BY source"
            )
            total = sum(int(r[1]) for r in rows)
            detail = ", ".join(f"{r[0]} {r[1]}" for r in rows) or "none"
            add(
                "env declarations",
                total > 0,
                f"{total} names from: {detail}",
                ""
                if total
                else "no .env.example or settings schema found: env reads will "
                "review, not reject, until one exists (or list your .env "
                "under env_declared_in)",
            )
        ns = s.store.namespace("imports_lockfile")
        if "imports_lockfile" in s.oracles and ns.exists("sources"):
            rows = ns.query("SELECT lang, source, kind FROM {t:sources} ORDER BY lang, source")
            locks = [str(r[1]) for r in rows if str(r[2]) == "lockfile"]
            manifests = [str(r[1]) for r in rows if str(r[2]) != "lockfile"]
            add(
                "dependency sources",
                bool(rows),
                f"lockfiles: {', '.join(locks) or 'none'}; manifests: "
                f"{', '.join(manifests) or 'none'}",
                ""
                if locks
                else (
                    "without a lockfile an unknown import reviews as 'may be "
                    "transitive'; commit uv.lock / poetry.lock / package-lock.json "
                    "(or pin requirements.txt) to make absence provable"
                ),
            )
        ns = s.store.namespace("routes_fastapi")
        if "routes_fastapi" in s.oracles and ns.exists("routes"):
            n_routes = ns.count("routes")
            uses = ns.query("SELECT COUNT(*) FROM {t:files} WHERE uses_fastapi=1")
            n_files = int(uses[0][0]) if uses else 0
            add(
                "fastapi routes",
                None,
                f"{n_routes} routes in {n_files} FastAPI/Starlette files",
                ""
                if n_files or "fastapi" not in stack
                else "FastAPI is a dependency but no route registrations were found",
            )
    add(
        "git",
        True if is_git else None,
        "git repo (including worktrees)" if is_git else "not a git repo",
        ""
        if is_git
        else "without git, sync uses a file fingerprint scan (fine, just slower on huge trees)",
    )
    hooks = {
        "git pre-commit": bool(hook_location)
        and _mentions(os.path.join(repo_root, (hook_location or "").strip()), "weftgate check"),
        "Claude Code hook": _mentions(
            os.path.join(repo_root, ".claude", "settings.json"), "weftgate hook claude"
        ),
        ".mcp.json": _mentions(os.path.join(repo_root, ".mcp.json"), '"weftgate"'),
        ".cursor/mcp.json": _mentions(os.path.join(repo_root, ".cursor", "mcp.json"), '"weftgate"'),
        ".vscode/mcp.json": _mentions(os.path.join(repo_root, ".vscode", "mcp.json"), '"weftgate"'),
    }
    installed = [k for k, v in hooks.items() if v]
    for agent, directory in (
        ("Codex", ".codex"),
        ("Cursor", ".cursor"),
        ("Antigravity", ".agents"),
    ):
        configured = _mentions(os.path.join(repo_root, directory, "hooks.json"), "weftgate hook")
        add(
            f"{agent} completion hook",
            None,
            "configured; runtime trust not inspected" if configured else "not configured",
            "Enable/trust the hook in the client; verify with a disposable broken fixture."
            if configured
            else f"weftgate setup --agents {agent.lower()} --hooks --instructions",
        )
    commands = config.oracle_config("workflow").get("commands", [])
    add(
        "workflow test evidence",
        None,
        f"{len(commands)} configured command(s)"
        if isinstance(commands, list)
        else "invalid command configuration",
        "Set [weftgate.workflow] commands, then run `weftgate checkpoint --run --require-ready`.",
    )
    add(
        "hooks",
        None,
        ", ".join(installed) or "none installed",
        "" if installed else "run `weftgate setup --hooks --agents all`",
    )
    report["ok"] = all(c["ok"] is not False for c in report["checks"])
    return report


def _mentions(path: str, needle: str) -> bool:
    try:
        with open(path, encoding="utf-8") as fh:
            return needle in fh.read()
    except OSError:
        return False


def render_text(report: dict[str, Any]) -> str:
    lines = [f"weftgate doctor: {report['repo_root']}"]
    for c in report["checks"]:
        mark = "ok " if c["ok"] else ("!! " if c["ok"] is False else "-- ")
        lines.append(f"  {mark} {c['name']:22} {c['detail']}")
        if c["hint"]:
            lines.append(f"       hint: {c['hint']}")
    lines.append(
        "everything the gate needs is in place" if report.get("ok") else "fix the !! items above"
    )
    return "\n".join(lines)


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)
