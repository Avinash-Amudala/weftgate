# Repository protection

Applied to `Avinash-Amudala/weftgate` on September 13, 2026.

The `main` branch requires a pull request, an up-to-date branch and these successful
GitHub Actions checks:

- `core-only`
- `package`
- `test (py3.10, ubuntu-latest)`
- `test (py3.11, ubuntu-latest)`
- `test (py3.12, macos-latest)`
- `test (py3.12, ubuntu-latest)`
- `test (py3.12, windows-latest)`
- `test (py3.13, ubuntu-latest)`

The checks are bound to GitHub Actions (app ID `15368`). Keep this list and the live
policy aligned when changing the CI matrix, otherwise pull requests may wait for a
check that no longer exists.

`GitGuardian Security Checks` is also required and bound to the GitGuardian app
(ID `46505`), for nine required checks in total. Investigate a failed scan and
resolve real exposures or classify confirmed test fixtures before merging.

Protection applies to administrators. Force pushes and branch deletion are disabled.
Linear history and resolved review conversations are required. Stale approvals are
dismissed. Because this repository currently has one maintainer, the required number
of approving reviews is zero; pull requests and CI are still mandatory. Require an
independent approval when another maintainer is available. Repository owners retain
the ability to change these settings.

GitHub secret scanning and push protection are enabled, as are vulnerability alerts,
private vulnerability reporting and Dependabot security updates. A scanner finding
requires investigation. Removing a real credential from a file does not revoke it.
Classify fabricated test fixtures individually rather than excluding whole test
directories from scanning.

## Verify live settings

With a repository-admin GitHub CLI session, these commands are read-only:

```sh
gh api repos/Avinash-Amudala/weftgate/branches/main/protection
gh api repos/Avinash-Amudala/weftgate --jq .security_and_analysis
gh api repos/Avinash-Amudala/weftgate/private-vulnerability-reporting
```

Use normal pull requests and wait for CI. Do not bypass protection to publish a fix.
Settings are maintained in GitHub, so this document is a record rather than an
automatic policy installer. Check the [live branch settings](https://github.com/Avinash-Amudala/weftgate/settings/branches)
after any policy change.
