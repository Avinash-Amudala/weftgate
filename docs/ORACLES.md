# Writing an oracle

An oracle answers one narrow, machine-checkable question about a relationship in a
codebase: "does this route resolve to a defined handler", "is this env var declared
anywhere the project declares them", "is this import in the lockfile". weft is the
gate; oracles are the product surface. Writing one is an afternoon, and this guide
is the afternoon.

Start from a skeleton:

```bash
python scripts/new-oracle.py config_keys --kind config_key
```

That writes `weft/oracles/config_keys.py` and `tests/test_config_keys.py` with the
protocol filled in and the three required tests stubbed, and registers the oracle in
`weft/oracles/__init__.py` and `pyproject.toml`. For an out-of-tree plugin, pass
`--package yourpkg` to write the files under your own package instead; the registry
finds it through the `weft.oracles` entry point or a dotted path in `weft.toml`.

## The contract

```python
class Oracle(Protocol):
    name: str                      # unique, e.g. "config_keys"
    kinds: tuple[str, ...]         # claim kinds it handles, e.g. ("config_key",)
    version: str                   # bump when the index layout changes: forces a rebuild

    def extract(self, change: Change, ctx: Context) -> list[Claim]: ...
    def check(self, claim: Claim, ctx: Context) -> Finding: ...
    def build(self, ctx: Context) -> None: ...                  # optional
    def sync(self, ctx: Context, since: str | None) -> None: ...  # optional
    def suggest(self, claim: Claim, ctx: Context) -> list[str]: ...  # optional
```

Subclass `weft.oracle.BaseOracle` and override what you need. It gives you
`accept`, `review`, `reject`, and `unverifiable` helpers that keep the verdict
semantics in one place (a `reject` on a soft claim is capped to `review`
automatically).

## The one rule

**Block only on a positive, machine-checkable falsehood.** Everything else is
`REVIEW` or `UNVERIFIABLE`:

| Situation | Verdict |
|---|---|
| The index is not built, or an optional extra is missing | `UNVERIFIABLE` |
| The reference is computed at runtime, or comes through a star import | `REVIEW` (soft claim) |
| The declaration source is absent from the repo altogether | `REVIEW` |
| Resolution would need something outside the repo | `REVIEW` |
| The reference is provably absent from the project's own artifacts | `REJECT`, with suggestions |

A false block gets the tool uninstalled the same day. When in doubt, review.

## The spine, step by step

1. **Index.** In `build`, walk `ctx.files(suffixes)` and write rows into your own
   namespaced tables through `ctx.store.namespace(self.name)`. Use `rebuild` (temp
   table, then swap) for a full build and `replace_file` for one file so a failure
   never leaves a half-written index. Both are atomic.
2. **Sync.** In `sync`, take `ctx.store.sync_files(since)` (the files changed since
   the recorded commit plus the working-tree diff) and re-scan just those. If your
   table does not exist yet, call `build`.
3. **Extract.** In `extract`, read `change.added_regions()`. A region has
   `lines()` of `(lineno, text)` and, when the whole new file content is known,
   `full_text` so you can parse properly. Return one `Claim` per reference; mark a
   reference you can see but cannot name as `hard=False`.
4. **Check.** In `check`, return `UNVERIFIABLE` if your table is absent, `REVIEW`
   for soft claims, `ACCEPT` when the reference resolves, and `REJECT` with
   `did_you_mean` suggestions only for a proven absence.
5. **Suggest.** `weft.suggest.did_you_mean(name, candidates)` is bounded Levenshtein
   plus token overlap, deterministic and budget-capped.

`weft/oracles/env_vars.py` is the fully worked reference. `tests/plugins/dummy_oracle.py`
is the smallest possible oracle.

## The three tests

Every oracle ships with, at minimum:

- a **true positive**: a real broken edge it rejects, with a suggestion;
- a **true negative**: correct code it accepts;
- a **soft case**: a dynamic reference it reviews rather than rejects.

Use `tests/test_env_vars.py` as the template. Add a test for the `UNVERIFIABLE`
path (no index) too: it is the path that protects users when something is missing.

## Determinism

Same repo state, same input, same findings, in the same order. Sort everything you
iterate, never depend on dict order from the filesystem, and keep timings and
temp paths out of reasons (put volatile observations in `claim.attrs`).

## Registering

In-tree oracles are listed in `weft/oracles/__init__.py` (`BUILTIN`) and under
`[project.entry-points."weft.oracles"]` in `pyproject.toml`. A separately
distributed oracle exposes `register(api)`:

```python
def register(api: OracleAPI) -> None:
    api.register_oracle(ConfigKeysOracle())
```

and declares the entry point in its own `pyproject.toml`, or the user lists its
dotted path in `weft.toml`:

```toml
[weft]
oracles = ["env_vars", "imports_lockfile", "routes_fastapi", "yourpkg.config_keys"]
```

## Measuring it

Run the mutation harness on a repo that exercises your oracle and check that every
injected breakage is detected, blocked, and suggested:

```bash
weft eval mutate --seed 13
```

Then audit a few real repos. Anything the oracle rejects that is not actually
broken is a bug in the oracle, and the one kind we will not merge.
