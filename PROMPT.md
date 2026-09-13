# Kickoff prompt for Claude Code

Paste the block below into Claude Code with this repo open. It is written to be handed over as-is.

---

You are implementing this repository. It is a tool called weftgate: a verification gate for coding agents that checks the wiring, not the spelling. It reconstructs the relationships in a codebase (route to handler, env var to declaration, import to lockfile, and more) and rejects code that references something that does not resolve, before that code ships.

Before writing any code, read these three files in full: `AGENTS.md`, `docs/DESIGN.md`, and `docs/ADDENDUM-context-and-memory.md`. `AGENTS.md` is the build contract and it is authoritative. `docs/DESIGN.md` is the what and why. The addendum describes later phases that you will not build yet.

Then set up the environment:

```
bash scripts/bootstrap.sh
```

That creates a virtual environment, installs the package with all extras and dev tools, and runs the self-test. If the script is missing or fails, do the equivalent by hand: create a venv, `pip install -e ".[all,dev]"`, then `python -m weftgate.selftest`. Confirm the self-test passes before you change anything.

Your scope is v0.1 only: the verification gate. Do not build the context surface or the memory consumer from the addendum. Those are v0.2 and v0.3 and come later.

Build in the exact order given in `AGENTS.md` section 8. Do not start a phase until the previous phase's tests pass. After each phase, run all four checks and make sure they are clean before moving on:

```
ruff check . && mypy weftgate && python -m weftgate.selftest && pytest -q
```

Hold to these invariants at all times. They are load-bearing, and breaking any of them is worse than being slow:

- Block only on a positive, machine-checkable falsehood. A missing index, an unresolvable dynamic reference, an uninstalled optional extra, or a claim derived from prose all soften to review or unverifiable. They never reject. When you are unsure whether something should reject or review, it reviews.
- Keep the core standard-library only. The modules `types`, `config`, `registry`, `oracle`, `store`, `gate`, `change`, `suggest`, `honesty`, `cli`, and `mcp_server` import nothing outside the standard library. Anything heavier is an optional extra that degrades to unverifiable when it is absent, and you test it with the extra uninstalled.
- The CLI and the MCP server must never diverge. Both call the same gate functions, and a test asserts their outputs match for the same input.
- Never return a proven verdict for an outcome claim without machine-checkable evidence you could re-derive.
- Everything is deterministic. The same repo state and the same input give the same findings, in a stable order. The eval harness depends on this.
- Every oracle ships with three tests: a true positive it rejects, a true negative it accepts, and a soft case it reviews rather than rejects. Use `tests/test_env_vars.py` as the template. `weftgate/oracles/env_vars.py` is the fully worked reference oracle; the two other oracles are stubs with their contracts written in their docstrings, and you implement them to match.

If you need an open-source library while building, add it to the correct group in `pyproject.toml`. Keep the core group empty; put anything heavier under an optional extra. Do not add a dependency to the core unless the tool cannot run without it, and prefer the standard library.

Do not rename the project; checking the name is a human task for before release, not part of the build. Do not replace the LICENSE file; it already carries the required notice.

When each phase is done, report back in a few plain sentences: what you implemented, which of the four checks pass, and anything in the design that turned out to be wrong or underspecified so it can be fixed in the source of truth rather than worked around.
