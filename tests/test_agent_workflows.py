"""Real hook payload shapes, setup preservation and explicit activation boundaries."""

import json
import os

import pytest

from tests.conftest import write
from weftgate import hooks, setup
from weftgate.cli import main
from weftgate.config import load_toml
from weftgate.eval.fixture import write_fixture


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "repo")
    write_fixture(root, broken=True)
    return root


@pytest.mark.parametrize(
    "agent,payload,expected",
    [
        ("claude", {"stop_hook_active": False}, "block"),
        ("codex", {"stop_hook_active": False}, "block"),
        ("cursor", {"status": "completed", "loop_count": 0}, "followup_message"),
        (
            "antigravity",
            {"terminationReason": "model_stop", "fullyIdle": True, "executionNum": 1},
            "continue",
        ),
    ],
)
def test_each_native_hook_requests_repair_on_proven_failure(repo, capsys, agent, payload, expected):
    assert hooks.completion(agent, repo, json.dumps(payload)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result.get("decision") == expected or expected in result
    assert "DATABSE_URL" in json.dumps(result)


@pytest.mark.parametrize(
    "agent,payload",
    [
        ("claude", {"stop_hook_active": True}),
        ("codex", {"stop_hook_active": True}),
        ("cursor", {"status": "completed", "loop_count": 2}),
        ("cursor", {"status": "aborted", "loop_count": 0}),
        ("antigravity", {"terminationReason": "model_stop", "fullyIdle": True, "executionNum": 2}),
        ("antigravity", {"terminationReason": "error", "fullyIdle": True, "executionNum": 0}),
    ],
)
def test_native_hooks_do_not_loop_or_resume_interruptions(repo, capsys, agent, payload):
    hooks.completion(agent, repo, json.dumps(payload))
    assert json.loads(capsys.readouterr().out) == {}


def test_hook_is_soft_on_dynamic_code_bad_inputs_and_disabled_policy(repo, capsys):
    os.remove(os.path.join(repo, "app/broken.py"))
    write(repo, "app/dynamic.py", "import os\ndef read(k): return os.environ[k]\n")
    for payload in ("{}", "oops", "[]"):
        hooks.completion("claude", repo, payload)
        assert json.loads(capsys.readouterr().out) == {}
    write_fixture(repo, broken=True)
    cfg = os.path.join(repo, "weftgate.toml")
    with open(cfg) as handle:
        old = handle.read()
    with open(cfg, "w") as handle:
        handle.write(old.replace('block_on = "reject"', 'block_on = "never"'))
    hooks.completion("codex", repo, "{}")
    assert json.loads(capsys.readouterr().out) == {}


def test_setup_all_merges_rules_hooks_and_codex_config_idempotently(repo, capsys):
    write(repo, "AGENTS.md", "# Existing instructions\nPreserve this.\n")
    write(repo, ".codex/config.toml", '# Personal settings stay intact\nmodel = "example"\n')
    write(
        repo,
        ".cursor/hooks.json",
        json.dumps({"version": 1, "hooks": {"stop": [{"command": "my-check"}]}}),
    )
    write(repo, ".agents/hooks.json", json.dumps({"custom": {"Stop": []}}))
    assert setup.run(repo, agents=["all"], hooks=True, instructions=True, fmt="json") == 0
    first = json.loads(capsys.readouterr().out)
    assert not first["snippets"].get("codex")
    with open(os.path.join(repo, ".codex/config.toml")) as handle:
        text = handle.read()
    assert text.startswith("# Personal")
    assert load_toml(text)["mcp_servers"]["weftgate"]["args"] == ["mcp"]
    with open(os.path.join(repo, "AGENTS.md")) as handle:
        instructions = handle.read()
    assert instructions.startswith("# Existing") and "weftgate workflow" in instructions
    for rel in (
        ".codex/hooks.json",
        ".cursor/hooks.json",
        ".claude/settings.json",
        ".agents/hooks.json",
        ".agents/mcp_config.json",
    ):
        assert "weftgate" in open(os.path.join(repo, rel)).read()
    assert "my-check" in open(os.path.join(repo, ".cursor/hooks.json")).read()
    assert "custom" in open(os.path.join(repo, ".agents/hooks.json")).read()
    assert setup.run(repo, agents=["all"], hooks=True, instructions=True, fmt="json") == 0
    assert json.loads(capsys.readouterr().out)["written"] == []


def test_setup_dry_run_writes_nothing(repo, capsys):
    setup.run(repo, agents=["all"], hooks=True, instructions=True, dry_run=True)
    assert not os.path.exists(os.path.join(repo, ".codex"))
    assert not os.path.exists(os.path.join(repo, "AGENTS.md"))
    capsys.readouterr()


def test_setup_rejects_invalid_codex_toml_before_any_write(repo):
    write(repo, ".codex/config.toml", "broken toml ???")
    with pytest.raises(ValueError):
        setup.run(repo, agents=["all"], hooks=True, instructions=True)
    assert not os.path.exists(os.path.join(repo, ".mcp.json"))


def test_setup_refuses_symlink_destination_before_any_write(repo, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, os.path.join(repo, ".codex"))
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="symlink"):
        setup.run(repo, agents=["all"], hooks=True)
    assert not list(outside.iterdir())
    assert not os.path.exists(os.path.join(repo, ".mcp.json"))


def test_cli_native_hook_dispatch(repo, monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert main(["--repo", repo, "hook", "codex", "--event", "stop"]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "block"
    assert main(["--repo", repo, "hook", "cursor"]) == 2
    assert "use --event stop" in capsys.readouterr().err
