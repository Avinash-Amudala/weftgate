# weft: design

*A verification gate for coding agents that checks the wiring, not the spelling.*

Working name: **weft** (in weaving, the weft is the thread that crosses and binds the warp; here it is the thread that binds the parts of a codebase together). The name is provisional. Check availability on PyPI, npm, and GitHub before committing, and if it is taken, rename with a single find-and-replace since nothing in the design depends on it.

License: Apache-2.0.

---

## 1. The problem

A coding agent writes code that reads perfectly and does not work, because the parts do not connect. The function it calls exists, but the route it wired to that function is never registered. The variable it reads is spelled correctly, but nothing declares it. The model field it added never made it into a migration. The endpoint it called does not match the shape the API actually returns.

These are relational failures. They live in the edges between files, not inside any one file. A language server and an abstract syntax tree both say the code is fine, because every symbol they can see does exist. What is missing is the connection, and a connection is only visible if you reconstruct it.

Concrete failures that ship today, across common stacks:

- A route or URL pattern points at a handler that is not defined, or a handler is defined and never registered on any route.
- An environment variable is read in code but declared nowhere (no `.env.example`, no settings schema, no config default).
- A request or response is built in a shape that does not match the declared OpenAPI or schema contract for that endpoint.
- A model gains a field that no migration adds, or a migration references a column no model has.
- A feature flag is checked in code but defined in no registry.
- A dependency is injected but no provider or binding supplies it.
- A config key is read but does not exist in the actual config file.
- A background task is dispatched by a name that no task registers, or a task is registered and never dispatched.
- An import names a package that is not in the lockfile and is not part of the standard library. This is the slopsquatting case, and it is a supply-chain risk, not just a bug.

Every one of these is machine-checkable if the relationships are reconstructed as a graph and the reference is resolved against it. None of them is caught by asking whether a symbol exists.

## 2. Why this is different from what already exists

As of late 2026 there is a crowd of tools that verify symbol existence for agent output. They check whether a function, method, package, or path exists, usually with an abstract syntax tree or a language server, and flag the ones that do not. That problem is real and largely solved by several projects. Building another one adds nothing.

There is also a set of drift tools that watch an external API's schema for breaking changes over time. That is a different problem: it is about a remote contract evolving, not about whether the code an agent just wrote connects to the project's own artifacts.

weft occupies the gap between them. It verifies that the code an agent produced connects correctly to the project's own relationships and contracts. Symbol existence is the floor, delegated to a language server where one is available so weft is never worse than the symbol-checkers. The value is the edges above that floor, which nobody is checking as a product.

The second difference is measurement. weft ships an evaluation harness and an audit mode from day one, because a correctness gate that cannot show it is correct does not earn trust. See section 11.

## 3. Core concepts

Four concepts carry the whole system.

**Oracle.** A component that answers one narrow, exact, machine-checkable question about a relationship, built from the project's own artifacts. The env-var oracle answers "is this used variable declared anywhere the project declares variables." The route oracle answers "does this route resolve to a defined, registered handler." Oracles are plugins. The set of oracles is the product's surface, and the community extends it. This is the platform and the moat.

**Claim.** A single relational assertion to be checked, with a location. Claims come from two places. In diff mode, weft extracts them by parsing a code change: the change reads `DATABASE_URL`, so there is a claim that `DATABASE_URL` is declared. In claim mode, an agent states them directly: "I added route POST /users handled by users.create, and tests pass." Diff mode is deterministic and needs no model. Claim mode adds the honesty gate of section 9.

**Verdict.** The result of checking one claim, at one of four levels. `ACCEPT` means it resolved, or there was nothing checkable. `REVIEW` means a soft miss, something that could not be fully resolved and is worth a human glance but is not a proven error. `REJECT` means a hard claim is provably false. `UNVERIFIABLE` means the oracle could not run at all, for example its index has not been built. The gate's overall verdict is the worst level among its findings, with `UNVERIFIABLE` never contributing to a block.

**Soft-fail.** The single most important behavioral rule. weft blocks only on a positive, machine-checkable falsehood. Everything else degrades to review, to a suggestion, or to silence. A missing index never rejects. A dynamic or computed reference that cannot be resolved softens to review. A prose-derived claim in claim mode softens from reject to review. A gate that false-blocks gets uninstalled within a day, so the bias is deliberate and strong: when in doubt, do not block.

## 4. Architecture

The data flow has two entry modes feeding one gate.

```
                 diff mode                         claim mode
        (file / patch / git diff)          (agent states structured claims)
                    |                                   |
              change parser                        claim intake
                    |                                   |
                    +----------------+------------------+
                                     |
                              enabled oracles
                       (extract claims in diff mode;
                        check claims in both modes)
                                     |
                            per-oracle index
                       (SQLite, per-repo, incremental)
                                     |
                                   gate
                    (collect findings, compute verdict,
                     attach did-you-mean suggestions)
                                     |
                    +----------------+------------------+
                    |                                   |
              MCP server                          plain CLI
        (stdio, for agents)              (identical output, for hooks/CI)
```

Components:

- **Change parser** (`change.py`) turns a file, a patch, or a git diff into a `Change`: the set of touched files and the added or modified regions. It does not need a full grammar. It gives oracles the raw material to extract claims from.
- **Oracle registry** (`registry.py`) discovers oracles from installed entry points and from the dotted paths listed in config, and holds the enabled set.
- **Oracles** (`oracles/`) each build an index from the repo, extract claims from a change, and check claims against their index.
- **Index store** (`store.py`) is one SQLite database per repo under a user cache directory, namespaced per oracle, built once and synced incrementally on the git commit plus the working-tree diff. No embeddings in the core; relational grounding is a graph and lookup problem, not a semantic-search problem, and keeping it lexical and structural is what makes it fast, dependency-light, and trustworthy.
- **Gate** (`gate.py`) runs oracles over a change or a claim set, collects findings, computes the overall verdict, and attaches suggestions.
- **Suggest** (`suggest.py`) produces did-you-mean candidates with bounded-Levenshtein plus token scoring, budget-capped, so a reject is actionable.
- **Honesty** (`honesty.py`) handles claim-mode assertions about outcomes (tests pass, bug fixed, endpoint returns a status) and grades them by evidence.
- **Surfaces**: `mcp_server.py` exposes the gate over stdio MCP; `cli.py` is a byte-for-byte-equivalent command-line shim so an MCP-blocked environment loses nothing and the two can never drift.

## 5. The oracle plugin interface

This is the part to get exactly right, because it is what the community builds on. An oracle is any object satisfying this protocol.

```python
class Oracle(Protocol):
    name: str                      # unique, e.g. "env_vars"
    kinds: tuple[str, ...]         # claim kinds it handles, e.g. ("env_var",)

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        """Pull candidate relational references out of a code change.
        Diff mode only. Return [] if this oracle finds nothing to check."""

    def check(self, claim: Claim, ctx: Context) -> Finding:
        """Resolve one claim against this oracle's index.
        MUST return UNVERIFIABLE (never REJECT) if the index is absent."""

    # Optional:
    def build(self, ctx: Context) -> None: ...          # build/refresh the index
    def sync(self, ctx: Context, since: str | None) -> None: ...  # incremental
    def suggest(self, claim: Claim, ctx: Context) -> list[str]: ...
```

An oracle package exposes a `register(api)` entry point:

```python
def register(api: OracleAPI) -> None:
    api.register_oracle(EnvVarOracle())
```

Config enables oracles by name or dotted path:

```toml
# weft.toml
[weft]
oracles = ["env_vars", "imports_lockfile", "routes_fastapi", "yourpkg.your_oracle"]
```

The invariant every oracle must honor is the soft-fail rule. An oracle that cannot resolve a reference for any reason other than a proven absence must return `REVIEW` or `UNVERIFIABLE`, not `REJECT`. Reviewers of new oracles enforce this. It is the difference between a tool people keep and a tool people rip out.

## 6. Indexing substrate

One SQLite file per repo, at `~/.cache/weft/<repo-hash>.sqlite`, outside the repo. A `meta` table records the schema version, the repo root, the git commit the index was built at, and per-oracle build metadata. Each oracle owns its own tables, prefixed with its name.

Build once, sync incrementally. A full build parses the whole repo. `sync` reindexes only the files that changed since the recorded commit, plus the working-tree diff, so a no-op sync is well under a second and a single changed file is about a second. Sync runs before every check so the gate is never stale. A structural rebuild must never discard expensive index state that is still valid; preserve and restore per-oracle tables across rebuilds the way a careful cache does.

Parsing is tiered so the tool installs and runs with nothing heavy, and gets sharper when optional extras are present.

- **Tier 0, always, standard library only.** The relational oracles that are structured file reads: env vars, config keys, imports against the lockfile, framework routes read from the framework's own registration files. These are the differentiators, and they are cheap and dependency-free. This ordering is deliberate: the commodity work (symbol existence) is the part that needs heavy tooling, and the distinctive work (edges) is the part that does not.
- **Tier 1, optional extras.** Tree-sitter for cross-language structural extraction, and a language-server client for authoritative symbol resolution. Installed via `pip install weft[treesitter]` or `weft[lsp]`. When absent, oracles that depend on them return `UNVERIFIABLE`, never a false reject.

## 7. Verdict semantics

| Level | Meaning | Blocks in hook or CI | Example |
|---|---|---|---|
| `ACCEPT` | Resolved, or nothing checkable | no | route resolves to a registered handler |
| `REVIEW` | Soft miss, cannot fully resolve | no | handler name is computed at runtime |
| `REJECT` | Hard claim provably false | yes | env var read, declared nowhere |
| `UNVERIFIABLE` | Oracle could not run | no | index not built, extra not installed |

The overall gate verdict is the worst blocking-eligible level among findings: `REJECT` if any, else `REVIEW` if any, else `ACCEPT`. `UNVERIFIABLE` findings are reported but never raise the overall verdict. Every `REJECT` carries did-you-mean suggestions when the oracle can produce them, so the output is a fix and not just a complaint.

## 8. Reference oracles for v1

Ship a small set that proves the pattern across more than one stack and includes both a differentiator and the table-stakes import guard. Each is a worked example the community copies.

1. **env_vars** (Tier 0, any stack). Extracts environment reads (`os.environ[...]`, `os.getenv(...)`, `process.env.X`, `ENV["X"]`) and checks each against the union of declared sources: `.env.example`, `.env.sample`, a settings or config schema, and defaults in code. A used var declared nowhere is a `REJECT` with the closest declared name suggested.
2. **imports_lockfile** (Tier 0, Python and Node to start). Checks that every third-party top-level import resolves to a package in the lockfile (`poetry.lock`, `uv.lock`, `requirements.txt`, `package-lock.json`, `pnpm-lock.yaml`) or the standard library. A phantom package is a `REJECT`. This is the slopsquatting guard, present so users need no second tool, but it is not the headline.
3. **routes_fastapi** (Tier 0, FastAPI as the first framework). Builds the route table from the app's own decorators and routers, and checks that each route's endpoint resolves to a defined function, and, in claim mode, that a stated route exists. A route to a missing endpoint is a `REJECT`. This is the first true edge oracle and the template for Django, Flask, Express, Rails, and Next.js oracles that follow.

The v1 goal is not breadth. It is three oracles that are correct, measured, and copyable, so oracle four is written by someone else.

## 9. The honesty gate (claim mode)

When an agent asserts an outcome rather than a reference, weft grades it by evidence and refuses to rubber-stamp. Outcome claims: tests pass, a bug is fixed, an endpoint returns a given status. Verdicts:

| Verdict | Condition |
|---|---|
| `PROVEN` | Machine-checkable evidence was observed and matches the claim exactly |
| `PLAUSIBLE` | Weaker evidence is consistent with the claim but does not pin it |
| `NOT_OBSERVED` | No evidence was supplied or found |
| `CONTRADICTED` | Evidence shows the claim is false |

The rule that makes this more than a slogan: never `PROVEN` without a matching machine-checkable signal. For "tests pass," that is an exit code of zero from a named command weft can re-run, or a parsed test report. For "endpoint returns 200," that is an actual probe. A claim with no evidence is `NOT_OBSERVED`, and the agent is told what evidence would settle it. This mirrors the discipline that a reproduction is only real when the specific signature was observed, generalized to any outcome claim.

## 10. Cross-agent surfaces

One gate, four ways to reach it, so weft works everywhere an agent runs.

- **MCP server** over stdio, tools: `check_change` (verify a file, patch, or diff), `check_claim` (verify structured claims, including honesty), `audit` (sweep the repo, section 11), `suggest` (did-you-mean for one reference), `index_status`. Works with Claude Code, Codex, Cursor, Antigravity, Windsurf, and any MCP client.
- **Plain CLI** with identical output, so an MCP-blocked org loses nothing and the two surfaces cannot drift: `weft check <path|->`, `weft claim <json>`, `weft audit`, `weft index`, `weft eval`.
- **Hooks.** A Claude Code PreToolUse hook that vets every Edit and Write before it lands. A git pre-commit hook. Both call the CLI and block only on `REJECT`.
- **CI action.** A GitHub Action that runs `weft check` on the pull request diff and `weft audit` on a schedule.

A setup command detects the stack, enables the right oracles, builds the index, and writes the agent and hook configuration, so adoption is one command.

## 11. Measurement, and the audit growth loop

Trust is the product. Two harnesses, both shipped.

- **Mutation harness** (`eval/mutate.py`). Inject known-bad edges into a real repo: rename a handler so a route dangles, delete an env declaration, point an import at a phantom package, and confirm the gate detects and blocks each. Deterministic by seed. Count a detection with no usable suggestion as a miss, so there is no survivorship bias. Report detected and blocked separately, per oracle. This answers "does the gate catch what it claims to."
- **Audit mode** (`eval/audit.py`, and the `audit` surface). Run the gate over the existing, already-merged codebase and surface the latent broken edges that are already there. This is both a correctness check and the adoption loop: a developer runs `weft audit` on their own repo, sees a real count of broken wires they did not know about, and that surprise is the reason they install it and tell someone. The field-audit result is the most credible number the project can have, because the user generates it on their own code.

Honesty rule for all reported numbers: any figure tuned on the same repo it was measured on is labeled an upper bound, not a field number. The audit result on the user's own untouched code is the number that carries weight.

## 12. Configuration

Precedence: `WEFT_*` environment variables, then repo `weft.toml` or `.weft.json`, then a user config, then defaults. Stack is auto-detected but can be pinned. Minimal example:

```toml
[weft]
oracles = ["env_vars", "imports_lockfile", "routes_fastapi"]
block_on = "reject"          # reject | review | never
env_declared_in = [".env.example", "settings.py"]

[weft.routes_fastapi]
app = "app.main:app"
```

## 13. Non-goals

Naming them protects the focus.

- Not a semantic code search or retrieval tool. That category is well served; integrate with it, do not rebuild it.
- Not an agent memory. A separate concern with its own mature tools.
- Not a symbol-existence checker as its headline. Symbol existence is the delegated floor; the edges are the product.
- No autofix in v1. Suggest, do not apply. Applying edits is a v2 decision with its own risk surface.
- Not an IDE, an agent framework, or a linter replacement.

## 14. Roadmap

- **v0.1.** Core gate, verdict types, registry, SQLite store with incremental sync, the three reference oracles, the CLI, the MCP server, the mutation harness, the audit mode, the self-test, and the one-command setup. Diff mode complete. Claim mode with the env and route oracles and the honesty gate for "tests pass."
- **v0.2.** More framework route oracles (Django, Flask, Express, Next.js), the config-key oracle, the feature-flag oracle, the tree-sitter and LSP tiers, the GitHub Action.
- **v0.3.** The migration-vs-model oracle, the OpenAPI-contract oracle, the DI-binding oracle, and a published oracle-authoring guide with a cookiecutter template so writing oracle N is an afternoon.
- **Later.** Optional performance path (tree-sitter or a native accelerator for large repos), an oracle registry index so users can discover community oracles, and optional integration points for memory and search tools rather than reimplementations.

## 15. What makes this a top repo, honestly

Three things have to be true, and the design aims all three at once. It has to do one sharp thing that nobody else does, which is relational and contract grounding rather than symbol existence. It has to prove it works, which is the mutation harness and the audit loop. And it has to be trivial to adopt and extend, which is the one-command setup, the four surfaces, and the oracle plugin interface. The extensibility is where the original "one repo for everything" instinct belongs: not many tools in one repo, but one gate that the community teaches about every stack, one oracle at a time.
