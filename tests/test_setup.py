"""weftgate setup and the Claude Code PreToolUse hook adapter."""

import json
import os
from pathlib import Path

import pytest

from tests.conftest import git, git_commit_all, git_init, have_git, write
from weftgate import setup
from weftgate.cli import main as cli_main
from weftgate.eval.fixture import write_fixture


def _repo(tmp_path):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    os.remove(os.path.join(root, "weftgate.toml"))
    return root


def test_setup_writes_config_and_builds_index(tmp_path, capsys):
    root = _repo(tmp_path)
    assert setup.run(root, dry_run=True) == 0
    out = capsys.readouterr().out
    assert "would write" in out and not os.path.exists(os.path.join(root, "weftgate.toml"))
    assert cli_main(["--repo", root, "--format", "json", "setup"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["written"] == ["weftgate.toml"] and "fastapi" in summary["stack"]
    assert summary["index"]["oracles"]["routes_fastapi"]["built"] is True
    text = Path(os.path.join(root, "weftgate.toml")).read_text(encoding="utf-8")
    assert 'app = "app.main:app"' in text and 'oracles = ["env_vars"' in text
    # A second run keeps the existing config unless forced.
    assert setup.run(root) == 0
    assert "keep" in capsys.readouterr().out
    write(root, "weftgate.toml", '[weftgate]\noracles = ["env_vars"]\n')
    assert setup.run(root, force=True) == 0
    assert "routes_fastapi" in Path(os.path.join(root, "weftgate.toml")).read_text(encoding="utf-8")


def test_setup_hooks_merge_without_clobbering(tmp_path, capsys):
    root = _repo(tmp_path)
    if have_git():
        git_init(root)
    write(
        root,
        ".claude/settings.json",
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls)"]},
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
                    ]
                },
            }
        ),
    )
    write(root, ".mcp.json", json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    assert setup.run(root, hooks=True) == 0
    settings = json.loads(
        Path(os.path.join(root, ".claude", "settings.json")).read_text(encoding="utf-8")
    )
    assert settings["permissions"] == {"allow": ["Bash(ls)"]}
    pre = settings["hooks"]["PreToolUse"]
    assert pre[0]["matcher"] == "Bash" and pre[1]["matcher"] == "Edit|Write|MultiEdit"
    assert pre[1]["hooks"][0]["command"] == "weftgate hook claude"
    mcp = json.loads(Path(os.path.join(root, ".mcp.json")).read_text(encoding="utf-8"))
    assert set(mcp["mcpServers"]) == {"other", "weftgate"}
    if have_git():
        hook = os.path.join(root, ".git", "hooks", "pre-commit")
        assert os.access(hook, os.X_OK) and "weftgate check --staged" in Path(hook).read_text(
            encoding="utf-8"
        )
    # Idempotent: running again changes nothing.
    assert setup.run(root, hooks=True) == 0
    assert (
        json.loads(Path(os.path.join(root, ".claude", "settings.json")).read_text(encoding="utf-8"))
        == settings
    )
    capsys.readouterr()


@pytest.mark.skipif(not have_git(), reason="git required")
def test_worktree_setup_preserves_shared_hook_and_doctor_detects_git(tmp_path, capsys):
    from weftgate import doctor

    root = _repo(tmp_path)
    git_init(root)
    git_commit_all(root)
    shared_hook = write(root, ".git/hooks/pre-commit", "#!/bin/sh\nweftgate check --staged\n")
    worktree = str(tmp_path / "linked")
    git(root, "worktree", "add", "-b", "linked", worktree)
    assert setup.run(worktree, hooks=True, agents=["codex"]) == 0
    assert "shared/external Git hook preserved" in capsys.readouterr().out
    assert Path(shared_hook).read_text(encoding="utf-8") == "#!/bin/sh\nweftgate check --staged\n"
    assert os.path.isfile(os.path.join(worktree, ".codex", "hooks.json"))
    checks = {c["name"]: c for c in doctor.run(worktree)["checks"]}
    assert checks["git"]["ok"] is True
    assert "git pre-commit" in checks["hooks"]["detail"]


def test_claude_hook_blocks_only_on_reject(tmp_path, capsys):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    store = str(tmp_path / "i.sqlite")
    target = os.path.join(root, "app", "new.py")

    def hook(payload):
        return setup.claude_hook(root, json.dumps(payload), store_path=store)

    bad_code = "import os\nx = os.environ['DATABSE_URL']\n"
    bad = {"tool_name": "Write", "tool_input": {"file_path": target, "content": bad_code}}
    assert hook(bad) == 2
    err = capsys.readouterr().err
    assert "weftgate blocked" in err and "did you mean DATABASE_URL" in err
    good_code = "import os\nx = os.environ['API_KEY']\n"
    good = {"tool_name": "Write", "tool_input": {"file_path": target, "content": good_code}}
    assert hook(good) == 0 and capsys.readouterr().out == ""
    soft = {
        "tool_name": "Write",
        "tool_input": {"file_path": target, "content": "import os\nx = os.environ[k]\n"},
    }
    assert hook(soft) == 0
    note = json.loads(capsys.readouterr().out)
    assert "weftgate notes" in note["hookSpecificOutput"]["additionalContext"]
    # Edit on an existing file reconstructs the new content.
    write(root, "app/new.py", "import os\nx = os.environ['API_KEY']\n")
    edit = {
        "tool_name": "Edit",
        "tool_input": {"file_path": target, "old_string": "API_KEY", "new_string": "API_KEYY"},
    }
    assert hook(edit) == 2
    capsys.readouterr()
    multi = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": target,
            "edits": [{"old_string": "API_KEY", "new_string": "REDIS_URL"}],
        },
    }
    assert hook(multi) == 0
    # Never block on garbage, unknown tools, or missing paths.
    assert setup.claude_hook(root, "not json", store_path=store) == 0
    assert hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}) == 0
    assert hook({"tool_name": "Write", "tool_input": {}}) == 0
    capsys.readouterr()


def test_reconstruct_content_shapes(tmp_path):
    p = write(str(tmp_path), "f.py", "a = 1\nb = 2\n")
    assert setup.reconstruct_content("Write", {"file_path": p, "content": "z"}) == "z"
    assert (
        setup.reconstruct_content(
            "Edit", {"file_path": p, "old_string": "b = 2", "new_string": "b = 3"}
        )
        == "a = 1\nb = 3\n"
    )
    assert (
        setup.reconstruct_content(
            "Edit", {"file_path": p + ".nope", "old_string": "", "new_string": "new"}
        )
        == "new"
    )
    assert (
        setup.reconstruct_content(
            "MultiEdit",
            {
                "file_path": p,
                "edits": [
                    {"old_string": "1", "new_string": "9", "replace_all": True},
                    {"old_string": "", "new_string": "c = 3\n"},
                ],
            },
        )
        == "a = 9\nb = 2\nc = 3\n"
    )
    assert setup.reconstruct_content("Bash", {"file_path": p}) is None
    assert setup.reconstruct_content("Write", {"file_path": p}) is None


def test_setup_agents_write_project_configs_and_print_snippets(tmp_path, capsys):
    root = _repo(tmp_path)
    write(root, ".vscode/mcp.json", json.dumps({"servers": {"other": {"command": "x"}}}))
    assert cli_main(["--repo", root, "--format", "json", "setup", "--agents", "all"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert set(summary["snippets"]) == {"windsurf", "claude-desktop"}
    assert json.loads(Path(os.path.join(root, ".mcp.json")).read_text(encoding="utf-8"))[
        "mcpServers"
    ]["weftgate"]["args"] == ["mcp"]
    assert (
        "weftgate"
        in json.loads(Path(os.path.join(root, ".cursor", "mcp.json")).read_text(encoding="utf-8"))[
            "mcpServers"
        ]
    )
    vscode = json.loads(
        Path(os.path.join(root, ".vscode", "mcp.json")).read_text(encoding="utf-8")
    )["servers"]
    assert set(vscode) == {"other", "weftgate"}
    # No Claude hook without --hooks; text mode prints the snippets.
    assert not os.path.exists(os.path.join(root, ".claude", "settings.json"))
    assert setup.run(root, agents=["codex"]) == 0
    out = capsys.readouterr().out
    assert ".codex/config.toml" in out
    assert "[mcp_servers.weftgate]" in Path(os.path.join(root, ".codex", "config.toml")).read_text(
        encoding="utf-8"
    )
    try:
        setup.run(root, agents=["nope"])
    except ValueError as exc:
        assert "unknown agent" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown agent accepted")
    capsys.readouterr()
