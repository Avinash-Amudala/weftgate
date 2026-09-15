# Weftgate: creator demo brief

**New session. Same project brain.**

Weftgate is a free, Apache-2.0 local memory and context tool for coding agents, with
verification built into the workflow. Save decisions with source anchors, request
a compact task brief, and leave a handoff with observed checks for the next session.
One Python install provides CLI, MCP, a local notebook and verification tools.

## The 45-second story

| Time | Show | Say in your own words |
| --- | --- | --- |
| 0–5s | A new agent session beside a small project | A fresh chat should not mean explaining every project decision again. |
| 5–15s | Save the idempotency decision with `remember` | Keep a useful decision and the file it belongs to in a local notebook. |
| 15–25s | A new process calls `brief` | The next connected agent can retrieve the note and current source pointers. |
| 25–33s | `handoff --run` observes the fixture test | Leave the next step and the checks actually observed. Old results remain historical. |
| 33–40s | Edit the source and recall | Changed sources hide stale notes by default. Review before trusting old decisions. |
| 40–45s | Install command and repository link | Try the example on GitHub. Star it if it is useful to your workflow. |

The [copyable example](../../examples/session-memory/README.md) runs without an AI
subscription. Its [recorded evidence](../assets/session/evidence.json) is produced by
real, separate CLI invocations. The [vertical film](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.3.0/weftgate-session-memory.mp4)
is an animated walkthrough with original brain graphics and sound design, suitable
as source material. Please record your own experience and retain editorial independence.

## Accurate claims

- Connect clients to the same local repository and store for shared recall. This is
  not automatic cloud synchronization between computers.
- Setup supports Codex, Claude Code, Cursor, Antigravity and other documented MCP
  clients. Review configuration, project trust and activation in the version used.
- Notes are explicit. No automatic transcript capture, private Mnemo installation,
  API key or embedding service is required for the public workflow.
- Bounded source pointers can help control context payloads. Token counts vary by
  model; no measured savings percentage or unlimited context is claimed.
- Gates check supported env, import and FastAPI relationships. Tests need explicit
  execution permission. Passing checks do not establish complete correctness.

## Collaboration scope to quote

Proposed pilot: one original Instagram Reel and one Story with a repository link.
Please quote the full fee, any applicable taxes, current delivery timing and any
optional organic repost rights separately. Share recent relevant Reel reach and
audience geography; follower counts alone do not establish a developer audience.

Any paid collaboration must be clearly disclosed. The ask is an honest product
demonstration and useful feedback. No guaranteed positive review, purchased stars,
coordinated votes or star-contingent payment. This brief is not a booking or a contract.

Repository: https://github.com/Avinash-Amudala/weftgate

Install: `pip install weftgate`

Questions and reproducible feedback: [GitHub Discussions](https://github.com/Avinash-Amudala/weftgate/discussions).
