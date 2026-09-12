# weft

**A verification gate for coding agents that checks the wiring, not the spelling.**

Your agent writes code that reads perfectly and does not run, because the parts do not connect. The route points at a handler that was never registered. The variable is read but declared nowhere. The migration does not match the model. The import names a package that is not in your lockfile. A language server says all of it is fine, because every symbol it can see exists. What is broken is the connection between them.

weft reconstructs those connections and checks them, before the code ships.

```
$ weft audit
Scanned 214 files. 6 broken wires found:

  REJECT  api/routes.py:41   route POST /orders -> orders.create   (no such handler; did you mean orders.create_order?)
  REJECT  config.py:12       env var STRIPE_SECRET read, declared nowhere   (add to .env.example)
  REJECT  workers/tasks.py:8 import "celeryy"   (not in poetry.lock; slopsquat risk; did you mean celery?)
  REVIEW  api/urls.py:73     handler name computed at runtime; cannot resolve
  ...
```

Run it on your own repo. The count is usually not zero.

## Why weft is different

There are good tools that check whether a symbol exists. weft is not another one. It checks the edges above symbol existence: route to handler, handler to schema, env var to declaration, migration to model, feature flag to registry, import to lockfile. Symbol existence is the floor, delegated to your language server where available. The edges are the product.

It blocks only on a proven falsehood. A missing index, a dynamic reference, an unresolved indirection all soften to review, never a false block. It is local-first, standard-library-only at the core, and it ships with a measurement harness so it can prove it works.

## Install

```bash
pip install weft
weft setup          # detects your stack, writes weft.toml, builds the index
weft setup --hooks  # also wires git pre-commit, the Claude Code PreToolUse hook, and .mcp.json
```

From a checkout, `bash scripts/bootstrap.sh` creates a venv, installs every extra, and runs the
offline self-test.

## Use it from your agent

weft is an MCP server and an identical CLI, so it works the same everywhere.

Claude Code, Cursor, Codex, Antigravity, Windsurf, any MCP client:

```json
{
  "mcpServers": {
    "weft": { "command": "weft", "args": ["mcp"] }
  }
}
```

As a git pre-commit hook or a Claude Code PreToolUse hook (blocks only on a `reject`):

```bash
bash scripts/install-hooks.sh /path/to/your/project
```

The same gate from the command line:

```bash
weft check app/main.py            # a file (or a directory)
git diff | weft check -           # a unified diff on stdin
weft check --staged               # what is about to be committed
weft claim '[{"kind":"route","method":"POST","path":"/users","handler":"users.create"}]'
weft audit                        # sweep the whole repo for latent broken wires
weft eval mutate --seed 13        # the mutation harness, reproducible
```

Exit code 1 means a blocking verdict; `--format=json` prints exactly what the MCP tools return.

## What it checks (v1)

- **env vars**: every variable your code reads is declared somewhere your project declares them.
- **imports**: every third-party import resolves to your lockfile or the standard library (slopsquatting guard).
- **routes** (FastAPI first): every route resolves to a defined, registered handler.

More stacks and edge oracles are added one plugin at a time. weft is an oracle platform; writing a check for your framework is the intended way to extend it. See `docs/DESIGN.md`.

## Status

v0.1: the verification gate is implemented and green (three oracles, diff and claim mode, the
honesty gate, CLI and MCP surfaces with an output-parity test, incremental SQLite index, the
mutation harness, the audit sweep, and the offline self-test). The grounded-context surface and
verified memory described in `docs/ADDENDUM-context-and-memory.md` are v0.2 and v0.3.

The core is standard-library only. Optional extras (`weft[treesitter]`, `weft[lsp]`,
`weft[yaml]`, `weft[mcp]`) are reserved for later tiers; nothing in v0.1 needs them, and the
stdio MCP server runs without the `mcp` package.

See `docs/DESIGN.md` for the full design and `AGENTS.md` for the build guide.

## License

Apache-2.0.
