# Changelog

All notable changes to weftgate are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [Unreleased]

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
