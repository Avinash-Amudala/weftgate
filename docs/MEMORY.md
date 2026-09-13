# Source-aware memory

Weftgate includes a compact public adaptation of mnemo's lexical memory design.
Install `weftgate` once; no companion repository is required for these commands:

```bash
weftgate remember "Order idempotency" "Keep duplicate requests idempotent." --file app/orders.py
weftgate recall "orders"
weftgate recall "orders" --include-stale
weftgate remember "Order idempotency" "Reviewed revised behavior." --file app/orders.py --id NOTE_ID
weftgate forget NOTE_ID
```

Notes live in `recall_notes` in the existing per-repository SQLite cache, normally
under `~/.cache/weftgate`. `WEFTGATE_CACHE` overrides that location. They are local,
not committed or sent to a service by Weftgate. Your MCP client receives retrieved
notes and may transmit them according to its own policy. `weftgate index --status`
shows the exact store path. No transcript capture, model download or federation
is enabled by these commands.

Titles/body are bounded to 120/4,000 characters with up to 20 explicit file citations.
Paths must stay inside the repo and cannot traverse symlinks. Recall uses deterministic
camel-aware lexical matching and rechecks candidate file hashes before returning them.

| State | Meaning | Returned by default |
| --- | --- | --- |
| anchored | All cited files match their original hashes. Prose remains unverified. | Yes |
| unverified | No files were cited. Useful for preferences, not proof. | Yes |
| stale | A source changed or cannot be verified. | No |
| invalid | A cited source disappeared. | No |

Re-reading stale notes never updates their original evidence. Only explicitly
replacing a note by ID re-anchors reviewed text. `forget` logically deletes one note;
it is not a forensic erasure guarantee for backups or SQLite storage. Avoid saving
credentials. Notes are untrusted data and must not override user or system instructions.
Token accounting follows [CONTEXT.md](CONTEXT.md).

## Legacy mnemo plugin seam

Existing mnemo users can keep `"oracles": ["weftgate.memory"]` in `.mnemo.json`.
The original lower-level anchors API remains supported. The public notebook does
not automatically ingest or expose an existing private mnemo database. The rest
of this page documents that lower-level integration.

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
