# Grounded context, source-aware memory and verification

The v0.3 product is a local second brain for coding agents: understand, remember,
verify. This extends the released v0.1 gate without changing its central rule:
reject only a positive, machine-checkable falsehood. Missing evidence stays visible
as review or unverifiable. A passing static gate is not complete correctness.

## Shared local substrate

The per-repository SQLite store holds oracle indexes, a content-hash Python parsing
cache, changed-node history, and explicitly saved notes. CLI and MCP call the same
functions through `brain.call` and `gate.Session`.

- `context.py`: exact resolution and bounded observed relationship slices.
- `recall.py` and `privacy.py`: local lexical storage, source grounding and
  best-effort secret scrubbing adapted from Mnemo. No private transcripts or personal configuration.
- `transfer.py`: bounded read-only import from an explicitly selected Mnemo database
  or portable JSON export. Original hashes are retained; existing IDs are preserved.
- `brief.py`: one task response combining notes and context, plus historical handoffs.
- `workflow.py`: current-tree checks and optionally observed configured tests.
- `hooks.py`: editor-specific completion responses with bounded continuation.
- `payload.py`: compact serialization, complete-item elision and measured byte limits.

Python definitions are cached by content hash. The context graph is assembled from
current oracle indexes and source references on demand. It does not claim a full
incremental cross-language runtime graph. Network-dependent indexing, cloud memory,
automatic transcript capture, embeddings and runtime call dispatch are outside
this release. Core modules remain standard-library-only.

## Context contract

`resolve(reference)`, `neighbors(reference, hops=1, kinds=...)`, and `card(reference)`
return nodes and observed edges with source locators, ambiguity and coverage notes.
No file bodies or environment values are returned. Missing names are not guessed.
Unsupported syntax and dynamic relationships remain explicit limitations.

The default budget is 1,500 estimated tokens, enforced as 6,000 UTF-8 JSON bytes.
Accounting includes the JSON text envelope. Token estimates use bytes divided by
four and are not exact tokenization. Ranked items are omitted whole. MCP text is
not duplicated as structuredContent. See [CONTEXT.md](CONTEXT.md).

## Memory contract

`remember`, `recall` and `forget` are available from a single public install. An
explicit source citation stores its source hash. File, env, import, route and
symbol claims are checked before storage. Proven false claims refuse the write;
missing evidence stays stale for review. Each recall checks candidate anchors;
changed or deleted sources are hidden by default. Repeated reads never rewrite the
original evidence. An explicit replacement with the note ID re-anchors reviewed text.

The notebook also includes `brief`, `handoff`, `memory_import`, `memory_export` and
`memory_stats`. Existing seven-column note tables remain readable. A handoff stores
a historical checkpoint in a separate linked table; recall compares its fingerprint
with the current tree. Tree changes while checking or saving roll back the handoff.
Portable export copies summary notes without turning old checkpoints into proof.

An anchored note is source-current, not semantically proven. Unanchored preferences
are marked unverified. Every note is untrusted data, never authority over the user.
Legacy mnemo retains the lower-level anchor/check/changes plugin seam. See
[MEMORY.md](MEMORY.md).

## Workflow contract

The coding agent remains responsible for reasoning, edits and repairs. A checkpoint
verifies present working-tree changes, including staged and untracked code. Configured
commands execute only with explicit `run` opt-in and the existing allowlist. Before
and after repository fingerprints detect changes during the check. A `ready` report
covers this set of contracts and commands, not all application behavior.

Completion hooks request a bounded repair pass after positive failures. They do not
silently run tests, capture transcripts, override interrupts or loop forever. Client
trust and policy can prevent execution. CI branch protection is the portable merge
boundary. See [WORKFLOWS.md](WORKFLOWS.md) and [AGENTS-INTEGRATION.md](AGENTS-INTEGRATION.md).

## Measurement and tests

Measure returned UTF-8 payload bytes and actual gate events. Repeated rejections
can produce repeated events. Neither a rejection nor an omitted context item proves
a saved retry or a token saving. Any comparison must define a task, baseline,
model/tokenizer and identical outcome quality. No fixed savings estimate is generated.

Tests cover Unicode budgets, deterministic resolution, stale and removed sources,
optional-dependency absence, CLI/MCP parity, scoped paths, native hook protocol shapes,
loop limits, setup preservation, staged/untracked changes and observed test outcomes.
Editor builds require their own activation smoke test. Fixture scores demonstrate
behavior and are not field accuracy claims.
