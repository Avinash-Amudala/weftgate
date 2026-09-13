# Release validation

## Unified memory workflow, v0.3.0

Local validation on macOS / Python 3.13:

- **229 tests passed, 91.07% line coverage**, including a run treating resource and
  unraisable-exception warnings as errors. File handles in older tests and the
  self-test were corrected during that stricter check.
- Ruff lint and formatting, strict mypy, the offline self-test, and all 13 seeded
  fixture mutations passed. Self-audit reports four dynamic plugin imports for
  review and no blocking findings.
- A wheel built from the source distribution installed with no runtime dependencies
  in a fresh virtual environment outside the checkout. `pip check` and the offline
  self-test passed; MCP, tree-sitter, pylsp and yaml were confirmed absent.
- Regression tests cover explicit false memory claims, missing evidence, dependency
  contract drift, Unicode search, source-preserving migration, legacy schemas,
  preferences/todos, redaction, malformed input, import rollback and export paging.
- Brief/transfer CLI and MCP parity, byte budgets, explicit test opt-in, historical
  handoff evidence, source changes during tests and rollback on changes while saving
  are covered. Existing v0.2 note IDs and the lower-level memory API remain compatible.
- The local legacy Mnemo self-test also passes against this source tree, including
  its source-grounding integration. No private database or transcript was migrated
  as part of validation; transfer fixtures are fabricated.

Cross-platform release results are recorded by the linked pull request and tag
workflow once they complete. The existing 78-second film demonstrates the v0.2
foundation; it does not record the new v0.3 commands.

## Grounded context and recall, v0.2.0

Local validation before the release:

- **199 tests passed, 90.88% line coverage** on macOS / Python 3.13.
- Ruff lint and formatting, strict mypy, offline self-test and the seeded fixture
  mutation evaluation. The 13 injected mutations were detected, blocked and given
  usable suggestions. This does not estimate field accuracy.
- Fresh wheel installed without dependencies in an isolated environment; the
  complete offline self-test ran outside the source checkout.
- Regression coverage for dirty/deleted sources, ambiguous symbols, stale note
  suppression, explicit reanchoring, repository isolation, Unicode byte budgets,
  CLI/MCP output parity, staged/untracked changes, observed passing/failing commands,
  native completion protocols and preserving shared Git worktree hooks.
- Native hook protocol fixtures cover Codex, Claude Code, Cursor and Antigravity.
  Interactive certification against every editor version is not claimed. Review
  project trust and follow [the activation checks](AGENTS-INTEGRATION.md).
- Captioned 78-second film: 1920×1080, 30 fps, H.264/AAC, fast-start MP4. Complete
  audio/video decoding passed; encoded scenes were visually reviewed. Source,
  actual CLI evidence, a 598 KB GIF and the brain artwork are included.
- The private mnemo companion self-test passes with stale sources hidden on recall
  and original grounding hashes preserved.

[Release validation and trusted publishing](https://github.com/Avinash-Amudala/weftgate/actions/runs/34743831555)
passed for tag `v0.2.0` at `d97754d51ae2f5dea94fd5db6eecd9ee3ac81de3`, including Linux
Python 3.10–3.13, macOS, Windows, core-only and package checks. A fresh installation
of `weftgate==0.2.0` from PyPI passed `pip check` and the complete offline self-test
outside the source checkout. The Windows scan target passes after removing repeated
path filtering and redundant stat calls; its one-second bound was retained.

The maintainer's Weftgate and mnemo checkouts now have project MCP configuration,
completion hooks and workflow guidance for all four editors. Client trust remains a
separate activation step. Weftgate's configured test checkpoint observed passing
tests with an unchanged tree fingerprint. GitHub `main` protection was enabled on
September 13, 2026: pull requests, eight required CI jobs, up-to-date branches,
resolved conversations, linear history and administrator enforcement. Force pushes
and branch deletion are blocked. The GitGuardian security check is also required.
See [repository protection](REPOSITORY-PROTECTION.md).
GitHub secret scanning, push protection, vulnerability alerts and Dependabot
security updates are enabled. These settings apply to the public Weftgate repository.

## Verification gate, v0.1.0

The release tag points to `9021b73b95fa5e4d0c7db967623acf5114cb809b`.
[The release workflow](https://github.com/Avinash-Amudala/weftgate/actions/runs/34734768156)
passed before publishing the wheel and source distribution using PyPI trusted publishing.

- **157 tests** with all extras installed; approximately **90% line coverage**.
- Linux: Python 3.10, 3.11, 3.12, 3.13. macOS and Windows: Python 3.12.
- Separate core-only job, with optional libraries asserted absent; only the optional
  official MCP-client test skips. The standard-library MCP protocol test still runs.
- Ruff lint and formatting, strict mypy, offline self-test, package build, and Twine metadata checks.
- Fixture mutation evaluation: 13 injected changes detected, blocked, and correctly
  suggested; zero misses. This is a fixture result, not field accuracy.
- Fresh virtual environment outside the checkout: installed `weftgate==0.1.0` directly
  from PyPI, ran `weftgate --version`, the complete offline self-test, and `pip check` successfully.
- Demo: 52 seconds, 1920×1080, H.264 MP4; reviewed the rendered scenes. GIF, captions,
  renderer, and actual CLI evidence are included. No private repository content is used.

Regression coverage includes stale-session refresh, failed-index rollback and recovery,
worktree reverts, nested transactions, dynamic routing, incomplete dependency evidence,
JUnit failures/skips, probe redirects, structured-input validation, Action argument
handling, GitHub annotation escaping, hook preservation, and memory invalidation.

These checks do not establish that the analyzer is flawless, cover every framework,
or constitute an independent security audit. Historical field numbers are explicitly
separated from current release validation in [FIELD-RESULTS.md](FIELD-RESULTS.md).

## Mnemo companion

The companion repository remains private as requested. Its separate CI matrix passes
on Python 3.10–3.13, with and without Weftgate installed. Self-tests include fabricated
transcripts, recall, consent/redaction, false-claim rejection, stale-memory retention,
import aliases, tenant isolation, and local HTTPS. Both local project configurations
enable `weftgate.memory`; neither enables a remote hub or external embeddings.

The original grounding hashes are retained during re-verification. Changed content and
uncertain dependency evidence cannot silently restore memory validity.

## Packaging follow-up, v0.1.1

The live PyPI check exposed relative documentation links in the v0.1.0 package README.
v0.1.1 makes them absolute and adds this record; verification behavior is unchanged.
Its tag is subject to the same full release-validation workflow.
