"""An evidence-based handoff checkpoint shared by CLI, MCP and completion hooks.

Checks current working-tree changes, including staged and untracked files. Test
commands run only with explicit opt-in. A passing command establishes its exit
status at this tree, never universal application correctness.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from . import honesty
from .change import Change
from .context import safe_path
from .gate import Session
from .payload import bounded


def current_change(session: Session) -> Change:
    store = session.store
    if not store.is_git_repo():
        return Change.combine(
            Change.from_file(os.path.join(session.repo_root, f), session.repo_root)
            for f in store.all_files()
            if safe_path(session.repo_root, f)
            and f.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
        )
    if store.current_commit() is None:
        return Change.combine(
            [Change.from_git(session.repo_root, staged=True), Change.from_git(session.repo_root)]
        )
    current = Change.from_git(session.repo_root, rev_range="HEAD")
    untracked = store._git("ls-files", "--others", "--exclude-standard", "-z")
    if untracked is None:
        raise RuntimeError("cannot enumerate untracked files")
    for file in sorted(untracked.split("\0")):
        if (
            file
            and safe_path(session.repo_root, file)
            and file.endswith((".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"))
        ):
            current.regions.extend(
                Change.from_file(os.path.join(session.repo_root, file), session.repo_root).regions
            )
    return current


def fingerprint(session: Session) -> str:
    digest = hashlib.sha256()
    for relative in session.store.all_files():
        path = safe_path(session.repo_root, relative)
        if path is None:
            continue
        digest.update(relative.encode())
        digest.update(b"\0")
        with open(path, "rb") as handle:
            while block := handle.read(128_000):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def checkpoint(
    session: Session,
    *,
    run: bool = False,
    budget: int | None = None,
) -> dict[str, Any]:
    if not isinstance(run, bool):
        raise ValueError("run must be a boolean")
    config = session.config.oracle_config("workflow")
    commands = config.get("commands", [])
    if (
        not isinstance(commands, list)
        or len(commands) > 8
        or any(
            not isinstance(command, str) or not command.strip() or len(command) > 500
            for command in commands
        )
    ):
        raise ValueError("[weftgate.workflow] commands must be up to 8 nonempty command strings")
    before = fingerprint(session)
    result = session.check_change(current_change(session))
    tests: list[dict[str, Any]] = []
    policy = honesty.Policy.from_config(session.config, session.repo_root, run)
    for command in commands:
        verdict = honesty.grade(honesty.OutcomeClaim("tests_pass", {"command": command}), policy)
        tests.append(
            {
                "command": command,
                "status": verdict.verdict.value,
                "reason": verdict.reason,
                "observed": verdict.observed,
            }
        )
    after = fingerprint(session)
    tests_failed = any(t["status"] == "contradicted" for t in tests)
    failed = result.verdict.value == "reject" or tests_failed
    observed = bool(tests) and all(t["status"] == "proven" for t in tests)
    uncertain = (
        result.verdict.value == "review"
        or any(f.level.value == "unverifiable" for f in result.findings)
        or bool(session.sync_errors)
    )
    state = (
        "blocked"
        if failed
        else "changed_during_check"
        if before != after
        else "needs_review"
        if uncertain
        else "needs_test_evidence"
        if not observed
        else "ready"
    )
    items = [{"finding": f.to_dict()} for f in result.findings if f.level.value != "accept"] + [
        {"test": t} for t in tests
    ]
    return bounded(
        items,
        {
            "operation": "checkpoint",
            "state": state,
            "blocking": tests_failed or (failed and bool(result.stats.get("blocking"))),
            "gate_verdict": result.verdict.value,
            "files_checked": len(result.stats.get("files", [])),
            "finding_count": len(result.findings),
            "tests_observed": observed,
            "tree_fingerprint": after,
            "tree_unchanged": before == after,
            "commit": session.ctx.git_commit,
            "next": (
                "Repair proven failures and run checkpoint again."
                if failed
                else "Review notes, run configured tests with --run, then hand off evidence."
                if state != "ready"
                else "Hand off this evidence and any untested behavior."
            ),
            "scope": "Current working tree and configured commands. Ready is scoped evidence, "
            "not proof of complete correctness. Re-run after changes.",
        },
        budget,
    )
