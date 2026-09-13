# Move Mnemo memories into Weftgate

For everyday context, memory, handoffs and verification, install **Weftgate only**.
Its local notebook is part of the same package, MCP server and repository database
as the gate. Existing Mnemo users can explicitly transfer reviewed memories.

| Need | Where it lives now |
| --- | --- |
| Decisions, preferences, gotchas, tasks and notes | `weftgate remember` and `recall` |
| Relevant memory plus current source references | `weftgate brief` |
| Check explicit file, env, route, import and symbol claims | Built into `remember` |
| Detect old source evidence | Built into recall; stale notes are hidden by default |
| Session summary and observed checkpoint | `weftgate handoff` |
| Backup or transfer reviewed notes | `weftgate memory export` and `import` |
| Transcript capture, distillation, embeddings or a shared hub | Legacy Mnemo; separate opt-in workflows |

Weftgate does not install Mnemo, load its plugins, discover its databases or read
agent transcripts. Migration copies selected notes; it does not enable capture or
synchronize two running notebooks. Keep the legacy source until you have reviewed
the imported result and made a backup.

## Preview, then import

Choose the source database for the project whose checkout you are in. An agent
must get the user's explicit source selection before opening a private memory file.

```bash
pip install --upgrade weftgate
cd /path/to/the/project
weftgate memory import /path/to/mnemo.sqlite --limit 50
# Inspect eligible notes, redactions, skipped rows and freshness. Then:
weftgate memory import /path/to/mnemo.sqlite --limit 50 --apply
weftgate memory stats
weftgate recall --include-stale
```

The default is a preview with no note inserts. `--apply` inserts the eligible batch
in one transaction. The source SQLite file is opened read-only with extension and
schema execution disabled. No legacy Python code runs. Notes use the current
repository's contracts; use the matching checkout to avoid unrelated stale results.

Supported kinds are decision, convention, task, note, gotcha, howto, command,
handoff, preference and todo. Raw `episode` transcript records are excluded.
Unsupported, malformed or overlong records are reported as skipped. Titles are
limited to 120 characters and bodies to 4,000; text is not silently truncated into
an accepted note. The importer never runs remembered commands.

A Mnemo note ID maps to a stable `mnemo-...` ID. Existing destination IDs are kept,
so repeating a page is safe and does not overwrite reviewed notes. Original source
hashes and grounding commits are preserved. Importing does not reanchor an old
note against today's code. Missing hashes remain stale when a source was claimed;
notes with no source claims are labeled unverified. Review and explicitly replace
stale notes with `remember --id NOTE_ID` and their current references.

The report includes `eligible`, `imported`, `kept_existing`, `skipped`, `has_more`
and `next_offset`. While `has_more` is true, repeat with `--offset NEXT_OFFSET`.
Each page can read up to 500 records. Use a larger `--budget` or smaller `--limit`
when preview items are omitted from the bounded response. With `--apply`, all
eligible records in the requested input page are inserted, even if the response
budget omits their display. Finish migration before editing the source database;
concurrent inserts or deletes can move its offset-based pages.

## Portable backups

```bash
weftgate memory export --limit 50 > memory-page-1.json
# If has_more is true, use the returned next_offset:
weftgate memory export --limit 50 --offset NEXT_OFFSET > memory-page-2.json
```

Exports contain complete notes and original anchors in the `weftgate.memory`
version 1 JSON format. They include stale notes so review history is retained.
The default export budget is 16,000 estimated tokens. If the next note does not
fit, increase `--budget`; no partially exported note is treated as a complete one.
Keep the notebook unchanged while paging to avoid offset shifts.

To restore, run `weftgate memory import /path/to/memory-page-1.json`, review, and
repeat with `--apply`. Import each exported file. `has_more` refers to unread records
inside that input file; `source_export_has_more` warns that the file was one page of
a larger original export. It is not a cursor into the source notebook. Each input
JSON file must be at most 5 MiB.

Handoff summaries transfer as notes. Their historical checkpoint snapshots do not
transfer as reusable proof; run a new checkpoint in the destination checkout.
Exports may contain private project decisions. Store and share them deliberately.
Best-effort secret scrubbing does not make arbitrary memory text public-safe.

## Existing integrations

The lower-level `weftgate.memory` oracle plugin and anchor/check/changes APIs remain
compatible with legacy Mnemo. Existing `.mnemo.json` configuration can keep using
them. After migrating, configure agents to use the Weftgate MCP server for the
unified notebook and disable the old Mnemo server if you no longer need its legacy
features. Setup preserves other servers, existing rules and custom hooks; review
[agent activation](AGENTS-INTEGRATION.md) and update old workflow guidance explicitly.
