# Changelog

All notable changes to weftgate are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

## [0.3.0] - 2026-09-13

### Added
- One local memory workflow in Weftgate: `brief` combines relevant notes and source
  context; `handoff` saves a session summary with historical checkpoint evidence.
- Explicit file, env, route, import and symbol claims on remembered notes, with
  proven false claims refused and uncertain evidence retained for review.
- Read-only Mnemo migration with preview/apply, original source hashes, stable IDs,
  transaction rollback and exclusion of raw transcript episodes.
- Portable paginated memory export/import and aggregate `memory stats`.
- Mnemo note kinds, including preferences and todos, and best-effort secret scrubbing
  before note writes and legacy-text output. No second package is required.

### Changed
- Import anchors track dependency contract changes. Old evidence is never silently
  refreshed into a current claim, including during migration.
- Handoff summaries are not saved when source changes during checking or saving.
  Recalled checkpoint snapshots are labeled historical and compared with the current tree.
- Unified CLI/MCP surfaces and setup guidance for one public package. Existing note
  storage and the legacy Mnemo plugin API remain compatible.
- Rewrite product architecture and migration docs around the implemented workflow.

### Scope
- Transcript capture, distillation, embeddings and team hubs remain legacy opt-in
  features. The notebook does not enable them. The attached motion film demonstrates
  the v0.2 foundation; the new commands are documented in the migration/workflow guides.

## [0.2.0] - 2026-09-13

### Added
- Bounded source context: `resolve`, `neighbors` and `card`, shared by CLI and MCP.
- Local `remember`, `recall` and `forget`, integrating mnemo's lexical grounding
  design without requiring a private companion package. Changed sources are hidden.
- Current-tree `checkpoint` with explicit test execution and incomplete-evidence states.
- Project MCP setup for Codex and Antigravity, completion hooks for four editors,
  and opt-in workflow instructions that preserve existing configuration.
- Brain visual and evidence-backed context/memory walkthrough.

### Changed
- The ledger reports observed payload bytes and gate events. Removed speculative
  token savings based on a fixed cost per rejection.
- Setup uses atomic file replacement and rejects symlink destinations before writes.
- Reduce repeated stat calls and path filtering in no-Git index scans.

## [0.1.1] - 2026-09-13

### Fixed
- Use absolute repository documentation links in the package README so they work
  on PyPI as well as GitHub. Verification behavior is unchanged.

### Added
- Release validation record and an unpublished developer walkthrough for the launch.

## [0.1.0] - 2026-09-12

The verification gate.

### Added
- Verified memory (the recall consumer, addendum A5) as an integration with mnemo: a
  changed-node ledger every sync appends to, anchors with content hashes and the
  grounding commit, re-checks that yield valid/stale/invalid, and weftgate's oracles as a
  mnemo verification plugin. `weftgate memory anchor|check|changes` and the
  `memory_anchor`, `memory_check`, `memory_changes` MCP tools. See docs/MEMORY.md.
- Three Tier 0 oracles, standard library only: `env_vars` (reads vs declarations across
  dotenv files, settings schemas, Dockerfile/compose, code defaults), `imports_lockfile`
  (imports vs lockfiles and manifests for Python and Node, with import-name aliases,
  tsconfig path aliases, monorepo and nested project roots), `routes_fastapi` (routes
  vs handlers and `include_router` wiring, built statically with `ast`).
- Diff mode (file, new content, unified diff, git working tree or staged) and claim
  mode (structured claims, including route existence and outcome claims).
- The honesty gate: outcome claims graded PROVEN / PLAUSIBLE / NOT_OBSERVED /
  CONTRADICTED; never PROVEN without machine-checkable evidence; re-runs and probes
  are opt-in and allowlisted.
- Per-repo SQLite index with atomic per-oracle tables and incremental sync (git diff
  plus untracked files, fingerprint fallback without git).
- A CLI and a standard-library stdio MCP server with an output-parity test; a Claude
  Code PreToolUse hook adapter; `weftgate setup` writing config, index, git pre-commit
  hook, and MCP config for Claude Code, Cursor, and VS Code; a GitHub Action;
  pre-commit hooks.
- Measurement: a seeded mutation harness that reports detected, blocked, and
  correctly suggested separately; an audit sweep; an offline self-test; field
  results on six open-source repositories.
- An oracle-authoring guide and a scaffold script.

### Release hardening
- Refresh reused sessions, detect worktree reverts, preserve indexes on failed rebuilds,
  and isolate nested transactions with savepoints.
- Review incomplete dependency metadata and dynamic route evidence; never use installed
  dependency percentages as proof of absence.
- Preserve original memory hashes, invalidate changed symbols and declarations, and
  return a safe pagination cursor for the changed-node ledger.
- Validate structured claims, escape GitHub annotation properties, count nested JUnit
  failures, and prevent opt-in URL probes from following redirects.
- Preserve existing hooks and refuse malformed agent configuration.
- Pass Action inputs as process arguments; gate trusted PyPI publishing on the full CI
  matrix and extract release notes without dropping their final line.
- Add a reproducible captioned demo, release documentation, and an organic launch plan.

### Verdict rules worth knowing
- A verdict blocks only on a positive, machine-checkable falsehood. A missing index,
  an uninstalled extra, a dynamic reference, a documentation snippet, a repo with no
  declaration source, or a name absent from a manifest without a lockfile all soften
  to review or unverifiable.
