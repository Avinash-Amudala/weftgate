# A local second brain for coding agents: context, memory and gates in Weftgate 0.2

Preparation draft. [Published version, edited for length](https://dev.to/avinash_amudala_8712ab560/a-local-second-brain-for-coding-agents-context-memory-and-gates-in-weftgate-02-20ik).

Coding agents need more than another large context dump. They need a small set of
relevant source locations, decisions that are still current, and evidence that their
changes connect to the project correctly.

I maintain [Weftgate](https://github.com/Avinash-Amudala/weftgate). Version 0.2 puts
those three jobs in one local Python package: understand, remember and verify.

![Understand, remember, verify](https://raw.githubusercontent.com/Avinash-Amudala/weftgate/main/docs/assets/weftgate-brain.png)

[Watch the captioned 78-second demo](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.2.0/weftgate-demo.mp4).
It uses real CLI output from an intentionally broken fixture. It is a demonstration,
not a benchmark of accuracy on arbitrary repositories.

## Understand with bounded context

```bash
pip install weftgate
cd /path/to/your/repo
weftgate setup --agents codex,claude,cursor,antigravity --hooks --instructions
weftgate card "POST /orders" --budget 1200
```

Use a route that exists in your project. The card contains source locations and
static relationships between declarations, dependencies, env reads and route handlers.
It does not load file bodies or pretend to be a runtime call graph. Ambiguous names
and missing capabilities remain visible.

The default response is capped at 6,000 UTF-8 JSON bytes, including its accounting
fields. That is an estimate of 1,500 tokens, not a guarantee for every model tokenizer.
The ledger records actual payload bytes and omissions. It does not invent a savings
percentage or assume each rejected change avoided another agent run.

## Remember decisions, then recheck their sources

```bash
weftgate remember "Order idempotency" "Keep duplicate requests idempotent." --file app/orders.py
weftgate recall "orders"
```

The path must exist. Weftgate stores an explicit note in a repository-scoped local
SQLite database. On recall it checks the cited file hashes. If a file changes or
vanishes, the note is hidden by default. The original hashes stay intact until you
review and explicitly replace the note.

An unchanged file does not prove the saved prose true. Notes are untrusted context,
not higher-priority instructions. There is no automatic transcript capture, embedding
download or API key. The public package includes this mnemo-derived lexical notebook;
the separate private companion is not required.

## Verify connections and hand off evidence

The original gate checks env names, Python and Node imports, and static FastAPI or
Starlette references. `DATABSE_URL` can be rejected against a declared `DATABASE_URL`;
`os.environ[key]` remains advisory when the key cannot be resolved statically.

```toml
[weftgate.workflow]
commands = ["python -m pytest -q"]
```

```bash
weftgate checkpoint --run --require-ready
```

A checkpoint checks the current changed code, including staged and untracked source
files. With explicit execution enabled it observes configured, allowlisted test
commands. It distinguishes a proven failure, incomplete evidence, review findings,
and a repository that changed while checking. Ready means these checks and commands
passed against an unchanged file fingerprint. It does not certify the entire app.

## Use the same tools across editors

CLI and MCP use the same implementation. Setup writes project configuration and
workflow rules for Codex, Claude Code, Cursor and Antigravity. Their completion hooks
request bounded repair passes when a proven failure remains. Claude also has a
pre-edit adapter for supported Edit/Write/MultiEdit operations.

Trust and enable hooks in each editor. Codex uses `/hooks`. The other new adapters
run after writes, and no local hook is a complete enforcement boundary. Keep the
GitHub Action required in branch protection when merges must be gated.

The release has automated protocol fixtures, CLI/MCP parity checks, stale-memory
regressions and package isolation tests. See the [validation record](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/VALIDATION.md)
and [activation guide](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/AGENTS-INTEGRATION.md)
for scope and reproducible checks. Every editor build has not been interactively certified.

Try it on a project you know well. I would value reproducible reports about confusing
setup, useful context and false blocks. [Source and quickstart](https://github.com/Avinash-Amudala/weftgate).

*Disclosure: this article and launch assets were prepared with AI assistance. Code
behavior is backed by the linked tests and reproducible fixture evidence.*
