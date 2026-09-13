"""GitHub Action runner. Treat every workflow input as data, never shell code."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys


def command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, check=True, **kwargs)  # type: ignore[arg-type]


def install() -> None:
    ref = os.environ.get("INPUT_REF", "")
    target = (
        f"git+https://github.com/Avinash-Amudala/weftgate.git@{ref}"
        if ref
        else os.environ["GITHUB_ACTION_PATH"]
    )
    command([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", target])
    command(["weftgate", "--version"])


def run() -> int:
    mode = os.environ.get("INPUT_MODE", "check")
    block = os.environ.get("WEFTGATE_BLOCK_ON", "")
    if mode not in {"check", "audit"}:
        raise ValueError("mode must be check or audit")
    if block not in {"", "reject", "review", "never"}:
        raise ValueError("block-on must be reject, review, or never")
    if mode == "audit":
        paths = shlex.split(os.environ.get("INPUT_PATHS", ""))
        return subprocess.run(["weftgate", "audit", "--format=github", "--", *paths]).returncode
    base = os.environ.get("INPUT_BASE", "")
    pr_base = os.environ.get("PR_BASE", "")
    if not base and pr_base:
        command(["git", "check-ref-format", "refs/heads/" + pr_base], capture_output=True)
        shallow = command(["git", "rev-parse", "--is-shallow-repository"], capture_output=True)
        fetch = ["git", "fetch", "--no-tags"]
        if shallow.stdout.strip() == "true":
            fetch.append("--unshallow")
        command([*fetch, "origin", f"refs/heads/{pr_base}:refs/remotes/origin/{pr_base}"])
        base = "refs/remotes/origin/" + pr_base
    if not base:
        previous = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD~1"], text=True, capture_output=True
        )
        if previous.returncode == 0:
            base = previous.stdout.strip()
        else:
            # A one-commit shallow checkout is not necessarily the first commit.
            shallow = command(["git", "rev-parse", "--is-shallow-repository"], capture_output=True)
            if shallow.stdout.strip() == "true":
                raise ValueError("checkout history is shallow; use actions/checkout fetch-depth: 0")
            base = command(
                ["git", "hash-object", "-t", "tree", "--stdin"], input="", capture_output=True
            ).stdout.strip()
            diff = command(
                [
                    "git",
                    "diff",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-renames",
                    "-U0",
                    base,
                    "HEAD",
                    "--",
                ],
                capture_output=True,
            )
            return subprocess.run(
                ["weftgate", "check", "-", "--format=github"], input=diff.stdout, text=True
            ).returncode
    # Resolve first, preventing flags, revisions containing shell code, or paths
    # from ever being interpreted as git diff options.
    resolved = command(
        ["git", "rev-parse", "--verify", "--end-of-options", base + "^{commit}"],
        capture_output=True,
    ).stdout.strip()
    diff = command(
        [
            "git",
            "diff",
            "--no-color",
            "--no-ext-diff",
            "--no-renames",
            "-U0",
            resolved + "...HEAD",
            "--",
        ],
        capture_output=True,
    )
    return subprocess.run(
        ["weftgate", "check", "-", "--format=github"], input=diff.stdout, text=True
    ).returncode


def main() -> int:
    try:
        if sys.argv[1:] == ["install"]:
            install()
            return 0
        return run()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"weftgate action: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
