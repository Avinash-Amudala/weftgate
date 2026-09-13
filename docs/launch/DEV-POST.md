---
title: Catch broken environment, import, and route connections with Weftgate
tags: python, testing, showdev, devtools
published: true
url: https://dev.to/avinash_amudala_8712ab560/catch-broken-environment-import-and-route-connections-with-weftgate-2h3p
---

I maintain Weftgate, an open-source verification gate for coding agents. It checks environment-variable reads, dependency imports, and FastAPI route references against contracts in the repository. It runs locally through a CLI, MCP, hooks, and CI.

The core has no runtime dependencies and makes no network calls on its default path. It is an early static analyzer with explicit limits. A passing gate does not prove that an application works.

## Start with a small, reproducible case

Use Python 3.10 or later in a fresh directory:

```bash
mkdir weftgate-example
cd weftgate-example
python3 -m venv .venv
. .venv/bin/activate
pip install weftgate
printf 'DATABASE_URL=\n' > .env.example
printf 'import os\nurl = os.environ["DATABSE_URL"]\n' > app.py
weftgate check app.py
```

The environment oracle compares the read with `.env.example`. The misspelled hard claim rejects, exits 1, and suggests `DATABASE_URL`.

Correct the reference and check again:

```bash
printf 'import os\nurl = os.environ["DATABASE_URL"]\n' > app.py
weftgate check app.py
```

This time the reference resolves. Now try a computed key:

```bash
printf 'import os\nkey = "DATABASE_URL"\nurl = os.environ[key]\n' > app.py
weftgate check app.py
```

That returns `review`, with exit code 0. The environment parser does not establish the computed key's value, so the finding stays advisory.

These are constructed demonstrations, not field accuracy benchmarks.

## Follow the connections across files

The [58-second demo](https://github.com/Avinash-Amudala/weftgate/releases/download/v0.1.1/weftgate-demo-motion.mp4) traces three intentional mistakes in a fixture:

| Reference | Repository evidence | Suggested correction |
| --- | --- | --- |
| `import requestz` | Dependency declarations | `requests` |
| `os.environ["DATABSE_URL"]` | `.env.example` | `DATABASE_URL` |
| Route handler `helth` | Defined/imported handlers | `health` |

[![Animated evidence trace and repair](https://raw.githubusercontent.com/Avinash-Amudala/weftgate/main/docs/assets/demo.gif)](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/DEMO.md)

You can reproduce the broader mutation fixture locally:

```bash
weftgate eval mutate --fixture --seed 13
```

The harness measures detection, blocking, and usable suggestions separately. Its fixture score is not a claim about arbitrary repositories.

## Why the uncertain cases matter

An import absent from a manifest can be transitive. A router produced by a factory can register paths that a static scan cannot enumerate. A missing index cannot establish absence. These cases must review or be reported as unverifiable.

An `accept` result only describes the extracted claims. Continue running your tests, type checker, security checks, and normal review.

## Try it on an existing project

```bash
weftgate doctor
weftgate audit
weftgate check app/main.py
```

`doctor` explains which contracts are available. Environment reads supplied externally should be documented in your declaration source. Python and Node dependency resolution can depend on workspace and runtime configuration, so review findings in context.

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
      - uses: Avinash-Amudala/weftgate@v0.1.1
```

MCP clients can start `weftgate mcp` from the target repository. The tools and CLI call the same gate functions; no separate model API or server account is required.

## Help improve the boundaries

The most useful feedback is a minimal example of a false block or a missing contract. There are also contribution issues for workspace fixtures and a first-project walkthrough.

- [Repository and installation](https://github.com/Avinash-Amudala/weftgate)
- [Demo transcript and reproducible evidence](https://github.com/Avinash-Amudala/weftgate/blob/main/docs/DEMO.md)
- [Report a reproducible issue](https://github.com/Avinash-Amudala/weftgate/issues/new/choose)

Disclosure: this walkthrough was generated with AI and checked against the project's reproducible fixtures. It does not claim independent benchmark results.
