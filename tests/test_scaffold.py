"""scripts/new-oracle.py writes a compilable oracle plus its three tests."""

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_scaffold_writes_oracle_and_tests(tmp_path):
    root = str(tmp_path / "proj")
    os.makedirs(os.path.join(root, "weftgate", "oracles"))
    os.makedirs(os.path.join(root, "tests"))
    shutil.copy(
        os.path.join(REPO, "weftgate", "oracles", "__init__.py"),
        os.path.join(root, "weftgate", "oracles", "__init__.py"),
    )
    shutil.copy(os.path.join(REPO, "pyproject.toml"), os.path.join(root, "pyproject.toml"))
    script = os.path.join(REPO, "scripts", "new-oracle.py")
    proc = subprocess.run(
        [sys.executable, script, "config_keys", "--kind", "config_key", "--root", root],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    oracle = os.path.join(root, "weftgate", "oracles", "config_keys.py")
    test = os.path.join(root, "tests", "test_config_keys.py")
    assert os.path.isfile(oracle) and os.path.isfile(test)
    ast.parse(Path(oracle).read_text(encoding="utf-8"))  # compiles
    ast.parse(Path(test).read_text(encoding="utf-8"))
    src = Path(oracle).read_text(encoding="utf-8")
    assert "class ConfigKeysOracle(BaseOracle)" in src
    assert 'kinds: tuple[str, ...] = ("config_key",)' in src
    assert "def register(api: OracleAPI)" in src
    assert '"config_keys": "weftgate.oracles.config_keys:register"' in Path(
        os.path.join(root, "weftgate", "oracles", "__init__.py")
    ).read_text(encoding="utf-8")
    assert 'config_keys = "weftgate.oracles.config_keys:register"' in Path(
        os.path.join(root, "pyproject.toml")
    ).read_text(encoding="utf-8")
    # Refuses to overwrite.
    proc = subprocess.run(
        [sys.executable, script, "config_keys", "--kind", "config_key", "--root", root],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2 and "refusing" in proc.stderr
    # Out-of-tree package.
    proc = subprocess.run(
        [
            sys.executable,
            script,
            "feature_flags",
            "--kind",
            "flag",
            "--package",
            "mypkg",
            "--root",
            root,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert os.path.isfile(os.path.join(root, "mypkg", "feature_flags.py"))
    assert "entry point" in proc.stdout
