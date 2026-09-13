"""Exercise the same runner used by the composite Action, including hostile inputs."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from tests.conftest import git_commit_all, git_init, write


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_action_audit_arguments_are_literal(monkeypatch):
    runner = load_script("action_runner")
    calls = []
    monkeypatch.setenv("INPUT_MODE", "audit")
    monkeypatch.setenv("INPUT_PATHS", "'folder with spaces' '$(touch OWNED)'")
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0),
    )
    assert runner.run() == 0
    assert calls == [
        ["weftgate", "audit", "--format=github", "--", "folder with spaces", "$(touch OWNED)"]
    ]


def test_action_install_ref_is_not_a_shell_program(monkeypatch):
    runner = load_script("action_runner")
    calls = []
    monkeypatch.setenv("INPUT_REF", "main; touch OWNED")
    monkeypatch.setattr(runner, "command", lambda args, **kw: calls.append(args))
    runner.install()
    assert calls[0][-1].endswith("@main; touch OWNED")
    assert "shell" not in calls[0]


@pytest.mark.parametrize("mode,block", [("typo", ""), ("audit", "typo")])
def test_action_rejects_invalid_configuration(monkeypatch, mode, block):
    runner = load_script("action_runner")
    monkeypatch.setenv("INPUT_MODE", mode)
    monkeypatch.setenv("WEFTGATE_BLOCK_ON", block)
    with pytest.raises(ValueError):
        runner.run()


def test_action_runs_on_initial_commit_and_subsequent_diff(tmp_path, monkeypatch):
    runner = load_script("action_runner")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "PATH", str(Path(os.sys.executable).parent) + os.pathsep + os.environ["PATH"]
    )
    for name in ("INPUT_BASE", "PR_BASE", "INPUT_MODE"):
        monkeypatch.delenv(name, raising=False)
    git_init(str(tmp_path))
    write(str(tmp_path), ".env.example", "DATABASE_URL=\n")
    write(str(tmp_path), "app.py", 'import os\nvalue = os.environ["DATABSE_URL"]\n')
    git_commit_all(str(tmp_path))
    assert runner.run() == 1
    write(str(tmp_path), "app.py", 'import os\nvalue = os.environ["DATABASE_URL"]\n')
    git_commit_all(str(tmp_path))
    assert runner.run() == 0


def test_release_notes_preserve_final_line_and_stop_at_next_version():
    script = load_script("release_notes")
    assert script.extract("# Log\n## [0.1.0]\nFirst.\nLast.\n", "v0.1.0") == "First.\nLast.\n"
    assert script.extract("## [0.1.0]\nNew.\n## [0.0.1]\nOld.\n", "v0.1.0") == "New.\n"
    with pytest.raises(ValueError):
        script.extract("## [0.1.0]\nNew.\n", "v0.2.0")


def test_rename_updates_config_env_and_package_without_editing_itself(tmp_path):
    import shutil

    root = str(tmp_path)
    git_init(root)
    write(root, "pyproject.toml", '[project]\nname = "oldgate"\n')
    write(root, "oldgate/__init__.py", 'NAME = "oldgate"\n')
    write(root, "oldgate.toml", '[oldgate]\nblock_on = "reject"\n')
    write(root, "README.md", "import oldgate\nOLDGATE_CACHE=x\n")
    script = Path(__file__).parents[1] / "scripts/rename.sh"
    (tmp_path / "scripts").mkdir()
    shutil.copy2(script, tmp_path / "scripts/rename.sh")
    shutil.copy2(script.with_suffix(".py"), tmp_path / "scripts/rename.py")
    git_commit_all(root)
    command = (
        [os.sys.executable, "scripts/rename.py"]
        if os.name == "nt"
        else ["bash", "scripts/rename.sh"]
    )
    subprocess.run([*command, "newgate"], cwd=root, check=True)
    assert (tmp_path / "newgate/__init__.py").read_text() == 'NAME = "newgate"\n'
    assert (tmp_path / "newgate.toml").read_text().startswith("[newgate]")
    assert "NEWGATE_CACHE" in (tmp_path / "README.md").read_text()
    assert (tmp_path / "scripts/rename.sh").read_bytes() == script.read_bytes()
