# Verified memory: the recall consumer

This is the third consumer of the graph from `docs/ADDENDUM-context-and-memory.md`
section A5, built as an integration with [mnemo](https://github.com/Avinash-Amudala/mnemo)
rather than a memory engine of its own. weftgate owns the graph and the truth about it;
mnemo owns the memories and their ranking. The seam between them is three small,
stable calls plus a plugin entry point.

## The mechanism

1. **Anchors.** When a memory is stored, mnemo asks weftgate to ground it:
   `weftgate memory anchor '{"text": "...", "claims": {"env": [...], "routes": [...],
   "files": [...], "imports": [...], "symbols": [...]}}'`. Each anchor carries a node
   id, a content hash of the exact artifact (a file, a symbol's definition span, an env
   declaration), the commit it was grounded on, and a state. Declared claims always
   anchor, even when invalid, so a false memory is visible as such; prose is only a
   guess, so a name read from prose anchors only if it resolves now.
2. **The changed-node ledger.** Every `Session.sync()` snapshots the node sets a sync
   can change (files, env declarations, resolved routes, provided packages, and the
   symbols of the files about to be re-scanned), diffs them after the oracles sync, and
   appends the difference to a `changes` table with a monotonically increasing `seq`.
   `weftgate memory changes --since N` returns what changed after `N`. Its `seq`
   cursor covers only the returned page; continue while `has_more` is true.
3. **Self-invalidation.** mnemo remembers the last `seq` it consumed. Before a recall
   (throttled) and on `store.py invalidate`, it asks for the changes since then and
   marks memories anchored on any of those nodes `stale`. Cost is proportional to the
   number of changes, not the number of memories.
4. **Re-verification.** `store.py reverify` sends stale anchors back through
   `weftgate memory check`. The memory returns to `valid` only when its original evidence matches.
   Changed content stays `stale`; if a node is gone it becomes `invalid`. Re-checks
   retain the original hashes and do not prove that remembered prose is still true. Stale and invalid
   memories are down-ranked and flagged in recall, never silently served.
5. **The gate at write time.** `weftgate.memory.register(api)` is a mnemo verification
   plugin. With `"oracles": ["weftgate.memory"]` in `.mnemo.json`, a memory that claims
   "the API reads `DATABSE_URL`" is refused before it is stored, with
   `did_you_mean: DATABASE_URL`. A claim read from prose can flag but never rejects,
   which both sides enforce.

## Node ids

```
file:<repo-relative path>
env:<NAME>
route:<METHOD> <full path>
dist:<python|node>:<distribution>
symbol:<file>:<name>
```

They are plain strings so any consumer can store and compare them.

## Surfaces

| CLI | MCP tool | Purpose |
|---|---|---|
| `weftgate memory anchor <json>` | `memory_anchor` | anchors for a memory's text and claims |
| `weftgate memory check <json>` | `memory_check` | re-derive anchor states; `summary` is the memory's state |
| `weftgate memory changes --since N` | `memory_changes` | changed nodes after sequence `N` |

Both surfaces call the same functions in `weftgate/memory.py`, and a test asserts they agree.

## Try it

```bash
pip install git+https://github.com/Avinash-Amudala/weftgate.git
cd /path/to/mnemo && python3 mnemo/selftest.py     # the grounding stage runs when weftgate is importable
```

The self-test stores a memory anchored on an env var and a file, refuses a memory
with a typo'd env var, removes the declaration, watches the memory go stale then
invalid, confirms recall flags it, restores the declaration, and watches it become
valid again. Without weftgate the stage skips and says so.

## What this is not

Not a memory engine (mnemo is), not semantic search, and not a token-compression
benchmark. The number to lead with is the one the ledger already counts: broken wires
caught before they shipped.
