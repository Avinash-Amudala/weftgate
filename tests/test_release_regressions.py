"""Regressions found during the release review, beyond the happy-path fixture."""

from __future__ import annotations

import json

import pytest

from tests.conftest import write
from weftgate import cli, memory
from weftgate.change import Change
from weftgate.config import Config
from weftgate.gate import Session, claims_from_json
from weftgate.honesty import Honesty, OutcomeClaim, grade
from weftgate.oracle import BaseOracle
from weftgate.types import Claim, Level, Location


def test_reused_session_refreshes_before_every_check(tmp_path):
    root = str(tmp_path)
    write(root, ".env.example", "DATABASE_URL=\n")
    claim = Claim("env_var", "NEW_NAME", Location("app.py"))
    with Session(root, config=Config(oracles=["env_vars"]), store_path=":memory:") as session:
        assert session.check_claims([claim]).verdict is Level.REJECT
        write(root, ".env.example", "DATABASE_URL=\nNEW_NAME=\n")
        assert session.check_claims([claim]).verdict is Level.ACCEPT


class FlakyOracle(BaseOracle):
    name = "flaky"
    kinds = ("flaky",)
    fail = False

    def build(self, ctx):
        ctx.store.namespace(self.name).rebuild(
            "rows", "file TEXT", [("new" if self.fail else "valid",)]
        )
        if self.fail:
            raise RuntimeError("partial write")

    def sync(self, ctx, since):
        self.build(ctx)

    def check(self, claim, ctx):
        return (
            self.reject(claim, "must not run after indexing failed")
            if self.fail
            else self.accept(claim, "ready")
        )


def test_failed_sync_preserves_tables_and_recovers_without_stale_errors(tmp_path):
    oracle = FlakyOracle()
    with Session(str(tmp_path), oracles={oracle.name: oracle}, store_path=":memory:") as session:
        session.sync()
        oracle.fail = True
        report = session.sync()
        assert report[oracle.name]["action"] == "failed"
        assert session.store.namespace(oracle.name).query("SELECT file FROM {t:rows}") == [
            ("valid",)
        ]
        claim = Claim("flaky", "x", Location("file"))
        assert session.check_claims([claim], sync=False).findings[0].level is Level.UNVERIFIABLE
        oracle.fail = False
        result = session.check_claims([claim])
        assert result.verdict is Level.ACCEPT and "sync_errors" not in result.stats


def test_config_change_rebuilds_env_contract(tmp_path):
    root = str(tmp_path)
    write(root, ".env.example", "DATABASE_URL=\n")
    write(root, "contract.txt", "CUSTOM_KEY=\n")
    path = str(tmp_path / "index.sqlite")
    claim = Claim("env_var", "CUSTOM_KEY", Location("app.py"))
    with Session(root, config=Config(oracles=["env_vars"]), store_path=path) as session:
        assert session.check_claims([claim]).verdict is Level.REJECT
    with Session(
        root, config=Config(oracles=["env_vars"], env_declared_in=["contract.txt"]), store_path=path
    ) as session:
        assert session.check_claims([claim]).verdict is Level.ACCEPT


def test_hidden_file_anchor_and_symbol_change_survive_forced_rebuild(tmp_path):
    root = str(tmp_path)
    write(root, ".env.example", "DATABASE_URL=\n")
    write(root, "app.py", "def health():\n    return 1\n")
    with Session(root, store_path=":memory:") as session:
        anchors = memory.anchor(
            session, claims={"files": [".env.example"], "symbols": ["app.py:health"]}
        )
        assert all(a["state"] == "valid" for a in anchors["anchors"])
        write(root, "app.py", "def health():\n    return 2\n")
        session.sync(force_rebuild=True)
        assert dict(session.last_changes)["symbol:app.py:health"] == "changed"
        assert memory.check(session, anchors["anchors"], sync=False)["summary"] == "stale"


def test_memory_pagination_does_not_skip_unreturned_changes(tmp_path, monkeypatch):
    with Session(str(tmp_path), oracles={}, store_path=":memory:") as session:
        session.store.record_changes(None, [("file:a", "changed"), ("file:b", "changed")])
        original = session.store.changes_since
        monkeypatch.setattr(session.store, "changes_since", lambda seq: original(seq, limit=1))
        first = memory.changes(session, since=0, sync=False)
        second = memory.changes(session, since=first["seq"], sync=False)
        assert [c["node"] for c in second["changes"]] == ["file:b"]


@pytest.mark.parametrize(
    "xml",
    [
        '<testsuite tests="1" failures="0"><testcase name="x"><failure/></testcase></testsuite>',
        '<testsuites><testsuite tests="1"><testsuite tests="1"><testcase><error/></testcase>'
        "</testsuite></testsuite></testsuites>",
    ],
)
def test_junit_failure_elements_cannot_be_overridden_by_summary_counts(tmp_path, xml):
    report = write(str(tmp_path), "report.xml", xml)
    result = grade(OutcomeClaim("tests_pass", {"report": report}))
    assert result.verdict is Honesty.CONTRADICTED


def test_skipped_tests_are_not_proven_passes(tmp_path):
    report = write(
        str(tmp_path),
        "report.xml",
        '<testsuite tests="1" skipped="1"><testcase><skipped/></testcase></testsuite>',
    )
    assert grade(OutcomeClaim("tests_pass", {"report": report})).verdict is Honesty.NOT_OBSERVED


@pytest.mark.parametrize(
    "raw",
    [
        {"kind": "env", "subject": "X", "hard": "false"},
        {"kind": "env", "subject": "X", "attrs": [1]},
        {"kind": "env", "subject": "X", "line": -1},
        {"kind": "env", "subject": "X", "source": "unrecognized"},
    ],
)
def test_malformed_claims_are_usage_errors(raw):
    with pytest.raises(ValueError):
        claims_from_json([raw])


def test_github_annotations_escape_file_and_title_properties():
    from weftgate.types import Finding, GateResult

    finding = Finding(
        Claim("env_var", "X", Location("a,b.py\n::error::injected", 1)),
        Level.REJECT,
        "missing",
        "a,b",
    )
    rendered = cli.render_github(GateResult.build([finding]))
    assert "file=a%2Cb.py%0A%3A%3Aerror%3A%3Ainjected" in rendered
    assert "title=weftgate a%2Cb" in rendered
    assert len(rendered.splitlines()) == 2


def test_eval_exit_code_counts_missing_suggestions_as_failure(tmp_path, monkeypatch, capsys):
    from weftgate.eval import mutate

    monkeypatch.setattr(mutate, "run", lambda *a, **k: mutate.MutationReport(13, 1, 1, 1, 0))
    assert cli.main(["eval", "mutate", "--fixture", "--format=json"]) == 1
    assert json.loads(capsys.readouterr().out)["misses"] == 1


def test_setup_preserves_existing_hooks_and_invalid_agent_config(tmp_path):
    from weftgate import setup

    (tmp_path / ".git/hooks").mkdir(parents=True)
    hook = tmp_path / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho existing\n")
    setup.run(str(tmp_path), hooks=True)
    assert "echo existing" in hook.read_text()
    config = tmp_path / ".mcp.json"
    config.write_text("{broken json")
    with pytest.raises(ValueError):
        setup.run(str(tmp_path), agents=["claude"])
    assert config.read_text() == "{broken json"


def test_routes_with_dynamic_paths_or_methods_cannot_prove_absence(tmp_path):
    write(
        str(tmp_path),
        "app.py",
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "@app.api_route(path, methods=methods)\ndef health(): pass\n",
    )
    with Session(str(tmp_path), store_path=":memory:") as session:
        result = session.check_claims(
            [Claim("route_handler", "POST /health", Location(""), source="assertion")]
        )
        assert result.verdict is Level.REVIEW


def test_corrupt_dependency_metadata_never_proves_a_phantom_import(tmp_path):
    write(str(tmp_path), "package-lock.json", "{broken json")
    with Session(str(tmp_path), store_path=":memory:") as session:
        result = session.check_change(Change.from_text("app.js", 'import express from "express";'))
        assert result.stats["reject"] == 0


def test_unrelated_nested_lock_does_not_prove_root_dependencies_complete(tmp_path):
    write(str(tmp_path), "pyproject.toml", '[project]\ndependencies = ["pytest"]\n')
    write(str(tmp_path), "examples/demo/uv.lock", '[[package]]\nname = "requests"\n')
    with Session(str(tmp_path), store_path=":memory:") as session:
        result = session.check_change(Change.from_text("app.py", "import phantom_dependency_zz\n"))
        assert result.verdict is Level.REVIEW


def test_rechecking_stale_memory_preserves_its_original_evidence(tmp_path):
    file = tmp_path / "app.py"
    file.write_text("TIMEOUT = 30\n")
    with Session(str(tmp_path), store_path=":memory:") as session:
        original = memory.anchor(session, claims={"files": ["app.py"]})
        file.write_text("TIMEOUT = 60\n")
        first = memory.check(session, original["anchors"])
        second = memory.check(session, first["anchors"])
        assert first["summary"] == second["summary"] == "stale"
        file.write_text("TIMEOUT = 30\n")
        assert memory.check(session, second["anchors"])["summary"] == "valid"


def test_dynamic_module_attributes_never_prove_missing_handler(tmp_path):
    write(str(tmp_path), "handlers.py", "def __getattr__(name):\n    return lambda: {}\n")
    text = (
        "from fastapi import FastAPI\nimport handlers\napp = FastAPI()\n"
        'app.add_api_route("/health", handlers.health)\n'
    )
    write(str(tmp_path), "app.py", text)
    with Session(str(tmp_path), store_path=":memory:") as session:
        assert session.check_change(Change.from_text("app.py", text)).verdict is Level.REVIEW


def test_diff_uses_context_to_avoid_docstring_and_optional_import_false_blocks(tmp_path):
    write(str(tmp_path), ".env.example", "DATABASE_URL=\n")
    write(str(tmp_path), "uv.lock", '[[package]]\nname = "requests"\n')
    write(
        str(tmp_path),
        "app.py",
        '"""Example:\nos.environ["DATABSE_URL"]\n"""\n'
        "try:\n    import optional_phantom_zz\nexcept ImportError:\n    pass\n",
    )
    diff = (
        '--- a/app.py\n+++ b/app.py\n@@ -1,0 +2 @@\n+os.environ["DATABSE_URL"]\n'
        "@@ -4,0 +5 @@\n+    import optional_phantom_zz\n"
    )
    with Session(str(tmp_path), store_path=":memory:") as session:
        result = session.check_change(Change.from_unified_diff(diff))
        assert result.verdict is Level.REVIEW
        assert [f.claim.subject for f in result.findings] == ["optional_phantom_zz"]


def test_factory_router_prevents_proving_route_absence(tmp_path):
    write(
        str(tmp_path),
        "app.py",
        "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(create_router())\n",
    )
    with Session(str(tmp_path), store_path=":memory:") as session:
        result = session.check_claims(
            [Claim("route_handler", "GET /runtime-route", Location(""), source="assertion")]
        )
        assert result.verdict is Level.REVIEW


def test_opt_in_probe_reports_redirect_without_following_it():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from weftgate.honesty import _probe

    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/must-not-be-requested")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        assert _probe(f"http://127.0.0.1:{server.server_port}/start", "GET", 2) == 302
        assert hits == ["/start"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
