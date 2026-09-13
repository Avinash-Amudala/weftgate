# weftgate

**A local second brain for coding agents. Understand the code. Remember decisions. Verify changes.**

[![CI](https://github.com/Avinash-Amudala/weftgate/actions/workflows/ci.yml/badge.svg)](https://github.com/Avinash-Amudala/weftgate/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/weftgate)](https://pypi.org/project/weftgate/)
[![GitHub Marketplace](https://img.shields.io/badge/Marketplace-weftgate-purple)](https://github.com/marketplace/actions/weftgate)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/Avinash-Amudala/weftgate/blob/main/pyproject.toml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/Avinash-Amudala/weftgate/blob/main/LICENSE)

Give your agent compact source context, durable decisions and verification gates
through **one install, one MCP server and one local memory store**. Weftgate brings
Mnemo’s local memory workflow into the verification engine. You do not need to
install or configure a second project for everyday use.

![Weftgate brain: understand, remember, verify](https://raw.githubusercontent.com/Avinash-Amudala/weftgate/main/docs/assets/weftgate-brain.png)

| Understand | Remember | Verify |
| --- | --- | --- |
| Start with relevant memories and current source references. | Check explicit memory claims; hide stale notes; resume in another agent. | Check code connections and save a handoff with observed test evidence. |
| `weftgate brief "order retries"` | `weftgate remember ... --env DATABASE_URL` | `weftgate handoff ... --run` |

**No API key. No runtime dependencies. Local storage. No automatic transcript capture.**
Context, recall and default verification make no network calls. Explicitly enabled
test commands run your repository's code and can have their own side effects.

[![Watch the 78-second motion demo](https://raw.githubusercontent.com/Avinash-Amudala/weftgate/main/docs/assets/demo.gif)](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.2.0/weftgate-demo.mp4)

[Watch the v0.2 foundation demo](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.2.0/weftgate-demo.mp4) ·
[Transcript and reproducible evidence](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/DEMO.md) · [How to write an oracle](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/ORACLES.md)

## Try it

```bash
pip install weftgate
cd /path/to/your/repo
weftgate setup --agents codex,claude,cursor,antigravity --hooks --instructions
weftgate doctor                   # inspect coverage and configured integrations
weftgate audit                    # find existing broken connections
weftgate brief "your next task"   # memories + current source context
weftgate memory stats             # one local notebook and freshness counts
weftgate checkpoint               # changed code + evidence still needed
```

From source: `pip install git+https://github.com/Avinash-Amudala/weftgate.git`.
For development, `bash scripts/bootstrap.sh` installs the extras and runs the offline self-test.

The demo uses an intentionally broken fixture, not a field benchmark:

```text
REJECT  import 'requestz'       → did you mean requests?
REJECT  env var 'DATABSE_URL'   → did you mean DATABASE_URL?
REJECT  handler 'helth'         → did you mean health?
```

Fix the three names and the fixture passes. A computed key such as `os.environ[key]`
returns `review`, because static analysis cannot establish its value.
To reproduce: `weftgate eval mutate --fixture --seed 13`.

## What the result means

| Result | Meaning | Blocks by default? |
| --- | --- | --- |
| `accept` | The extracted reference resolves, or nothing checkable was found. | No |
| `review` | Evidence is incomplete or the reference is dynamic. | No |
| `reject` | A hard claim contradicts the indexed contract. | Yes |
| `unverifiable` | The relevant index or capability is unavailable. | No |

The rule is **block only on a positive, machine-checkable falsehood**. Suggestions
accompany findings when a nearby candidate exists. An `accept` verdict is not a test
suite result or proof that the application works; inspect coverage with `weftgate doctor`.

## Supported verification contracts

| Oracle | Checks | Conservative limits |
| --- | --- | --- |
| Environment variables | Reads against dotenv examples, settings schemas, Docker/Compose declarations, code defaults, and configured files. | Dynamic keys and absent declaration sources soften. Declare externally supplied variables in your contract. |
| Python and Node imports | Imports against dependency metadata, local packages, known package aliases, and supported path aliases. | A manifest alone cannot prove a complete dependency tree. Unknown mappings and optional imports review. |
| FastAPI / Starlette routes | Handler references, router includes, and route claims using a static AST index. | Computed registration, external modules, and unresolved prefixes cannot be fully verified. |

This is an early static analyzer with bounded parsers. It does not execute your app,
replace tests or a security scanner, or cover every framework. Python, Node, and
monorepo import resolution can depend on runtime configuration. Missing or ambiguous
evidence must soften; please [report a false block](https://github.com/Avinash-Amudala/weftgate/issues/new/choose)
with a minimal reproduction. [Historical field runs](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/FIELD-RESULTS.md) document
methods and limitations, rather than a claim of zero false positives.

## Use it with your agent

```bash
weftgate setup --agents all --hooks --instructions --dry-run
weftgate setup --agents codex,claude,cursor,antigravity --hooks --instructions
```

The standard-library MCP server requires no extra package. Example MCP configuration:

```json
{"mcpServers": {"weftgate": {"command": "weftgate", "args": ["mcp"]}}}
```

Run the server with the repository as its working directory. `weftgate setup --agents all`
writes supported project configs and prints snippets for clients with global settings.
CLI and MCP use the same functions. Start with `brief`, save decisions with
`remember`, and use `handoff` for the next session. Focused context, recall,
checkpoints, memory transfer and the existing verification tools remain available.

| Client | Context and recall | Native gate installed by setup |
| --- | --- | --- |
| Codex | Project MCP + AGENTS.md guidance | Stop hook requests one repair continuation. Trust via `/hooks`. |
| Claude Code | Project MCP + rules | Pre-edit gate for Edit/Write/MultiEdit; Stop check catches other writes. |
| Cursor | Project MCP + always-applied rule | Stop hook with up to two repair follow-ups. |
| Antigravity | Project MCP + workspace rule | Stop hook for an idle, normally completed run, with a bounded continuation. |
| VS Code / Copilot, Windsurf, Claude Desktop | MCP setup or printed configuration | Use the CLI, Git hook and CI for gating. |

Client versions, project trust and organization policy affect hook activation.
MCP tools and rules alone do not force an agent to use the gate. Local hooks are
guardrails; require the GitHub Action in branch protection to enforce merge checks.
[Integration paths, activation checks and official references](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/AGENTS-INTEGRATION.md).

## A small agent workflow

```bash
weftgate brief "order retries" --reference app/orders.py --budget 1200
weftgate remember "Order idempotency" "Keep duplicate requests idempotent." --file app/orders.py
# Your coding agent makes the change. Then:
weftgate check app/orders.py
weftgate handoff "Order retries" "Added retry handling. Next: review timeout behavior." --file app/orders.py --run --require-ready
# In Codex, Claude Code, Cursor or another MCP client:
weftgate brief "order retries"
```

Use paths and routes that exist in your project. Configure the commands the last
step should observe in `weftgate.toml`:

```toml
[weftgate.workflow]
commands = ["python -m pytest -q"]
```

`--run` explicitly permits execution of configured, allowlisted commands. A checkpoint
distinguishes proven failures, review findings, missing test evidence and changes
during verification. `--require-ready` exits 3 when evidence is incomplete. A ready
checkpoint covers those contracts and commands only. [Workflow details](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/WORKFLOWS.md).

Context responses contain source pointers, not file bodies. The default budget is
1,500 estimated tokens with a hard cap of 6,000 UTF-8 JSON bytes. Actual model token
counts vary. `weftgate ledger` reports payload bytes and gate events; it does not
invent a savings percentage or equate every rejection with an avoided retry.
[Context coverage and budgets](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/CONTEXT.md).

## CLI and CI

```bash
git diff | weftgate check -
weftgate check --staged
weftgate check --path app/main.py --content proposed.py
weftgate claim '[{"kind":"route","method":"POST","path":"/users"}]'
weftgate audit --format=json
weftgate index --show routes
```

Exit codes: **0** allows the change, **1** blocks according to policy, **2** means a
usage or configuration error. Use `--format=github` for workflow annotations.

```yaml
name: Verify connections
on: [pull_request]
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: Avinash-Amudala/weftgate@v0.3.0
        with:
          mode: check             # or audit to inspect the repository
```

The Action supports `base`, `paths` (shell-quoted paths, no shell expansion),
`block-on`, and `python-version`. Use a full checkout for diff ancestry.
The [pre-commit hooks](https://github.com/Avinash-Amudala/weftgate/blob/main/.pre-commit-hooks.yaml) use the same gate; pin `rev: v0.3.0`.

## Configure the contract

```toml
# weftgate.toml
[weftgate]
oracles = ["env_vars", "imports_lockfile", "routes_fastapi"]
block_on = "reject"                 # reject | review | never
env_declared_in = [".env.example"]
```

Precedence: `WEFTGATE_*` environment variables, repository configuration, user
configuration, then defaults. The index lives in the user cache, outside the repo.
`weftgate doctor` explains the selected configuration and missing contracts.

Outcome claims such as “tests passed” need machine-checkable evidence. Re-running a
named test command or probing a URL requires explicit `--run` and the configured
allowlist. See [security and execution boundaries](https://github.com/Avinash-Amudala/weftgate/blob/main/SECURITY.md).

## Memory that notices changed code

Weftgate's notebook checks explicit file, environment, route, import and symbol
claims before saving them. A proven false claim is refused with available suggestions.
Uncertain claims stay available for review. Recall checks original source hashes,
and notes with changed or missing evidence stay hidden by default. Source anchors
support a claim about freshness; the note's prose remains unverified.

```bash
weftgate remember "Database access" "Use the declared connection." --env DATABASE_URL
weftgate recall "database"
weftgate recall "database" --include-stale
weftgate memory stats
```

`handoff` saves a summary and its scoped checkpoint in the same notebook. Another
agent can resume through `brief`; remembered test evidence is labeled historical
and changes to the current tree are detected. Obvious secret patterns are scrubbed
from note text, but do not treat this as permission to store credentials.

Already have Mnemo data? Preview and import selected memories without installing
Mnemo or modifying its database:

```bash
weftgate memory import /path/to/mnemo.sqlite --limit 10
weftgate memory import /path/to/mnemo.sqlite --limit 10 --apply
```

The legacy repository remains compatible for existing transcript and team-hub
users. Automatic capture, external embeddings and team federation are outside the
public local workflow. They are not silently enabled by migration.
[Memory and trust](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/MEMORY.md) ·
[Migration and backup](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/MNEMO-MIGRATION.md) ·
[Architecture and scope](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/DESIGN.md).

## Contribute

```bash
bash scripts/bootstrap.sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy weftgate
.venv/bin/python -m weftgate.selftest
.venv/bin/python -m pytest -q --cov=weftgate --cov-fail-under=85
```

Start with [CONTRIBUTING.md](https://github.com/Avinash-Amudala/weftgate/blob/main/CONTRIBUTING.md), the [oracle guide](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/ORACLES.md), and
[AGENTS.md](https://github.com/Avinash-Amudala/weftgate/blob/main/AGENTS.md). New oracles need a real broken example, a correct example,
and a dynamic case that reviews. Reproducible false blocks and missing-contract
reports are especially useful.

Apache-2.0 · [Changelog](https://github.com/Avinash-Amudala/weftgate/blob/main/CHANGELOG.md) · [Launch plan](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/LAUNCH.md)
