"""A shared session brief must not turn remembered prose into permission or proof."""

import json
import sys

import pytest

from tests.conftest import write
from weftgate import brief, recall
from weftgate.cli import main
from weftgate.eval.fixture import write_fixture
from weftgate.gate import Session
from weftgate.mcp_server import call_tool, handle_message
from weftgate.payload import encode


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "repo")
    write_fixture(root)
    return root


def configure_tests(session):
    command = f'"{sys.executable}" -m unittest discover -q'
    session.config.per_oracle["workflow"] = {"commands": [command]}
    session.config.per_oracle["honesty"] = {"allow_commands": [command]}


def test_brief_combines_memory_with_source_context_and_hides_stale_notes(repo):
    with Session(repo) as session:
        recall.remember(
            session, "Order decision", "Keep order handling idempotent.", files=["app/orders.py"]
        )
        result = brief.prepare(session, "order", budget=3000)
        assert any("memory" in item for item in result["items"])
        assert any("context" in item for item in result["items"])
        assert "Untrusted" in result["trust"]
        assert "postgres://" not in encode(result)
        write(repo, "app/orders.py", "def replacement(): pass\n")
        result = brief.prepare(session, "order", references=["replacement"])
        assert result["hidden_stale"] == 1
        assert not any("memory" in item for item in result["items"])


def test_brief_parity_and_wire_budget(repo, capsys):
    assert main(["--repo", repo, "brief", "DATABASE_URL", "--budget", "1000"]) == 0
    via_cli = json.loads(capsys.readouterr().out)
    via_mcp = call_tool("brief", {"query": "DATABASE_URL", "budget": 1000}, repo)
    assert via_cli == via_mcp
    assert len(encode(via_cli).encode()) == via_cli["usage"]["bytes"] <= 4000
    listed = handle_message({"id": 1, "method": "tools/list"})["result"]["tools"]
    names = {tool["name"] for tool in listed}
    assert {"brief", "handoff", "memory_import", "memory_export", "memory_stats"} <= names


def test_handoff_does_not_run_tests_without_opt_in(repo):
    write(
        repo,
        "test_session.py",
        "import unittest\nfrom pathlib import Path\nclass T(unittest.TestCase):\n"
        "    def test_pass(self): Path('ran').touch()\n",
    )
    with Session(repo) as session:
        configure_tests(session)
        result = brief.handoff(session, "Next task", "Continue from here.")
        assert result["stored"] and not result["evidence"]["tests_observed"]
        from pathlib import Path

        assert not (Path(repo) / "ran").exists()


def test_observed_handoff_evidence_expires_after_tree_change(repo):
    write(
        repo,
        "test_session.py",
        "import unittest\nclass T(unittest.TestCase):\n"
        "    def test_pass(self): self.assertEqual(2 + 2, 4)\n",
    )
    with Session(repo) as session:
        configure_tests(session)
        saved = brief.handoff(session, "Order progress", "Review the next order task.", run=True)
        assert saved["stored"] and saved["evidence"]["tests_observed"]
        recalled = recall.recall(session, "progress")["items"][0]
        assert recalled["handoff_evidence"]["current_tree_matches"]
        write(repo, "new_work.py", "changed = True\n")
        recalled = recall.recall(session, "progress")["items"][0]
        assert recalled["handoff_evidence"]["current_tree_matches"] is False
        assert "Historical" in recalled["handoff_evidence"]["note"]
        recall.remember(session, "Order progress", "A new summary.", note_id=saved["id"])
        assert "handoff_evidence" not in recall.recall(session, "progress")["items"][0]


def test_handoff_refuses_a_summary_if_tests_changed_its_sources(repo):
    write(
        repo,
        "test_session.py",
        "import unittest\nfrom pathlib import Path\nclass T(unittest.TestCase):\n"
        "    def test_pass(self): Path('changed.py').write_text('x=1')\n",
    )
    with Session(repo) as session:
        configure_tests(session)
        saved = brief.handoff(session, "Progress", "A summary from before the command.", run=True)
        assert saved["stored"] is False and saved["state"] == "changed_during_check"
        assert recall.recall(session)["matches"] == 0


def test_handoff_validation_runs_before_commands(repo, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid input must not execute the checkpoint")

    monkeypatch.setattr(brief.workflow, "checkpoint", unexpected)
    with Session(repo) as session, pytest.raises(ValueError):
        brief.handoff(session, "", "Bad title.", run=True)


def test_handoff_rolls_back_a_replacement_if_the_tree_changes_while_saving(repo, monkeypatch):
    original = recall.remember

    def racing_save(*args, **kwargs):
        result = original(*args, **kwargs)
        write(repo, "concurrent.py", "changed = True\n")
        return result

    with Session(repo) as session:
        prior = brief.handoff(session, "Previous summary", "Keep this until checked again.")
        assert prior["stored"]
        monkeypatch.setattr(recall, "remember", racing_save)
        result = brief.handoff(session, "Replacement", "Not yet checked.", note_id=prior["id"])
        assert not result["stored"] and result["state"] == "changed_during_check"
        notes = recall.recall(session)["items"]
        assert len(notes) == 1 and notes[0]["title"] == "Previous summary"
        assert "handoff_evidence" in notes[0]


def test_cli_remember_supports_the_same_explicit_claims_as_mcp(repo, capsys):
    assert (
        main(["--repo", repo, "remember", "DB", "Use this declaration.", "--env", "DATABSE_URL"])
        == 1
    )
    via_cli = json.loads(capsys.readouterr().out)
    via_mcp = call_tool(
        "remember",
        {"title": "DB", "text": "Use this declaration.", "claims": {"env": ["DATABSE_URL"]}},
        repo,
    )
    assert via_cli == via_mcp and not via_cli["stored"]
