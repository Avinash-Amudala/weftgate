"""Test isolation: never touch the user's real cache or config."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "weft-test",
    "GIT_AUTHOR_EMAIL": "weft@example.invalid",
    "GIT_COMMITTER_NAME": "weft-test",
    "GIT_COMMITTER_EMAIL": "weft@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path_factory.mktemp("weft-home")
    monkeypatch.setenv("WEFT_CACHE", str(base / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(base / "xdg-cache"))
    monkeypatch.setenv("HOME", str(base / "home"))
    monkeypatch.delenv("WEFT_USER_CONFIG", raising=False)
    for key in ("WEFT_ORACLES", "WEFT_BLOCK_ON", "WEFT_ENV_DECLARED_IN", "WEFT_STACK"):
        monkeypatch.delenv(key, raising=False)
    for key, value in _GIT_ENV.items():
        monkeypatch.setenv(key, value)


def have_git() -> bool:
    return shutil.which("git") is not None


def git(root: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def git_init(root: str) -> None:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "weft-test")
    git(root, "config", "user.email", "weft@example.invalid")


def git_commit_all(root: str, msg: str = "c") -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg, "--allow-empty")
    return git(root, "rev-parse", "HEAD")


def write(root: str, rel: str, text: str) -> str:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
