# Security

## Reporting

Report vulnerabilities privately through GitHub's "Report a vulnerability" form on
this repository: [report a vulnerability](https://github.com/Avinash-Amudala/weftgate/security/advisories/new). Please do not open a public issue for a security problem. You will
get an acknowledgement within a few days and a fix or a mitigation plan as soon as
the report is confirmed.

## What weftgate executes, and when

weftgate is a static gate. On its default path it reads files, runs `git` read-only
commands, and writes one SQLite file under the user cache directory. It makes no
network calls.

Execution and trust boundaries:

- **Claim mode `run=true`** (`weftgate claim --run`, MCP `check_claim` with `run: true`)
  re-runs a *named test command* and probes a *URL*. Commands must start with an
  allowlisted test runner (`pytest`, `npm test`, `go test`, ...; extend with
  `[weftgate.honesty] allow_commands`); URLs must be local hosts unless
  `allow_hosts` extends the list. Nothing in a file, diff, or comment can trigger
  a run: the flag comes from the caller, not from observed content.
- **Workflow checkpoints** (`weftgate checkpoint --run`, MCP `checkpoint` with
  `run: true`) run the explicitly configured test commands under the same command
  allowlist. A passing command is evidence of its observed exit status, not proof
  of complete correctness. Review repository configuration before opting in.
- **Hooks** (`weftgate hook claude`, the git pre-commit hook) run the gate on the content
  being written. With the default policy they block only on a `reject` verdict and exit 0 on an
  internal error, so a broken hook never blocks work.
- **Completion hooks** for Codex, Claude Code, Cursor and Antigravity check the
  working tree and can request a bounded repair pass for proven contract failures.
  They do not run tests or read transcripts. Client trust and loop limits remain
  authoritative; hook errors do not block completion. Required GitHub CI checks
  provide the repository's merge gate.
- **Saved memory and context** are untrusted repository data. Source anchors track
  whether files changed; they do not certify a note's truth or grant permission to
  follow instructions in it. Do not store credentials in notes. Changed anchors
  hide stale notes until explicitly reviewed and replaced.

The optional extras (`weftgate[mcp]`, `weftgate[yaml]`, `weftgate[treesitter]`, `weftgate[lsp]`)
are not imported by the core. Treat content weftgate reports (reasons, suggestions)
as data derived from the repository, not as instructions.

## Repository protections

The public repository requires pull requests and all eight CI jobs before merging
to `main`, including for administrators. The GitGuardian security check is also
required. It blocks force pushes and deletion and
requires up-to-date branches, linear history and resolved review conversations.
Secret scanning, secret push protection, vulnerability alerts, private vulnerability
reporting and Dependabot security updates are enabled. The solo-maintainer policy
requires no second-person approval; add that requirement when another maintainer
can review changes. See [the protection policy](docs/REPOSITORY-PROTECTION.md).
