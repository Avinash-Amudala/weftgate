# Release validation

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
