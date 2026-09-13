"""Config precedence, the TOML subset parser, stack detection, repo-root discovery."""

import json
import os

import pytest

from tests.conftest import write
from weftgate.config import Config, _parse_toml_subset, detect_stack, find_repo_root, load_toml


def test_defaults_when_no_config(tmp_path):
    cfg = Config.load(str(tmp_path))
    assert cfg.oracles == ["env_vars", "imports_lockfile", "routes_fastapi"]
    assert cfg.block_on == "reject"
    assert cfg.sources == []


def test_repo_toml_then_env_override(tmp_path, monkeypatch):
    write(
        str(tmp_path),
        "weftgate.toml",
        '[weftgate]\noracles = ["env_vars"]\nblock_on = "review"\n'
        'env_declared_in = [".env.example", "settings.py"]\n\n'
        '[weftgate.routes_fastapi]\napp = "app.main:app"  # comment\n',
    )
    cfg = Config.load(str(tmp_path))
    assert cfg.oracles == ["env_vars"]
    assert cfg.block_on == "review"
    assert cfg.env_declared_in == [".env.example", "settings.py"]
    assert cfg.oracle_config("routes_fastapi") == {"app": "app.main:app"}
    assert any(s.startswith("repo:") for s in cfg.sources)

    monkeypatch.setenv("WEFTGATE_ORACLES", "imports_lockfile, env_vars")
    monkeypatch.setenv("WEFTGATE_BLOCK_ON", "never")
    cfg = Config.load(str(tmp_path))
    assert cfg.oracles == ["imports_lockfile", "env_vars"]
    assert cfg.block_on == "never"


def test_user_config_is_below_repo_config(tmp_path, monkeypatch):
    user = tmp_path / "config" / "weftgate"
    user.mkdir(parents=True)
    (user / "weftgate.toml").write_text('[weftgate]\nblock_on = "never"\noracles = ["env_vars"]\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    cfg = Config.load(str(repo))
    assert cfg.block_on == "never" and cfg.oracles == ["env_vars"]
    write(str(repo), ".weftgate.json", json.dumps({"weftgate": {"block_on": "reject"}}))
    cfg = Config.load(str(repo))
    assert cfg.block_on == "reject" and cfg.oracles == ["env_vars"]


def test_invalid_block_on_is_rejected(tmp_path):
    write(str(tmp_path), "weftgate.toml", '[weftgate]\nblock_on = "maybe"\n')
    with pytest.raises(ValueError):
        Config.load(str(tmp_path))


def test_toml_subset_parser_matches_tomllib():
    text = (
        '# top comment\n[weftgate]\noracles = ["a", "b"]  # trailing\nblock_on = "reject"\n'
        "n = 3\nf = 1.5\nflag = true\nempty = []\n[weftgate.routes_fastapi]\napp = 'x:app'\n"
    )
    subset = _parse_toml_subset(text)
    assert subset == load_toml(text)
    assert subset["weftgate"]["oracles"] == ["a", "b"]
    assert subset["weftgate"]["n"] == 3 and subset["weftgate"]["flag"] is True
    assert subset["weftgate"]["routes_fastapi"]["app"] == "x:app"


def test_detect_stack(tmp_path):
    write(str(tmp_path), "pyproject.toml", '[project]\ndependencies = ["fastapi"]\n')
    write(str(tmp_path), "package.json", '{"dependencies": {"express": "4"}}')
    assert detect_stack(str(tmp_path)) == ["express", "fastapi", "node", "python"]
    assert detect_stack(str(tmp_path), Config(stack=["go"])) == ["go"]


def test_find_repo_root(tmp_path):
    root = tmp_path / "proj"
    (root / "a" / "b").mkdir(parents=True)
    write(str(root), "weftgate.toml", "[weftgate]\n")
    assert find_repo_root(str(root / "a" / "b")) == str(root)
    lone = tmp_path / "lone"
    lone.mkdir()
    assert find_repo_root(str(lone)) == os.path.abspath(str(lone))
