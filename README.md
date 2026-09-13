# weft

**A verification gate for coding agents that checks the wiring, not the spelling.**

[![ci](https://github.com/Avinash-Amudala/weft/actions/workflows/ci.yml/badge.svg)](https://github.com/Avinash-Amudala/weft/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)](pyproject.toml)

Your agent writes code that reads perfectly and does not run, because the parts do not
connect. The route points at a handler that was never defined. The variable is read but
declared nowhere. The import names a package that is not in your lockfile. A language
server says all of it is fine, because every symbol it can see exists. What is broken is
the connection between them.

weft reconstructs those connections from the repository's own artifacts and checks them,
before the code ships. This is real output, on the small fixture repo the self-test
builds, with one wire broken per oracle:

```text
$ weft audit
Scanned 8 files. 3 broken wires found, 0 to review:

  REJECT       app/broken.py:3                  import 'requestz' is not in requirements.txt or the standard library (slopsquat risk)   (did you mean requests?)
  REJECT       app/broken.py:8                  env var 'DATABSE_URL' is read but declared nowhere (add it to .env.example)   (did you mean DATABASE_URL?)
  REJECT       app/broken.py:10                 handler 'helth' is not defined or imported in app/broken.py   (did you mean health?)

  env_vars           accept     6  review    0  reject    1  unverifiable    0
  imports_lockfile   accept    14  review    0  reject    1  unverifiable    0
  routes_fastapi     accept    10  review    0  reject    1  unverifiable    0
```

The same gate as JSON, abridged to one finding (the MCP tools return exactly this shape):

```text
$ weft check app/broken.py --format=json
{
  "verdict": "reject",
  "stats": {
    "claims": 6,
    "reject": 3,
    "review": 0,
    "unverifiable": 0,
    "blocking": true
  },
  "findings": [
    "...",
    {
      "attrs": {},
      "col": 10,
      "file": "app/broken.py",
      "hard": true,
      "kind": "env_var",
      "level": "reject",
      "line": 8,
      "oracle": "env_vars",
      "reason": "env var 'DATABSE_URL' is read but declared nowhere (add it to .env.example)",
      "source": "code",
      "subject": "DATABSE_URL",
      "suggestions": [
        "DATABASE_URL"
      ]
    }
  ]
}
```

Run it on your own repo. On six public repositories it had never seen, weft found nine
latent broken wires in one of them and zero false rejects across all six; the numbers,
the method, and the commits are in [docs/FIELD-RESULTS.md](docs/FIELD-RESULTS.md).

## Why weft is different

There are good tools that check whether a symbol exists. weft is not another one. It
checks the edges above symbol existence: route to handler, env var to declaration,
import to lockfile, router to the module that defines it. Symbol existence is the floor;
the edges are the product.

**It blocks only on a proven falsehood.** Every verdict is one of four levels:

| Level | Meaning | Blocks | Example |
|---|---|---|---|
| `accept` | resolved, or nothing checkable | no | the env var is in `.env.example` |
| `review` | a soft miss weft cannot fully resolve | no | `os.environ[key]` with a computed key; an import absent from a manifest that has no lockfile |
| `reject` | a hard claim is provably false | **yes** | `os.environ["DATABSE_URL"]` when only `DATABASE_URL` is declared |
| `unverifiable` | the oracle could not run | no | no lockfile in the repo; index not built |

A missing index, a dynamic reference, an uninstalled optional extra, a documentation
snippet, a repo with no declaration source at all: all of these soften. A gate that
false-blocks gets uninstalled the same day, so the bias is deliberate. Every reject
carries a did-you-mean suggestion, so the output is a fix, not a complaint.

It is local-first and the core is standard-library only. It ships with a measurement
harness and an audit mode so it can prove it works, and a ledger that counts the broken
wires it stopped before they shipped.

## Install

> The distribution name `weft` is taken on PyPI by an unrelated project, so
> `pip install weft` installs the wrong thing today. Until the rename
> (`scripts/rename.sh <newname>`) and the first release, install from the repository:

```bash
pip install git+https://github.com/Avinash-Amudala/weft.git
weft setup                  # detects your stack, writes weft.toml, builds the index
weft setup --hooks --agents all   # + git pre-commit, Claude Code hook, MCP config for every agent
weft doctor                 # explains what the gate can and cannot verify in this repo
```

From a checkout, `bash scripts/bootstrap.sh` creates a venv, installs every extra, and
runs the offline self-test.

## Use it from your agent

weft is an MCP server and an identical CLI, so it works the same everywhere. The MCP
server is standard-library only; no extra is needed to run it.

**Claude Code** (`.mcp.json`, written by `weft setup --agents claude`) plus a PreToolUse
hook that vets every Edit and Write before it lands (`weft setup --hooks`):

```json
{
  "mcpServers": { "weft": { "command": "weft", "args": ["mcp"] } }
}
```

**Cursor** (`.cursor/mcp.json`) and **VS Code** (`.vscode/mcp.json`, key `servers`):
`weft setup --agents cursor,vscode`. **Codex**, **Windsurf**, and **Claude Desktop**
keep MCP config globally; `weft setup --agents codex,windsurf,claude-desktop` prints the
snippet to paste.

Tools: `check_change` (a file, new content, a diff, or the staged changes),
`check_claim` (structured claims, including route existence and outcome claims graded
by evidence), `audit`, `suggest`, `index_status`, `index`.

## Use it from the command line, hooks, and CI

```bash
weft check app/main.py other.py       # files or directories
git diff | weft check -               # a unified diff on stdin
weft check --staged                   # what is about to be committed
weft check --path app/x.py --content new.py   # content that is not on disk yet
weft claim '[{"kind":"route","method":"POST","path":"/users","handler":"users.create"}]'
weft audit                            # sweep the whole repo for latent broken wires
weft eval mutate --seed 13            # the mutation harness, reproducible
weft index --show routes              # the resolved route table (or env, imports)
weft ledger                           # blocked changes caught before they shipped
```

Exit code 1 means a blocking verdict, 2 a usage or config error. `--format=json` prints
exactly what the MCP tools return; `--format=github` prints workflow annotations.

**GitHub Action**, on the pull request diff:

```yaml
- uses: Avinash-Amudala/weft@main
  with:
    mode: check          # or: audit
```

**pre-commit**:

```yaml
repos:
  - repo: https://github.com/Avinash-Amudala/weft
    rev: main
    hooks:
      - id: weft-check
```

Both block only on a `reject`.

## What it checks (v0.1)

- **env_vars**: every variable your code reads (`os.environ`, `os.getenv`, `process.env`,
  `import.meta.env`, `ENV[...]`, `os.Getenv`, `env::var`, `System.getenv`, ...) is
  declared somewhere your project declares them: `.env.example`-style files, pydantic
  settings classes, Dockerfile `ENV`, compose `environment:`, code defaults, or files you
  list under `env_declared_in`. Reads with an inline default and well-known ambient
  variables (`PATH`, `CI`, `NODE_ENV`, `GITHUB_*`) never reject.
- **imports_lockfile**: every third-party import resolves to a lockfile
  (`uv.lock`, `poetry.lock`, `Pipfile.lock`, pinned `requirements.txt`,
  `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`) or manifest, the standard library,
  or the repo's own packages. Knows that `PyYAML` provides `yaml`, reads tsconfig
  `paths`, framework aliases, monorepo and nested project roots. The slopsquatting guard.
- **routes_fastapi**: every route resolves to a defined handler and every
  `include_router` to a router that exists, following imports across the repo's own
  modules; in claim mode, a stated route exists in the resolved table. Built statically
  with `ast`; FastAPI is not imported.

More stacks are added one oracle at a time. Writing one is an afternoon:
[docs/ORACLES.md](docs/ORACLES.md) and `python scripts/new-oracle.py <name> --kind <kind>`.

## Verified memory (with mnemo)

The same graph the gate builds grounds an agent's memory. With
[mnemo](https://github.com/Avinash-Amudala/mnemo) installed, every memory is anchored on
graph nodes (files, env vars, routes, packages, symbols) with content hashes; when a
sync sees those nodes change, the memory goes stale, is re-verified through the
oracles, and is flagged or down-ranked at recall instead of being served as fact.
weft's oracles also gate `remember`, so a memory with a typo'd env var is refused with
a suggestion. `weft memory anchor|check|changes` and the matching MCP tools are the
whole interface; [docs/MEMORY.md](docs/MEMORY.md) has the mechanism.

## Configuration

```toml
# weft.toml
[weft]
oracles = ["env_vars", "imports_lockfile", "routes_fastapi"]   # names, or dotted paths to plugins
block_on = "reject"                  # reject | review | never
env_declared_in = [".env.example", "config/settings.py"]   # extra declaration sources
exclude = ["fixtures"]               # extra directories to skip

[weft.env_vars]
ambient = ["MY_PLATFORM_VAR"]        # never reject these

[weft.honesty]
allow_commands = ["make verify"]     # test commands claim mode may re-run with --run
allow_hosts = ["api.local"]          # hosts claim mode may probe with --run
```

Precedence: `WEFT_*` environment variables, then the repo's `weft.toml` or `.weft.json`,
then `~/.config/weft/weft.toml`, then defaults. The index lives under `~/.cache/weft/`
(`WEFT_CACHE` overrides).

## Status

v0.1: the verification gate, complete and measured. Three oracles, diff and claim mode,
the honesty gate, CLI and MCP surfaces with an output-parity test, incremental SQLite
index, mutation harness, audit sweep, self-test, field results on six repositories, a
GitHub Action, pre-commit hooks, and agent setup for Claude Code, Cursor, VS Code, Codex,
Windsurf, and Claude Desktop. See [CHANGELOG.md](CHANGELOG.md).

Before the first release: the rename (`scripts/rename.sh`), then `git tag v0.1.0`
triggers the release workflow (PyPI trusted publishing plus a GitHub release).

Verified memory (addendum v0.3) ships as the mnemo integration above. Next: Django, Flask,
Express, and Next.js route oracles, then the grounded-context surface (`resolve`,
`neighbors`, `card`) described in [docs/ADDENDUM-context-and-memory.md](docs/ADDENDUM-context-and-memory.md).
See [docs/DESIGN.md](docs/DESIGN.md) for the design and [AGENTS.md](AGENTS.md) for the
build contract.

## License

Apache-2.0.
