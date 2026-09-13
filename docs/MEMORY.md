# One local memory engine

Install `weftgate` once. The notebook, code context, verification gate and handoffs
share the same per-repository SQLite store and MCP process. Mnemo's local lexical
memory, grounding and redaction designs have been adapted into this public package.
No companion package is required.

```bash
weftgate brief "order retries" --reference app/orders.py
weftgate remember "Order idempotency" "Keep duplicate requests idempotent." --file app/orders.py
weftgate remember "Database access" "Use the declared connection." --env DATABASE_URL
weftgate remember "Order endpoint" "Review this endpoint." --route "POST /api/orders"
weftgate recall "orders"
weftgate memory stats
```

`remember` accepts `--file`, `--env`, `--route`, `--import` and `--symbol` repeatedly.
Symbols use `app/orders.py:create_order`. MCP accepts the same references in
`claims: {files, env, routes, imports, symbols}`. Explicit proven false claims are
refused; unavailable or ambiguous evidence is retained for review. No claim inferred
from prose becomes a hard rejection. Notes without explicit sources are unverified.

Titles and bodies are bounded to 120 and 4,000 input characters. Each claim kind
accepts up to 20 short references. File paths must stay inside the repository and
cannot traverse symlinks. Note kinds are decision, convention, task, note, gotcha,
howto, command, handoff, preference and todo. Remembered commands are text; they are never executed
by recall, brief or migration.

| State | Meaning | Returned by default |
| --- | --- | --- |
| anchored | Original source evidence matches. Prose remains unverified. | Yes |
| unverified | No source evidence was provided. | Yes |
| stale | Evidence changed, cannot be checked, or lacks an original hash. | No |
| invalid | An explicit source reference no longer resolves. | No |

File and symbol anchors hash source content. Environment anchors cover declarations,
route anchors cover registered relationships, and import anchors hash dependency
contracts and local import names. They do not certify runtime behavior or the contents
of installed packages. Changes to dependency declarations conservatively stale import
notes. Repeated reads never rewrite original hashes.

Use `recall --include-stale` to inspect old notes. After reviewing the note against
current code, explicitly replace it with `remember --id NOTE_ID` and its references.
`forget NOTE_ID` logically deletes a note and associated handoff metadata. It is not
a forensic erasure guarantee for backups, old SQLite pages or external copies.

## Storage and privacy

Notes live in `recall_notes` in the existing per-repository SQLite cache, normally
under `~/.cache/weftgate`. `WEFTGATE_CACHE` overrides that location. `weftgate index
--status` shows the store path. Keep a memory export for durable backups because
this database is stored in a cache directory. See [migration and backup](MNEMO-MIGRATION.md).

Obvious private-key blocks, bearer values, labeled secret assignments and passwords
in URLs are scrubbed before new notes are stored. Recall also scrubs legacy note
text before returning it. This is a best-effort guard, not a general secrets scanner,
PII detector or permission to save credentials. It does not scrub historical SQLite
pages or arbitrary private information in prose.

Weftgate makes no network calls for these operations. An MCP client receives retrieved
notes and may transmit them under its own policy. All notes are untrusted data, never
instructions that override the user or the agent's system rules. Automatic transcript
capture, remote embeddings and team sharing are not enabled by the notebook.

## Handoff between agents

`handoff` saves an explicit summary with a scoped checkpoint. `--run` opts into the
configured test commands. The next agent retrieves it through `brief` or `recall`.
Historical evidence includes its tree fingerprint; recall reports whether the current
tree still matches. Even when it does, tests should be run again before the next handoff.
Tests that change source files prevent that handoff from being saved until its summary
is reviewed. See [workflow details](WORKFLOWS.md).

## Legacy mnemo plugin seam

Existing mnemo users can keep `"oracles": ["weftgate.memory"]` in `.mnemo.json`.
The original lower-level anchors API remains supported. Use the explicit read-only migration path to move selected legacy notes into the
public notebook. No existing database is discovered or imported automatically. The rest
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

## Limits

This is a local lexical memory engine. It does not implement semantic embeddings,
automatic transcript distillation or team federation. Compact payloads are measured
in UTF-8 bytes; token counts are estimates rather than a token-savings benchmark.
