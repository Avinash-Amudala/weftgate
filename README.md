# weftgate

**Catch broken connections in agent-written code before it ships.**

[![CI](https://github.com/Avinash-Amudala/weftgate/actions/workflows/ci.yml/badge.svg)](https://github.com/Avinash-Amudala/weftgate/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/weftgate)](https://pypi.org/project/weftgate/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/Avinash-Amudala/weftgate/blob/main/pyproject.toml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/Avinash-Amudala/weftgate/blob/main/LICENSE)

A mistyped environment variable. An import missing from the lockfile. A FastAPI route
pointing at a handler that does not exist. Weftgate checks these connections against
your repository through one local CLI, MCP server, hook, or GitHub Action.

**No API key. No runtime dependencies. No network calls on the default verification path.**

[![Watch the 58-second motion demo](https://raw.githubusercontent.com/Avinash-Amudala/weftgate/main/docs/assets/demo.gif)](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.1.1/weftgate-demo-motion.mp4)

[Watch the full demo](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.1.1/weftgate-demo-motion.mp4) ·
[Transcript and reproducible evidence](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/DEMO.md) · [How to write an oracle](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/ORACLES.md)

## Try it

```bash
pip install weftgate
cd /path/to/your/repo
weftgate doctor                  # see which contracts can be checked
weftgate audit                   # inspect the current repository
weftgate check app/main.py        # check a file or directory
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

## Supported contracts in v0.1

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
weftgate setup --agents claude,cursor,vscode
weftgate setup --hooks             # review the generated local configuration
```

The standard-library MCP server requires no extra package. Example MCP configuration:

```json
{"mcpServers": {"weftgate": {"command": "weftgate", "args": ["mcp"]}}}
```

Run the server with the repository as its working directory. `weftgate setup --agents all`
writes supported project configs and prints snippets for clients with global settings.
CLI and MCP use the same gate functions. Tools include `check_change`, `check_claim`,
`audit`, `suggest`, `index_status`, and `index`.

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
      - uses: Avinash-Amudala/weftgate@v0.1.0
        with:
          mode: check             # or audit to inspect the repository
```

The Action supports `base`, `paths` (shell-quoted paths, no shell expansion),
`block-on`, and `python-version`. Use a full checkout for diff ancestry.
The [pre-commit hooks](https://github.com/Avinash-Amudala/weftgate/blob/main/.pre-commit-hooks.yaml) use the same gate; pin `rev: v0.1.0`.

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

## Optional memory integration

Weftgate exposes `memory anchor`, `memory check`, and `memory changes` through the CLI
and MCP. With mnemo installed in the same interpreter, add
`"oracles": ["weftgate.memory"]` to `.mnemo.json` to check structured memory claims.

Changed evidence keeps memories **stale**; checking does not silently replace the
original hashes or prove remembered prose. See [the integration contract](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/MEMORY.md).
Mnemo is a separate companion repository and is not required to use Weftgate.

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
