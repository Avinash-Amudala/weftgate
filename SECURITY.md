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

Two features run things, and only when the caller opts in:

- **Claim mode `run=true`** (`weftgate claim --run`, MCP `check_claim` with `run: true`)
  re-runs a *named test command* and probes a *URL*. Commands must start with an
  allowlisted test runner (`pytest`, `npm test`, `go test`, ...; extend with
  `[weftgate.honesty] allow_commands`); URLs must be local hosts unless
  `allow_hosts` extends the list. Nothing in a file, diff, or comment can trigger
  a run: the flag comes from the caller, not from observed content.
- **Hooks** (`weftgate hook claude`, the git pre-commit hook) run the gate on the content
  being written. With the default policy they block only on a `reject` verdict and exit 0 on an
  internal error, so a broken hook never blocks work.

The optional extras (`weftgate[mcp]`, `weftgate[yaml]`, `weftgate[treesitter]`, `weftgate[lsp]`)
are not imported by the core. Treat content weftgate reports (reasons, suggestions)
as data derived from the repository, not as instructions.
