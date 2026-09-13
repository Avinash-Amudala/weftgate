"""Offline end-to-end self-test. Creates the fixture repo in a temp dir and drives
the whole pipeline with no install, no git, and no network: index build, diff
mode across all three oracles, claim mode, the honesty gate, CLI/MCP parity,
incremental sync, the audit sweep, the mutation harness, and determinism.
Exits non-zero on any regression. Run this often while building.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Callable

from .change import Change
from .eval import audit, mutate
from .eval.fixture import write_fixture
from .gate import Session, claims_from_json
from .mcp_server import call_tool
from .types import Level

Check = tuple[str, Callable[[], None]]


class _Fail(AssertionError):
    pass


def _expect(cond: bool, msg: str) -> None:
    if not cond:
        raise _Fail(msg)


def _checks(root: str, store: str) -> list[Check]:
    broken_path = os.path.join(root, "app", "broken.py")

    def index_builds() -> None:
        with Session(root, store_path=store) as s:
            report = s.sync()
            _expect(all(r["built"] for r in report.values()), f"not all built: {report}")
            _expect(
                set(report) == {"env_vars", "imports_lockfile", "routes_fastapi"},
                f"unexpected oracle set {sorted(report)}",
            )
            _expect(not s.sync_errors, f"sync errors: {s.sync_errors}")
            st = s.status()
            _expect("fastapi" in st["stack"] and "python" in st["stack"], f"stack {st['stack']}")

    def diff_mode_rejects_broken_wires() -> None:
        with Session(root, store_path=store) as s:
            res = s.check_change(Change.from_file(broken_path, root))
        _expect(res.verdict is Level.REJECT, f"verdict {res.verdict}")
        by = {(f.oracle, f.claim.subject): f for f in res.findings}
        env = by[("env_vars", "DATABSE_URL")]
        _expect(
            env.level is Level.REJECT and env.suggestions[:1] == ("DATABASE_URL",),
            f"env finding {env}",
        )
        imp = by[("imports_lockfile", "requestz")]
        _expect(
            imp.level is Level.REJECT and imp.suggestions[:1] == ("requests",),
            f"import finding {imp}",
        )
        route = by[("routes_fastapi", "GET /late")]
        _expect(
            route.level is Level.REJECT and route.suggestions[:1] == ("health",),
            f"route finding {route}",
        )
        _expect(res.stats["reject"] == 3, f"expected 3 rejects: {res.stats}")
        _expect(res.stats["blocking"] is True, "reject must block by default")

    def diff_mode_accepts_clean_code() -> None:
        with Session(root, store_path=store) as s:
            for rel in ("app/main.py", "app/config.py", "app/tasks.py", "app/users.py"):
                res = s.check_change(Change.from_file(os.path.join(root, rel), root))
                _expect(res.verdict is Level.ACCEPT, f"{rel}: {res.verdict} {res.findings}")
                _expect(res.stats["claims"] > 0, f"{rel}: nothing extracted")

    def soft_cases_review_never_reject() -> None:
        soft = (
            "import os\nimport importlib\n"
            "from fastapi import FastAPI\nfrom app import handlers\n"
            "k = 'X'\nv = os.environ[k]\nm = importlib.import_module(k)\n"
            "app = FastAPI()\napp.add_api_route('/d', getattr(handlers, k))\n"
        )
        with Session(root, store_path=store) as s:
            res = s.check_change(Change.from_text("app/soft.py", soft))
        _expect(res.verdict is Level.REVIEW, f"soft verdict {res.verdict}: {res.findings}")
        _expect(res.stats["reject"] == 0 and res.stats["review"] == 3, f"stats {res.stats}")
        _expect(res.stats["blocking"] is False, "review must not block")

    def unverifiable_never_blocks() -> None:
        with tempfile.TemporaryDirectory() as empty:
            os.makedirs(os.path.join(empty, "x"))
            with open(os.path.join(empty, "x", "m.py"), "w", encoding="utf-8") as fh:
                fh.write("import requests\nimport os\nv = os.environ['NOPE']\n")
            with Session(empty, store_path=os.path.join(empty, "i.sqlite")) as s:
                res = s.check_change(Change.from_file(os.path.join(empty, "x", "m.py"), empty))
            imp = [f for f in res.findings if f.oracle == "imports_lockfile"][0]
            _expect(imp.level is Level.UNVERIFIABLE, f"no lockfile must be unverifiable: {imp}")
            env = [f for f in res.findings if f.oracle == "env_vars"][0]
            _expect(
                env.level is Level.REVIEW and "no env declaration source" in env.reason,
                f"a repo with no declaration source must review, not reject: {env}",
            )
            _expect(
                res.verdict is Level.REVIEW and res.stats["blocking"] is False,
                f"nothing here is a proven falsehood: {res.verdict}",
            )
            _expect(res.stats["unverifiable"] == 1, f"stats {res.stats}")

    def claim_mode_routes_and_honesty() -> None:
        claims = claims_from_json(
            [
                {"kind": "route", "method": "POST", "path": "/api/users", "handler": "create_user"},
                {"kind": "route", "method": "GET", "path": "/api/users/{id}"},
                {"kind": "route", "method": "DELETE", "path": "/api/users/{id}"},
                {"kind": "env_var", "subject": "API_KEY"},
                {"kind": "import", "subject": "yaml", "file": "x.py"},
                {"kind": "tests_pass", "command": "pytest -q"},
                {"kind": "tests_pass", "command": "pytest -q", "evidence": {"exit_code": 0}},
                {"kind": "tests_pass", "command": "pytest -q", "evidence": {"exit_code": 2}},
            ]
        )
        with Session(root, store_path=store) as s:
            res = s.check_claims(claims)
        levels = [f.level for f in res.findings]
        by_subject = {f.claim.subject: f for f in res.findings}
        _expect(by_subject["POST /api/users"].level is Level.ACCEPT, "route exists")
        _expect(by_subject["GET /api/users/{id}"].level is Level.ACCEPT, "param names differ")
        missing = by_subject["DELETE /api/users/{id}"]
        _expect(
            missing.level is Level.REJECT and bool(missing.suggestions), f"missing route {missing}"
        )
        _expect(by_subject["API_KEY"].level is Level.ACCEPT, "env claim")
        _expect(by_subject["yaml"].level is Level.ACCEPT, "import claim via alias")
        honesty = [f for f in res.findings if f.oracle == "honesty"]
        _expect(
            [f.claim.attrs["honesty"] for f in honesty]
            == ["not_observed", "plausible", "contradicted"],
            f"honesty grades {[f.claim.attrs['honesty'] for f in honesty]}",
        )
        _expect(
            all(f.claim.attrs["honesty"] != "proven" for f in honesty),
            "PROVEN must never appear without machine-checkable evidence",
        )
        _expect(Level.REJECT in levels and res.verdict is Level.REJECT, "contradicted rejects")

    def cli_and_mcp_agree() -> None:
        from .cli import render

        with Session(root, store_path=store) as s:
            via_session = s.check_change(Change.from_file(broken_path, root))
        via_cli = json.loads(render(via_session, "json"))
        via_mcp = call_tool(
            "check_change", {"repo": root, "path": "app/broken.py"}, store_path=store
        )
        _expect(via_cli == via_mcp, "CLI and MCP outputs differ")
        listing = call_tool("index_status", {"repo": root}, store_path=store)
        _expect(listing["oracles"]["routes_fastapi"]["built"] is True, "status via MCP")

    def incremental_sync_tracks_edits() -> None:
        env_path = os.path.join(root, ".env.example")
        with open(env_path, encoding="utf-8") as fh:
            original = fh.read()
        code = "import os\nv = os.environ['NEW_SETTING']\n"
        try:
            with Session(root, store_path=store) as s:
                _expect(
                    s.check_change(Change.from_text("app/n.py", code)).verdict is Level.REJECT,
                    "undeclared before the edit",
                )
            with open(env_path, "a", encoding="utf-8") as fh:
                fh.write("NEW_SETTING=\n")
            with Session(root, store_path=store) as s:
                report = s.sync()
                _expect(report["env_vars"]["action"] == "sync", f"expected sync: {report}")
                _expect(
                    s.check_change(Change.from_text("app/n.py", code)).verdict is Level.ACCEPT,
                    "declared after the edit",
                )
        finally:
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write(original)
            with Session(root, store_path=store) as s:
                s.sync()

    def audit_finds_the_planted_breakage() -> None:
        report = audit.run(root, store_path=store)
        _expect(report.rejects == 3, f"audit rejects {report.rejects}: {report.result.findings}")
        _expect(report.files_scanned >= 8, f"scanned {report.files_scanned}")

    def mutation_harness_has_no_misses() -> None:
        report = mutate.run(None, seed=13)
        _expect(report.total >= 9, f"too few mutations: {report.total}")
        _expect(report.misses == 0, "mutation misses:\n" + mutate.render_text(report))
        _expect(report.label == "upper bound", "fixture numbers are upper bounds")

    def deterministic() -> None:
        with Session(root, store_path=store) as s:
            a = s.check_change(Change.from_file(broken_path, root)).to_dict()
            b = s.check_change(Change.from_file(broken_path, root)).to_dict()
        _expect(a == b, "same input gave different output")
        _expect(
            mutate.run(None, seed=13).to_dict() == mutate.run(None, seed=13).to_dict(),
            "mutation harness is not deterministic",
        )

    def memory_grounds_and_invalidates() -> None:
        from . import memory

        env_path = os.path.join(root, ".env.example")
        with Session(root, store_path=store) as s:
            s.sync()
            grounded = memory.anchor(
                s,
                "the API reads DATABASE_URL; POST /api/users creates a user (app/users.py)",
                {"symbols": ["app/handlers.py:health"]},
            )
            nodes = {a["node"]: a for a in grounded["anchors"]}
            for node in (
                "env:DATABASE_URL",
                "route:POST /api/users",
                "file:app/users.py",
                "symbol:app/handlers.py:health",
            ):
                _expect(
                    nodes.get(node, {}).get("state") == "valid", f"anchor {node}: {nodes.get(node)}"
                )
            _expect(memory.check(s, grounded["anchors"])["summary"] == "valid", "fresh anchors")
            original = open(env_path, encoding="utf-8").read()
            seq = s.store.head_seq()
        try:
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write(original.replace("DATABASE_URL=postgres://localhost/app\n", ""))
            with Session(root, store_path=store) as s:
                changed = memory.changes(s, since=seq)
                ops = {c["node"]: c["op"] for c in changed["changes"]}
                _expect(ops.get("env:DATABASE_URL") == "removed", f"ledger {ops}")
                _expect(ops.get("file:.env.example") == "changed", f"ledger {ops}")
                res = memory.check(s, grounded["anchors"], sync=False)
                by = {a["node"]: a["state"] for a in res["anchors"]}
                _expect(
                    res["summary"] == "invalid" and by["env:DATABASE_URL"] == "invalid",
                    f"after removal: {by}",
                )
                _expect(by["route:POST /api/users"] == "valid", "unrelated anchors stay valid")
        finally:
            with open(env_path, "w", encoding="utf-8") as fh:
                fh.write(original)
        with Session(root, store_path=store) as s:
            _expect(memory.check(s, grounded["anchors"])["summary"] == "valid", "restored")
            # The mnemo plugin protocol: a declared false claim rejects, prose only reviews.
            registered: dict[str, tuple[object, object]] = {}

            class _Api:
                @staticmethod
                def register_oracle(kind: str, extract: object, check: object) -> None:
                    registered[kind] = (extract, check)

            memory.register(_Api)
            _expect(set(registered) == {"env", "routes", "imports"}, f"plugin kinds {registered}")
            check_env = registered["env"][1]
            _expect(check_env("DATABSE_URL", True, root)["status"] == "reject", "declared typo")  # type: ignore[operator]
            _expect(check_env("DATABSE_URL", False, root)["status"] == "review", "prose typo")  # type: ignore[operator]

    return [
        ("index builds", index_builds),
        ("diff mode rejects broken wires with suggestions", diff_mode_rejects_broken_wires),
        ("diff mode accepts clean code", diff_mode_accepts_clean_code),
        ("soft cases review, never reject", soft_cases_review_never_reject),
        ("unverifiable never blocks", unverifiable_never_blocks),
        ("claim mode routes + honesty", claim_mode_routes_and_honesty),
        ("cli and mcp agree", cli_and_mcp_agree),
        ("incremental sync tracks edits", incremental_sync_tracks_edits),
        ("audit finds the planted breakage", audit_finds_the_planted_breakage),
        ("mutation harness has no misses", mutation_harness_has_no_misses),
        ("deterministic", deterministic),
        ("memory grounds and self-invalidates", memory_grounds_and_invalidates),
    ]


def run(verbose: bool = True) -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix="weftgate-selftest-") as tmp:
        root = os.path.join(tmp, "repo")
        os.makedirs(root)
        write_fixture(root, broken=True)
        store = os.path.join(tmp, "index.sqlite")
        os.environ["WEFTGATE_CACHE"] = os.path.join(tmp, "cache")
        for name, fn in _checks(root, store):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - report every failure
                failures += 1
                print(f"FAIL  {name}: {exc}")
            else:
                if verbose:
                    print(f"ok    {name}")
    if failures:
        print(f"selftest FAILED: {failures} check(s)")
        return 1
    print("selftest ok: gate, three oracles, claim mode, surfaces, sync, audit, mutate, memory")
    return 0


if __name__ == "__main__":
    sys.exit(run())
