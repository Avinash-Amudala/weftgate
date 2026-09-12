# Contributing

The fastest way to help is to write an oracle for a stack weft does not cover yet.
An oracle is one file. Copy `weft/oracles/env_vars.py` as the template and follow
the checklist in `AGENTS.md` section 6.

## The rule that gets a PR merged or rejected

An oracle blocks (`REJECT`) only on a proven, machine-checkable absence. Anything
it cannot resolve (dynamic names, missing index, uninstalled extra) returns
`REVIEW` or `UNVERIFIABLE`. A false block is the one bug we will not merge.

## Every oracle ships with three tests

- true positive: a real broken edge it catches and rejects
- true negative: correct code it accepts
- soft case: a dynamic reference it reviews rather than rejects

See `tests/test_env_vars.py`.

## Before you push

```bash
ruff check . && mypy weft && python -m weft.selftest && pytest -q
```
