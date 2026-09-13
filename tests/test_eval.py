"""The measurement harnesses: audit finds planted breakage; mutate is seeded,
deterministic, detects and blocks every injected edge with a usable suggestion."""

import json
import os

from tests.conftest import write
from weftgate.cli import main as cli_main
from weftgate.eval import audit, mutate
from weftgate.eval.fixture import write_fixture
from weftgate.mcp_server import call_tool
from weftgate.types import Level


def test_audit_finds_planted_breakage_and_reuses_gate(tmp_path, capsys):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root, broken=True)
    store = str(tmp_path / "i.sqlite")
    report = audit.run(root, store_path=store)
    assert report.files_scanned == 8 and report.label == "field"
    by = {(f.oracle, f.claim.subject): f for f in report.result.findings}
    assert by[("env_vars", "DATABSE_URL")].level is Level.REJECT
    assert by[("env_vars", "DATABSE_URL")].suggestions == ("DATABASE_URL",)
    assert by[("imports_lockfile", "requestz")].level is Level.REJECT
    assert by[("routes_fastapi", "GET /late")].level is Level.REJECT
    assert by[("routes_fastapi", "GET /late")].suggestions[0] == "health"
    assert report.rejects == 3 and report.result.stats["blocking"] is True
    assert report.result.stats["accept"] > 10 and report.result.stats["mode"] == "audit"
    assert all(f.level is not Level.ACCEPT for f in report.result.findings)
    assert report.per_oracle["env_vars"]["reject"] == 1
    # Path filter, text rendering, and CLI/MCP parity.
    only = audit.run(root, paths=["app/users.py"], store_path=store)
    assert only.files_scanned == 1 and only.rejects == 0
    text = audit.render_text(report)
    assert "3 broken wires found" in text and "did you mean DATABASE_URL" in text
    code = cli_main(["--repo", root, "--store", store, "--format", "json", "audit"])
    via_cli = json.loads(capsys.readouterr().out)
    assert code == 1
    assert via_cli == call_tool("audit", {"repo": root}, store_path=store)
    assert cli_main(["--repo", root, "--store", store, "audit", "app/users.py"]) == 0
    assert "No broken wires found" in capsys.readouterr().out


def test_audit_clean_fixture(tmp_path):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    report = audit.run(root, store_path=str(tmp_path / "i.sqlite"))
    assert report.rejects == 0 and report.reviews == 0
    assert "No broken wires found" in audit.render_text(report)


def test_mutate_fixture_is_deterministic_and_fully_blocked():
    a = mutate.run(None, seed=13)
    b = mutate.run(None, seed=13)
    assert a.to_dict() == b.to_dict()
    assert a.label == "upper bound"
    assert a.total >= 9 and set(a.per_oracle) == {"env_vars", "imports_lockfile", "routes_fastapi"}
    assert a.detected == a.blocked == a.suggested == a.total, mutate.render_text(a)
    assert a.misses == 0
    ops = {m["op"] for m in a.mutations}
    assert {"typo_env", "typo_import"} <= ops and ops & {
        "typo_handler",
        "rename_def",
        "typo_router",
    }
    other = mutate.run(None, seed=7)
    assert other.total == a.total and other.misses == 0
    assert [m["mutated"] for m in other.mutations] != [m["mutated"] for m in a.mutations]


def test_mutate_on_a_copied_repo_never_touches_it(tmp_path, capsys):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    write(root, ".venv/lib/junk.py", "import nothing_here\n")
    before = {p: open(os.path.join(root, p)).read() for p in ("app/main.py", "app/config.py")}
    report = mutate.run(root, seed=3, count=2)
    assert report.label == "field" and report.total == 6 and report.misses == 0
    assert {p: open(os.path.join(root, p)).read() for p in before} == before
    code = cli_main(
        ["--repo", root, "--format", "json", "eval", "mutate", "--seed", "3", "--count", "2"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["total"] == 6
    assert cli_main(["--format", "json", "eval", "mutate", "--fixture", "--seed", "13"]) == 0
    assert json.loads(capsys.readouterr().out)["label"] == "upper bound"
    assert "misses" in mutate.render_text(report)
