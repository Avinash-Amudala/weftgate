"""End-to-end context, memory freshness, budget and handoff evidence regressions."""

import json
import os
import sys

import pytest

from tests.conftest import git, git_commit_all, git_init, have_git, write
from weftgate import brain, context, recall, workflow
from weftgate.cli import main
from weftgate.eval.fixture import write_fixture
from weftgate.gate import Session
from weftgate.mcp_server import call_tool, handle_message
from weftgate.payload import bounded, encode


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "repo")
    write_fixture(root)
    return root


def test_resolve_card_and_neighbors_have_provenance(repo):
    with Session(repo) as s:
        result = context.query(s, "resolve", "DATABASE_URL")
        assert result["status"] == "resolved"
        assert result["items"][0]["node"]["locations"][0]["file"] == ".env.example"
        assert "postgres://" not in encode(result)
        card = context.query(s, "card", "POST /api/orders", budget=8000)
        nodes = [i["node"]["id"] for i in card["items"] if "node" in i]
        assert "symbol:app/orders.py:create_order" in nodes
        neighbor = context.query(s, "neighbors", "engine")
        assert any(i.get("edge", {}).get("to") == "env:DATABASE_URL" for i in neighbor["items"])
        assert context.query(s, "resolve", "MADE_UP_NAME")["status"] == "not_found"


def test_context_refreshes_same_session_and_rolls_back_bad_parse(repo):
    with Session(repo) as s:
        before = context.query(s, "resolve", "engine")
        assert before["status"] == "resolved"
        write(repo, "app/tasks.py", "def replacement():\n    return 1\n")
        assert context.query(s, "resolve", "engine")["status"] == "not_found"
        assert context.query(s, "resolve", "replacement")["status"] == "resolved"
        write(repo, "app/tasks.py", "def replacement(:\n")
        assert context.query(s, "resolve", "replacement")["status"] == "not_found"
        os.remove(os.path.join(repo, "app/tasks.py"))
        assert context.query(s, "resolve", "replacement")["status"] == "not_found"


def test_ambiguous_symbols_and_dynamic_notes(repo):
    write(repo, "other.py", "import os\ndef engine(key):\n    return os.environ[key]\n")
    with Session(repo) as s:
        result = context.query(s, "card", "engine", budget=8000)
        assert result["status"] == "ambiguous" and result["matches"] == 2
        assert any(i.get("note", {}).get("level") == "review" for i in result["items"])
        assert not any(i.get("edge", {}).get("to") == "env:key" for i in result["items"])


def test_context_deterministic_cached_and_respects_exclusion(repo):
    write(repo, "excluded/code.py", "def hidden(): pass\n")
    with Session(repo) as s:
        s.config.exclude = ["excluded"]
        first = context.query(s, "card", "engine")
        second = context.query(s, "card", "engine")
        assert first == second
        assert context.query(s, "resolve", "hidden")["status"] == "not_found"


def test_context_does_not_read_symlinks_or_file_bodies(repo, tmp_path):
    outside = tmp_path / "secret.py"
    outside.write_text("def private_secret(): pass\n")
    try:
        os.symlink(outside, os.path.join(repo, "link.py"))
    except OSError:
        pytest.skip("symlinks unavailable")
    with Session(repo) as s:
        assert context.query(s, "resolve", "private_secret")["status"] == "not_found"
        with pytest.raises(ValueError):
            recall.remember(s, "secret", "no", files=["link.py"])
        with pytest.raises(ValueError):
            recall.remember(s, "secret", "no", files=["../secret.py"])
    assert context.source(repo, "../secret.py") is None


@pytest.mark.parametrize("budget", [256, 257, 1500, 16000])
def test_budget_counts_exact_wire_bytes_and_omits_whole_items(budget):
    items = [{"name": f"test-{i}", "text": "脑🧠" * 50} for i in range(300)]
    out = bounded(items, {"operation": "example"}, budget)
    encoded = encode(out)
    assert out["usage"]["bytes"] == len(encoded.encode()) <= budget * 4
    assert len(out["items"]) + out["usage"]["omitted"] == len(items)
    wire = handle_message({"id": 1, "method": "ping"})
    assert wire["result"] == {}


@pytest.mark.parametrize("bad", [0, -1, True, "500", 16001])
def test_budget_rejects_invalid_values(bad):
    with pytest.raises(ValueError):
        bounded([], {}, bad)


def test_memory_lifecycle_hides_changed_and_deleted_sources(repo):
    with Session(repo) as s:
        saved = recall.remember(
            s, "Database engine", "Keep database setup here.", files=["app/tasks.py"]
        )
        assert saved["stored"] and saved["state"] == "anchored"
        found = recall.recall(s, "database")
        assert found["items"][0]["id"] == saved["id"]
        write(repo, "app/tasks.py", "def engine(): return 'changed'\n")
        for _ in range(2):
            found = recall.recall(s, "database")
            assert found["hidden_stale"] == 1 and not found["items"]
        stale = recall.recall(s, "database", include_stale=True)
        assert stale["items"][0]["state"] == "stale"
        # Only an explicit replacement updates the stored grounding.
        recall.remember(
            s,
            "Database engine",
            "Reviewed new implementation.",
            files=["app/tasks.py"],
            note_id=saved["id"],
        )
        assert recall.recall(s, "database")["items"][0]["state"] == "anchored"
        os.remove(os.path.join(repo, "app/tasks.py"))
        assert recall.recall(s, "database")["hidden_stale"] == 1
        assert recall.forget(s, saved["id"])["deleted"]
        assert not recall.forget(s, saved["id"])["deleted"]


def test_unanchored_notes_are_explicit_and_repo_isolated(repo, tmp_path):
    with Session(repo) as s:
        assert not recall.remember(s, "Missing", "No file", files=["missing.py"])["stored"]
        saved = recall.remember(s, "Use small changes", "A preference, not a proven fact.")
        assert saved["state"] == "unverified"
        assert recall.recall(s)["items"][0]["state"] == "unverified"
    other = str(tmp_path / "other")
    os.makedirs(other)
    with Session(other) as s:
        assert recall.recall(s)["items"] == []


def test_recall_searches_source_file_names(repo):
    with Session(repo) as session:
        saved = recall.remember(
            session, "Order contract", "Keep creation here.", files=["app/orders.py"]
        )
        found = recall.recall(session, "orders")
        assert found["items"][0]["id"] == saved["id"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("resolve", {"reference": "DATABASE_URL"}),
        ("neighbors", {"reference": "engine"}),
        ("card", {"reference": "POST /api/orders"}),
        ("recall", {"query": "nothing"}),
        ("checkpoint", {}),
    ],
)
def test_new_cli_mcp_parity_and_bounded_wire(repo, capsys, name, args):
    cli_args = ["--repo", repo, name]
    if "reference" in args:
        cli_args.append(args["reference"])
    if "query" in args:
        cli_args.append(args["query"])
    assert main(cli_args) == 0
    from_cli = json.loads(capsys.readouterr().out)
    assert from_cli == call_tool(name, args, default_repo=repo)
    message = handle_message(
        {"id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
        default_repo=repo,
    )
    wire = message["result"]["content"][0]["text"]
    assert len(wire.encode()) == from_cli["usage"]["bytes"]


@pytest.mark.skipif(not have_git(), reason="git unavailable")
def test_checkpoint_includes_staged_and_untracked_but_not_superseded_index(repo):
    git_init(repo)
    git_commit_all(repo)
    path = "app/staged.py"
    bad = "import os\nx = os.environ['DATABSE_URL']\n"
    write(repo, path, bad)
    git(repo, "add", path)
    with Session(repo) as s:
        assert workflow.checkpoint(s)["state"] == "blocked"
        write(repo, path, "import os\nx = os.environ['DATABASE_URL']\n")
        assert workflow.checkpoint(s)["state"] == "needs_test_evidence"
        write(repo, "untracked.py", bad)
        assert workflow.checkpoint(s)["state"] == "blocked"


def test_checkpoint_observes_tests_only_when_explicit(repo):
    write(
        repo,
        "test_example.py",
        "import unittest\nclass T(unittest.TestCase):\n"
        "    def test_ok(self): self.assertEqual(1, 1)\n",
    )
    # Use the current interpreter on every CI platform. Explicit allowlist entry
    # avoids assuming an unqualified python points to this environment.
    command = f'"{sys.executable}" -m unittest discover -q'
    with Session(repo) as s:
        s.config.per_oracle["workflow"] = {"commands": [command]}
        s.config.per_oracle["honesty"] = {"allow_commands": [command]}
        assert workflow.checkpoint(s)["state"] == "needs_test_evidence"
        assert workflow.checkpoint(s, run=True)["state"] == "ready"
        write(
            repo,
            "test_example.py",
            "import unittest\nclass T(unittest.TestCase):\n"
            "    def test_bad(self): self.fail('observed failure')\n",
        )
        result = workflow.checkpoint(s, run=True)
        assert result["state"] == "blocked" and result["blocking"]


def test_tool_catalog_exposes_every_new_operation():
    result = handle_message({"id": 1, "method": "tools/list"})
    names = {t["name"] for t in result["result"]["tools"]}
    assert set(brain.NAMES) <= names
