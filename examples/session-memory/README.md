# New session. Same project brain.

Save a decision, retrieve it in another process, attach observed test evidence to a
handoff, then see what happens when its source changes. This example uses Python's
standard library and Weftgate 0.3 or newer. No model, API key or editor is required.

From this repository's root, activate the environment where you installed Weftgate:

```bash
cd examples/session-memory
weftgate --repo . remember "Order retries" "Keep order creation idempotent." --file orders.py --id demo-order-retries
```

In another terminal, activate the same environment and enter this same directory:

```bash
weftgate --repo . brief "order retries" --reference create_order --budget 1200
```

The response includes the decision and a pointer to `create_order` in `orders.py`.
It returns source locations, not the entire file. The byte cap is explicit; estimated
model tokens are not a measured reduction in your provider bill.

The same `brief` and `remember` tools are exposed through MCP. To use this in an
editor, run `weftgate --repo . setup --agents all --instructions`, review the output,
connect your chosen client to this repository, and ask it to use those tools. Setup
can print instructions for clients with global configuration. This CLI example does
not establish activation in every editor build.

Save a handoff after running the example's configured duplicate-order test:

```bash
weftgate --repo . handoff "Order retries" "Duplicate order test passes. Next: review persistence." --file orders.py --run --require-ready --id demo-handoff
weftgate --repo . brief "order retries"
```

`--run` permits the configured `python -m unittest -q` command. Run this from an
environment where `python` is available. The saved result is historical evidence;
the next agent still needs current checks before claiming its own change works.

Append a comment to `orders.py` in your editor, then run:

```bash
weftgate --repo . recall "order retries"
weftgate --repo . recall "order retries" --include-stale
```

The two source-anchored notes are hidden by default after the file changes. The
second command lets you inspect them for review. A changed comment is enough:
freshness uses a content hash, not semantic equivalence. To refresh a note, review
its text against the current file and explicitly save a replacement with its ID.

Notes live in your local cache, outside Git. Repeated saves with these IDs replace
only these demo notes. No conversations are captured automatically. Unchanged
source files do not prove a note's prose true.

[36-second film](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.3.0/weftgate-session-memory.mp4)
· [Recorded fixture evidence](../../docs/assets/session/evidence.json)

Reproduce the film's assertions without touching your project notebook:

```bash
# From the Weftgate repository root, with the optional demo extra installed:
python -m scripts.make_session_demo --stills-only --out /tmp/weftgate-session-preview
```

The renderer copies this fixture to a temporary Git repository, invokes a fresh CLI
process for every step, and checks the returned memory, source resolution, handoff
readiness and stale-note results. It renders an illustrated walkthrough, not footage
of live editor sessions. Run without `--stills-only` to create the video too.
