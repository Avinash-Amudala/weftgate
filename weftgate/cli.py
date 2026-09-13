"""The plain CLI. Identical findings to the MCP server: both call gate.* .

Commands:
  weftgate check [<paths>...|-] [--staged|--git]     verify files, directories, or a diff
  weftgate check --path REL --content FILE|-          verify content that is not on disk yet
  weftgate claim '<json>'|@file|-  [--run]            verify structured claims (claim mode)
  weftgate audit [paths...]                           sweep the repo for latent broken edges
  weftgate index [--rebuild] [--status] [--show X]    build/refresh the index, show it, or dump it
  weftgate memory anchor|check|changes [json]         grounding for verified memory (mnemo)
  weftgate doctor                                     explain the setup and what to fix
  weftgate ledger [--clear]                           blocked changes caught before they shipped
  weftgate suggest KIND SUBJECT                       did-you-mean for one reference
  weftgate eval mutate [--seed N] [--fixture]         mutation harness, reproducible
  weftgate setup [--hooks] [--agents a,b] [--dry-run] detect stack, write config, build index
  weftgate hook claude                                Claude Code PreToolUse hook (stdin JSON)
  weftgate mcp                                        start the stdio MCP server

Global options: --repo PATH, --format text|json|github, --store PATH.
Exit codes: 0 ok (or non-blocking), 1 blocking verdict, 2 usage or config error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__, gate
from .change import Change
from .config import find_repo_root
from .types import GateResult, Level

FORMATS = ("text", "json", "github")


# --- rendering (shared shape with the MCP server via GateResult.to_dict) --------------------------


def render(result: GateResult, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(result.to_dict(), indent=2, sort_keys=True)
    if fmt == "github":
        return render_github(result)
    return render_text(result)


def render_text(result: GateResult) -> str:
    lines: list[str] = []
    for f in result.findings:
        if f.level is Level.ACCEPT:
            continue
        tip = f"  (did you mean {', '.join(f.suggestions)}?)" if f.suggestions else ""
        lines.append(f"{f.level.value.upper():12} {str(f.claim.location):28} {f.reason}{tip}")
    st = result.stats
    summary = (
        f"verdict: {result.verdict.value}  "
        f"(claims {st.get('claims', 0)}, reject {st.get('reject', 0)}, "
        f"review {st.get('review', 0)}, unverifiable {st.get('unverifiable', 0)})"
    )
    errors = st.get("sync_errors") or {}
    for name, err in sorted(errors.items()):
        lines.append(f"note: oracle {name!r} index unavailable: {err}")
    if not lines:
        return f"ok, no broken wires found\n{summary}"
    return "\n".join([*lines, summary])


def render_github(result: GateResult) -> str:
    kinds = {Level.REJECT: "error", Level.REVIEW: "warning", Level.UNVERIFIABLE: "notice"}
    out: list[str] = []
    for f in result.findings:
        if f.level is Level.ACCEPT:
            continue
        loc = f.claim.location
        where = f"file={_gh_property(loc.file)}" + (f",line={loc.line}" if loc.line else "")
        msg = f.reason + (f" (did you mean {', '.join(f.suggestions)}?)" if f.suggestions else "")
        out.append(
            f"::{kinds[f.level]} {where},title=weftgate {_gh_property(f.oracle)}::{_gh_escape(msg)}"
        )
    out.append(f"verdict: {result.verdict.value}")
    return "\n".join(out)


def _gh_property(text: str) -> str:
    return _gh_escape(text).replace(":", "%3A").replace(",", "%2C")


def _gh_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


# --- argument parsing -----------------------------------------------------------------------------


def _global_options(parser: argparse.ArgumentParser, top: bool) -> None:
    """--repo/--format/--store are accepted before *and* after the subcommand.
    On subparsers the default is SUPPRESS so an absent option keeps the top-level value."""
    default: Any = argparse.SUPPRESS
    parser.add_argument(
        "--repo",
        default=None if top else default,
        help="repository root (default: nearest .git or weftgate.toml)",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default="text" if top else default,
        help="output format (default: text)",
    )
    parser.add_argument(
        "--store",
        default=None if top else default,
        help="explicit SQLite index path (default: cache dir)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="weftgate",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"weftgate {__version__}")
    _global_options(p, top=True)
    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("check", help="verify files, directories, or a diff")
    c.add_argument(
        "targets",
        nargs="*",
        default=[],
        help="files and/or directories, or '-' for a unified diff on stdin",
    )
    c.add_argument("--staged", action="store_true", help="check the staged git diff")
    c.add_argument("--git", action="store_true", help="check the working-tree git diff")
    c.add_argument("--path", help="repo-relative path for --content")
    c.add_argument("--content", help="file holding the new content, or '-' for stdin")

    cl = sub.add_parser("claim", help="verify structured claims")
    cl.add_argument("claims", nargs="?", default="-", help="JSON, @file, or '-' for stdin")
    cl.add_argument(
        "--run",
        action="store_true",
        help="allow re-running named test commands / probing local URLs",
    )

    a = sub.add_parser("audit", help="sweep the repo for latent broken edges")
    a.add_argument("paths", nargs="*", help="limit to these files or directories")

    i = sub.add_parser("index", help="build or refresh the index")
    i.add_argument("--rebuild", action="store_true")
    i.add_argument("--status", action="store_true")
    i.add_argument(
        "--show",
        choices=["env", "routes", "imports"],
        help="dump what an oracle indexed: declared env names, the route table, "
        "or provided packages",
    )

    mem = sub.add_parser("memory", help="anchors and self-invalidation for verified memory")
    msub = mem.add_subparsers(dest="memory_command")
    ma = msub.add_parser("anchor", help="anchors for a memory: {text, claims}")
    ma.add_argument("payload", nargs="?", default="-", help="JSON, @file, or '-' for stdin")
    mc = msub.add_parser("check", help="re-derive anchor states: {anchors: [...]}")
    mc.add_argument("payload", nargs="?", default="-", help="JSON, @file, or '-' for stdin")
    mg = msub.add_parser("changes", help="changed graph nodes since a sequence number")
    mg.add_argument("--since", type=int, default=0)

    sub.add_parser("doctor", help="explain the setup and what to fix")
    lg = sub.add_parser("ledger", help="blocked changes caught before they shipped")
    lg.add_argument("--clear", action="store_true", help="delete the ledger")

    s = sub.add_parser("suggest", help="did-you-mean for one reference")
    s.add_argument("kind")
    s.add_argument("subject")

    e = sub.add_parser("eval", help="measurement harnesses")
    esub = e.add_subparsers(dest="eval_command")
    m = esub.add_parser("mutate", help="inject known breakage and measure detection")
    m.add_argument("--seed", type=int, default=13)
    m.add_argument("--count", type=int, default=None, help="mutations per oracle")
    m.add_argument("--fixture", action="store_true", help="run on the built-in fixture repo")

    st = sub.add_parser("setup", help="detect stack, write config, build index, wire hooks")
    st.add_argument("--hooks", action="store_true", help="also write git + Claude Code hooks")
    st.add_argument("--dry-run", action="store_true")
    st.add_argument("--force", action="store_true", help="overwrite an existing weftgate.toml")
    st.add_argument(
        "--agents",
        default=None,
        help="comma-separated agents to configure: claude, cursor, vscode, codex, "
        "windsurf, claude-desktop, or all",
    )

    h = sub.add_parser("hook", help="agent hook adapters")
    h.add_argument("agent", choices=["claude"])

    sub.add_parser("mcp", help="start the stdio MCP server")
    for parser in (
        list(sub.choices.values()) + list(esub.choices.values()) + list(msub.choices.values())
    ):
        _global_options(parser, top=False)
    return p


# --- commands -------------------------------------------------------------------------------------


def _repo(args: argparse.Namespace, hint: str | None = None) -> str:
    if args.repo:
        return os.path.abspath(str(args.repo))
    return find_repo_root(hint or os.getcwd())


def _emit(result: GateResult, fmt: str, repo: str = ".", surface: str = "cli") -> int:
    from . import ledger

    ledger.record(result, repo, surface)
    print(render(result, fmt))
    return 1 if result.stats.get("blocking") else 0


def cmd_check(args: argparse.Namespace) -> int:
    if args.content is not None:
        if not args.path:
            raise SystemExit("weftgate check --content needs --path REL")
        text = sys.stdin.read() if args.content == "-" else _read(args.content)
        repo = _repo(args)
        change = Change.from_text(args.path, text)
    elif args.staged or args.git:
        repo = _repo(args)
        change = Change.from_git(repo, staged=args.staged)
    else:
        targets = list(args.targets) or ["-"]
        if targets == ["-"]:
            stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
            repo = _repo(args)
            change = Change.from_path_or_diff("-", stdin_text, repo)
        else:
            first = next((t for t in targets if os.path.exists(t)), None)
            repo = _repo(args, first)
            resolved: list[str] = []
            for t in targets:
                # A relative target that does not exist from the cwd is repo-relative.
                if not os.path.exists(t) and os.path.exists(os.path.join(repo, t)):
                    t = os.path.join(repo, t)
                elif not os.path.exists(t) and not _looks_like_diff(t):
                    raise SystemExit(f"no such file or directory: {t}")
                resolved.append(t)
            change = Change.combine(Change.from_path_or_diff(t, None, repo) for t in resolved)
    with gate.Session(repo, store_path=args.store) as session:
        return _emit(session.check_change(change), args.format, repo)


def cmd_claim(args: argparse.Namespace) -> int:
    raw = args.claims
    if raw == "-":
        text = sys.stdin.read()
    elif raw.startswith("@"):
        text = _read(raw[1:])
    else:
        text = raw
    try:
        data = json.loads(text)
        claims = gate.claims_from_json(data)
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"invalid claims: {exc}") from exc
    repo = _repo(args)
    with gate.Session(repo, store_path=args.store) as session:
        return _emit(session.check_claims(claims, run=args.run), args.format, repo)


def cmd_audit(args: argparse.Namespace) -> int:
    from .eval import audit

    repo = _repo(args)
    report = audit.run(repo, paths=args.paths or None, store_path=args.store)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    elif args.format == "github":
        print(render_github(report.result))
    else:
        print(audit.render_text(report))
    return 1 if report.result.stats.get("blocking") else 0


def cmd_index(args: argparse.Namespace) -> int:
    repo = _repo(args)
    with gate.Session(repo, store_path=args.store) as session:
        if args.show:
            session.sync()
            dump = _index_dump(session, args.show)
            print(
                json.dumps(dump, indent=2, sort_keys=True)
                if args.format == "json"
                else _render_dump(args.show, dump)
            )
            return 0
        if args.status:
            info: dict[str, Any] = session.status()
        else:
            report = session.sync(force_rebuild=args.rebuild)
            info = {
                "repo_root": session.store.repo_root,
                "store": session.store.path,
                "commit": session.ctx.git_commit,
                "oracles": report,
                "sync_errors": dict(session.sync_errors),
            }
    if args.format == "json":
        print(json.dumps(info, indent=2, sort_keys=True))
    else:
        print(_render_index(info, status=args.status))
    return 0


def _render_index(info: dict[str, Any], status: bool) -> str:
    store = info.get("store")
    store_path = store.get("path") if isinstance(store, dict) else store
    lines = [f"repo:   {info['repo_root']}", f"store:  {store_path}"]
    if status:
        lines.append(f"stack:  {', '.join(info.get('stack') or []) or '(unknown)'}")
        lines.append(f"commit: {info['store'].get('build_commit') or '(none)'}")
    else:
        lines.append(f"commit: {info.get('commit') or '(none)'}")
    for name, o in sorted(info.get("oracles", {}).items()):
        state = "built" if o.get("built") else "NOT built"
        tables = ", ".join(f"{t}={n}" for t, n in sorted(o.get("tables", {}).items())) or "-"
        action = f" [{o['action']}]" if "action" in o else ""
        lines.append(f"  {name:18} {state:9}{action}  {tables}")
    for name, err in sorted((info.get("sync_errors") or {}).items()):
        lines.append(f"  ! {name}: {err}")
    return "\n".join(lines)


def _index_dump(session: gate.Session, what: str) -> Any:
    from .oracles.env_vars import describe_declarations
    from .oracles.routes_fastapi import describe_routes

    match what:
        case "env":
            return describe_declarations(session.ctx)
        case "routes":
            return describe_routes(session.ctx)
        case _:
            ns = session.store.namespace("imports_lockfile")
            if not ns.exists("provided"):
                return {}
            out: dict[str, dict[str, list[str]]] = {}
            for lang, dist, source in ns.query(
                "SELECT DISTINCT lang, dist, source FROM {t:provided} ORDER BY lang, dist, source"
            ):
                out.setdefault(str(lang), {}).setdefault(str(dist), []).append(str(source))
            return out


def _render_dump(what: str, dump: Any) -> str:
    if what == "env":
        rows = [f"{name:40} {', '.join(files)}" for name, files in dump.items()]
        return "\n".join(rows) or "(none)"
    if what == "routes":
        rows = [
            f"{r['method']:9} {r['path']:40} {r['handler']:30} {r['file']}:{r['line']}"
            for r in dump
        ]
        return "\n".join(rows) or "(no routes)"
    lines = []
    for lang, dists in dump.items():
        lines.append(f"[{lang}]")
        lines.extend(f"  {dist:40} {', '.join(sources)}" for dist, sources in dists.items())
    return "\n".join(lines) or "(no lockfiles or manifests)"


def cmd_memory(args: argparse.Namespace) -> int:
    from . import memory

    if args.memory_command not in ("anchor", "check", "changes"):
        raise SystemExit("usage: weftgate memory anchor|check|changes")
    with gate.Session(_repo(args), store_path=args.store) as session:
        if args.memory_command == "changes":
            out = memory.changes(session, since=args.since)
        else:
            raw = args.payload
            text = (
                sys.stdin.read() if raw == "-" else (_read(raw[1:]) if raw.startswith("@") else raw)
            )
            try:
                data = json.loads(text) if text.strip() else {}
            except ValueError as exc:
                raise SystemExit(f"invalid JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise SystemExit("payload must be a JSON object")
            if args.memory_command == "anchor":
                out = memory.anchor(session, str(data.get("text", "")), data.get("claims"))
            else:
                out = memory.check(session, list(data.get("anchors") or []))
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor

    report = doctor.run(_repo(args), store_path=args.store)
    print(doctor.to_json(report) if args.format == "json" else doctor.render_text(report))
    return 0 if report.get("ok") else 1


def cmd_ledger(args: argparse.Namespace) -> int:
    from . import ledger

    if args.clear:
        ledger.clear()
        print("ledger cleared")
        return 0
    info = ledger.summary()
    print(
        json.dumps(info, indent=2, sort_keys=True)
        if args.format == "json"
        else ledger.render_text(info)
    )
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    with gate.Session(_repo(args), store_path=args.store) as session:
        names = session.suggest(args.kind, args.subject)
    if args.format == "json":
        print(json.dumps({"kind": args.kind, "subject": args.subject, "suggestions": names}))
    else:
        print("\n".join(names) if names else "(no suggestions)")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from .eval import mutate

    if args.eval_command != "mutate":
        raise SystemExit("usage: weftgate eval mutate [--seed N] [--fixture]")
    report = mutate.run(None if args.fixture else _repo(args), seed=args.seed, count=args.count)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(mutate.render_text(report))
    return 0 if report.misses == 0 else 1


def cmd_setup(args: argparse.Namespace) -> int:
    from . import setup

    agents = [a.strip() for a in str(args.agents or "").split(",") if a.strip()]
    return setup.run(
        _repo(args),
        hooks=args.hooks,
        dry_run=args.dry_run,
        force=args.force,
        fmt=args.format,
        agents=agents or None,
    )


def cmd_hook(args: argparse.Namespace) -> int:
    from . import setup

    return setup.claude_hook(_repo(args), sys.stdin.read(), store_path=args.store)


def cmd_mcp(args: argparse.Namespace) -> int:
    from . import mcp_server

    return mcp_server.serve(default_repo=args.repo, store_path=args.store)


_COMMANDS = {
    "check": cmd_check,
    "claim": cmd_claim,
    "audit": cmd_audit,
    "index": cmd_index,
    "suggest": cmd_suggest,
    "eval": cmd_eval,
    "setup": cmd_setup,
    "hook": cmd_hook,
    "mcp": cmd_mcp,
    "doctor": cmd_doctor,
    "ledger": cmd_ledger,
    "memory": cmd_memory,
}


def _looks_like_diff(text: str) -> bool:
    return text.startswith(("diff --git", "--- ", "+++ ", "@@")) or "\n" in text


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not args.command:
        parser.print_help()
        return 0
    try:
        return _COMMANDS[args.command](args)
    except SystemExit as exc:  # our own usage errors carry a message
        if isinstance(exc.code, str):
            print(f"weftgate: {exc.code}", file=sys.stderr)
            return 2
        raise
    except NotImplementedError as exc:
        print(f"weftgate: not implemented: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"weftgate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
