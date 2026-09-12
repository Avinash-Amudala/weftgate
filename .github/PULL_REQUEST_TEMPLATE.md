## What

<!-- One or two sentences: which wire this makes weft check, or what it fixes. -->

## Checklist

- [ ] `ruff check . && ruff format --check . && mypy weft && python -m weft.selftest && pytest -q` are clean
- [ ] If this touches an oracle: it still blocks **only on a proven, machine-checkable absence**; anything unresolved reviews
- [ ] If this adds an oracle: a true-positive test (rejects, with a suggestion), a true-negative test, a soft-case test (reviews), and an unverifiable test ship with it
- [ ] `weft eval mutate --seed 13` on the fixture has zero misses, and any change in the field numbers in `docs/FIELD-RESULTS.md` is explained
- [ ] The CLI and the MCP server still agree (`tests/test_cli_mcp_parity.py`)
