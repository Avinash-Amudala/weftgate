# Evidence before handoff

The workflow is: recall relevant decisions, resolve the code, make a focused change,
check the changed references, run project tests, and hand off observed evidence.
Weftgate supplies those tools. Your coding agent performs the reasoning and repair.

`weftgate checkpoint` checks current working-tree content against HEAD, including
staged changes and untracked source files. Without Git it checks source files in
the current directory tree. It does not assume that a clean gate means tests ran.

```toml
[weftgate.workflow]
commands = ["python -m pytest -q"]

# Optional additions for your project's own verification commands:
[weftgate.honesty]
allow_commands = ["ruff check", "mypy"]
timeout = 60
```

Commands use the existing allowlist, are run without a shell, and require `--run`
or MCP `run: true`. Test runners still execute repository code and may access the
network. Review repository configuration before opting in. At most eight commands
can be configured. Hook adapters never run these test commands automatically.

| State | Meaning |
| --- | --- |
| `blocked` | A gate found a proven false reference or an observed test command failed. |
| `needs_review` | Dynamic references or unavailable capabilities need attention. |
| `needs_test_evidence` | No configured test result was observed on this run. |
| `changed_during_check` | The indexed repository file fingerprint changed while checking. |
| `ready` | No reported unresolved gate findings, all configured commands exited zero, and the fingerprint stayed unchanged. |

The fingerprint covers tracked and unignored repository files, excluding the
index itself and configured ignored directories. It does not cover remote services,
installed dependencies, ignored build products or background processes. A passing
command proves its exit status, not its adequacy or the application's correctness.
Re-run after changing code. This is a current-run report, not a reusable certificate.

CLI exit 1 means an enforced failure, exit 2 an input/tool error, and exit 0 no
enforced failure. `--require-ready` adds exit 3 for incomplete evidence. This lets
teams require evidence explicitly without relabeling uncertainty as a falsehood.
The `block_on = "never"` gate setting remains respected; test failures still fail
an explicitly requested test checkpoint.

Native completion hooks request bounded repair passes on proven failures only.
Codex and Claude stop after an already continued turn; Cursor allows two follow-ups;
Antigravity requests continuation only for a normally completed, fully idle first
execution. Interruptions/errors are not resumed. Missing tests do not cause an
infinite loop. Use `checkpoint --run --require-ready` and required CI checks for
stronger handoff and merge policies.
