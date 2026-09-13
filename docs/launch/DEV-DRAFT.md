---
title: Catch broken environment, import, and route connections with Weftgate
description: A reproducible introduction to a local verification gate for coding agents.
tags: python, opensource, devtools, ai
published: false
---

An agent can generate a plausible file with an environment-variable typo, an undeclared
import, or a route wired to a nonexistent handler. Weftgate checks those references
against contracts in the repository. It runs locally through a CLI, MCP, hooks, and CI.

The core has no runtime dependencies and makes no network calls on its default path.
It is an early static analyzer, with explicit limits—not proof that an application works.

## Start with a small, reproducible case

Use Python 3.10 or later in a temporary directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install weftgate
printf 'DATABASE_URL=\n' > .env.example
printf 'import os\nurl = os.environ["DATABSE_URL"]\n' > app.py
weftgate check app.py
```

The environment oracle compares the read with `.env.example`. The misspelled hard claim
rejects, exits 1, and suggests `DATABASE_URL`. Correct the name and check again. A dynamic
key such as `os.environ[key]` reviews instead: the parser cannot prove its value.

This is a constructed demonstration, not a field accuracy benchmark.

## Why the uncertain cases matter

An import absent from a manifest can be transitive. A router produced by a factory can
register paths that a static scan cannot enumerate. A missing index cannot establish
absence. These cases must review or be reported as unverifiable, rather than block.

An `accept` result only describes the extracted claims. Continue running your tests,
type checker, security checks, and normal review.

## Try it on an existing project

```bash
weftgate doctor
weftgate audit
weftgate check app/main.py
```

`doctor` explains which contracts are available. Environment reads supplied externally
should be documented in your declaration source. Python and Node dependency resolution
can depend on workspace and runtime configuration, so review the findings in context.

For a pull request:

```yaml
name: Verify connections
on: [pull_request]
permissions:
  contents: read
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - uses: Avinash-Amudala/weftgate@v0.1.0
```

MCP clients can start `weftgate mcp` from the target repository. The tools and CLI call the
same gate functions; no separate model API or server account is required.

## Help improve the boundaries

The most useful feedback is a minimal example of a false block or a missing contract.
There are also bounded contribution issues for workspace fixtures and a first-project
walkthrough.

- [Repository and installation](https://github.com/Avinash-Amudala/weftgate)
- [52-second demo and reproducible evidence](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/DEMO.md)
- [Report a reproducible issue](https://github.com/Avinash-Amudala/weftgate/issues/new/choose)

Disclosure: this project walkthrough was drafted with AI assistance and checked against
the project's reproducible fixtures. It does not claim independent benchmark results.
