"""Claim-mode honesty gate: grade outcome claims by evidence. Never PROVEN
without a matching machine-checkable signal.

Outcome claims: "tests pass", "bug fixed", "endpoint returns <status>".
Verdicts: PROVEN | PLAUSIBLE | NOT_OBSERVED | CONTRADICTED.

The ladder, per kind:

tests_pass
  re-run the named command (opt-in ``run=True``, allowlisted)  exit 0 -> PROVEN
                                                               else   -> CONTRADICTED
  (a refused or failed re-run falls through to the supplied evidence below)
  a JUnit XML report on disk with tests>0 and no failures/errors       -> PROVEN
  a report with failures or errors                                     -> CONTRADICTED
  a self-reported exit code of 0 / "N passed" output                   -> PLAUSIBLE
  a self-reported non-zero exit code / "N failed" output               -> CONTRADICTED
  nothing                                                              -> NOT_OBSERVED

endpoint_status
  an actual probe (opt-in ``run=True``, local hosts only by default)   -> PROVEN/CONTRADICTED
  a self-reported observed status                                      -> PLAUSIBLE/CONTRADICTED
  nothing                                                              -> NOT_OBSERVED

bug_fixed
  re-run the repro command: signature absent and exit 0               -> PROVEN
                            signature present                          -> CONTRADICTED
  before/after logs: signature in before, absent after                 -> PLAUSIBLE
                     signature still present after                     -> CONTRADICTED
  nothing                                                              -> NOT_OBSERVED

Re-running is a side effect, so it is off unless the caller passes ``run=True``
and the command starts with an allowlisted test runner (``[weft.honesty]
allow_commands`` extends the list). Probing is limited to localhost unless
``allow_hosts`` extends it. Standard library only; no network on the default path.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from .config import Config
from .types import Claim, Finding, Level, StrEnum

KINDS = frozenset({"tests_pass", "endpoint_status", "bug_fixed"})

DEFAULT_ALLOWED_COMMANDS = (
    "pytest", "py.test", "python -m pytest", "python3 -m pytest", "python -m unittest",
    "python3 -m unittest", "tox", "nox", "npm test", "npm run test", "pnpm test", "pnpm run test",
    "yarn test", "npx jest", "npx vitest", "jest", "vitest", "bun test", "go test", "cargo test",
    "make test", "mvn test", "gradle test", "./gradlew test", "dotnet test", "rspec",
    "bundle exec rspec", "phpunit", "mix test", "swift test", "ctest",
)
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0")
_DEFAULT_TIMEOUT = 600
_PASSED = re.compile(r"\b(\d+) passed\b")
_FAILED = re.compile(r"\b(\d+) (failed|errors?)\b")


class Honesty(StrEnum):
    PROVEN = "proven"
    PLAUSIBLE = "plausible"
    NOT_OBSERVED = "not_observed"
    CONTRADICTED = "contradicted"


@dataclass
class OutcomeClaim:
    kind: str  # "tests_pass" | "endpoint_status" | "bug_fixed"
    detail: dict[str, Any]  # e.g. {"command": "pytest -q"} or {"url": "...", "status": 200}
    evidence: dict[str, Any] | None = None  # supplied artifact, if any


@dataclass
class OutcomeVerdict:
    verdict: Honesty
    reason: str
    needed: str = ""  # what evidence would settle it, when NOT_OBSERVED
    observed: dict[str, Any] = field(default_factory=dict)  # the signal, when there was one


@dataclass
class Policy:
    """What the grader may do on the machine it runs on."""

    run: bool = False
    repo_root: str | None = None
    allow_commands: tuple[str, ...] = DEFAULT_ALLOWED_COMMANDS
    allow_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS
    timeout: int = _DEFAULT_TIMEOUT

    @classmethod
    def from_config(cls, config: Config | None, repo_root: str | None, run: bool) -> Policy:
        extra = config.oracle_config("honesty") if config is not None else {}
        cmds = tuple(DEFAULT_ALLOWED_COMMANDS) + tuple(str(c) for c in extra.get(
            "allow_commands", []))
        hosts = tuple(DEFAULT_ALLOWED_HOSTS) + tuple(str(h) for h in extra.get("allow_hosts", []))
        timeout = int(extra.get("timeout", _DEFAULT_TIMEOUT))
        return cls(run=run, repo_root=repo_root, allow_commands=cmds, allow_hosts=hosts,
                   timeout=timeout)

    def command_allowed(self, command: str) -> bool:
        norm = " ".join(command.split())
        return any(norm == a or norm.startswith(a + " ") for a in self.allow_commands)

    def host_allowed(self, url: str) -> bool:
        m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]+@)?(\[[^\]]+\]|[^:/?#]+)", url, re.I)
        if not m:
            return False
        host = m.group(1).lower()
        return host in {h.lower() for h in self.allow_hosts}


def grade(claim: OutcomeClaim, policy: Policy | None = None) -> OutcomeVerdict:
    """Grade one outcome claim. Default is honest ignorance: never PROVEN by default."""
    policy = policy or Policy()
    match claim.kind:
        case "tests_pass":
            return _grade_tests(claim, policy)
        case "endpoint_status":
            return _grade_endpoint(claim, policy)
        case "bug_fixed":
            return _grade_bug(claim, policy)
        case _:
            return OutcomeVerdict(Honesty.NOT_OBSERVED, f"unknown outcome kind {claim.kind!r}",
                                  needed=_needed(claim.kind))


def _needed(kind: str) -> str:
    return {
        "tests_pass": "a command weft can re-run whose exit code is 0 (pass run=true), or a "
                      "JUnit XML report path",
        "endpoint_status": "an actual probe of the URL returning the claimed status "
                           "(pass run=true for a local URL)",
        "bug_fixed": "the specific failure signature observed before and absent after the fix, "
                     "or a repro command weft can re-run",
    }.get(kind, "a machine-checkable signal")


# --- tests_pass ------------------------------------------------------------------------------


def _grade_tests(claim: OutcomeClaim, policy: Policy) -> OutcomeVerdict:
    detail, evidence = claim.detail, claim.evidence or {}
    command = str(detail.get("command") or evidence.get("command") or "").strip()
    needed = _needed("tests_pass")
    note = ""
    if policy.run and command:
        if not policy.command_allowed(command):
            note = (f"refused to re-run {command!r}: not an allowlisted test command "
                    f"(add it to [weft.honesty] allow_commands)")
        else:
            ran = _run(command, policy, str(detail.get("cwd") or ""))
            if ran is None:
                note = f"re-running {command!r} timed out or could not start"
            else:
                code, output = ran
                if code == 0:
                    return OutcomeVerdict(Honesty.PROVEN, f"re-ran {command!r}: exit code 0",
                                          observed={"exit_code": 0, "command": command})
                return OutcomeVerdict(Honesty.CONTRADICTED,
                                      f"re-ran {command!r}: exit code {code}",
                                      observed={"exit_code": code, "command": command,
                                                "output_tail": _tail(output)})
    # No observation of our own: grade what was supplied, noting why we did not run.
    verdict = _grade_tests_evidence(detail, evidence, policy, needed)
    if note:
        verdict.reason = f"{verdict.reason}; {note}"
    return verdict


def _grade_tests_evidence(
    detail: dict[str, Any], evidence: dict[str, Any], policy: Policy, needed: str
) -> OutcomeVerdict:
    report = detail.get("report") or evidence.get("report") or evidence.get("junit")
    if report:
        path = str(report)
        if not os.path.isabs(path) and policy.repo_root:
            path = os.path.join(policy.repo_root, path)
        parsed = _parse_junit(path)
        if parsed is None:
            return OutcomeVerdict(Honesty.NOT_OBSERVED,
                                  f"test report {report!r} is missing or not JUnit XML",
                                  needed=needed)
        tests, failures, errors = parsed
        if tests > 0 and failures == 0 and errors == 0:
            return OutcomeVerdict(Honesty.PROVEN,
                                  f"parsed {report}: {tests} tests, 0 failures, 0 errors",
                                  observed={"report": str(report), "tests": tests})
        if failures or errors:
            return OutcomeVerdict(Honesty.CONTRADICTED,
                                  f"parsed {report}: {failures} failures, {errors} errors",
                                  observed={"report": str(report), "failures": failures,
                                            "errors": errors})
        return OutcomeVerdict(Honesty.NOT_OBSERVED, f"parsed {report}: no tests recorded",
                              needed=needed)
    if "exit_code" in evidence:
        try:
            code = int(evidence["exit_code"])
        except (TypeError, ValueError):
            return OutcomeVerdict(Honesty.NOT_OBSERVED, "exit_code evidence is not an integer",
                                  needed=needed)
        if code == 0:
            return OutcomeVerdict(Honesty.PLAUSIBLE,
                                  "self-reported exit code 0; weft did not observe the run "
                                  "(pass run=true to re-run it)")
        return OutcomeVerdict(Honesty.CONTRADICTED, f"self-reported exit code {code}",
                              observed={"exit_code": code})
    output = str(evidence.get("output") or "")
    if output:
        failed = sum(int(m.group(1)) for m in _FAILED.finditer(output))
        passed = sum(int(m.group(1)) for m in _PASSED.finditer(output))
        if failed:
            return OutcomeVerdict(Honesty.CONTRADICTED,
                                  f"supplied output reports {failed} failed/errored",
                                  observed={"failed": failed})
        if passed:
            return OutcomeVerdict(Honesty.PLAUSIBLE,
                                  f"supplied output reports {passed} passed; weft did not "
                                  f"observe the run")
    return OutcomeVerdict(Honesty.NOT_OBSERVED, "no evidence supplied for tests_pass",
                          needed=needed)


def _parse_junit(path: str) -> tuple[int, int, int] | None:
    try:
        tree = ElementTree.parse(path)
    except (OSError, ElementTree.ParseError):
        return None
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites and root.tag != "testsuites":
        return None
    tests = failures = errors = 0
    for suite in suites:
        tests += _int_attr(suite, "tests")
        failures += _int_attr(suite, "failures")
        errors += _int_attr(suite, "errors")
    if tests == 0 and suites:
        tests = sum(1 for _ in root.iter("testcase"))
        failures = sum(1 for _ in root.iter("failure"))
        errors = sum(1 for _ in root.iter("error"))
    return tests, failures, errors


def _int_attr(node: ElementTree.Element, name: str) -> int:
    try:
        return int(node.get(name) or 0)
    except ValueError:
        return 0


# --- endpoint_status ---------------------------------------------------------------------------


def _grade_endpoint(claim: OutcomeClaim, policy: Policy) -> OutcomeVerdict:
    detail, evidence = claim.detail, claim.evidence or {}
    url = str(detail.get("url") or "")
    needed = _needed("endpoint_status")
    try:
        want = int(detail.get("status", 200))
    except (TypeError, ValueError):
        return OutcomeVerdict(Honesty.NOT_OBSERVED, "claimed status is not an integer",
                              needed=needed)
    if not url:
        return OutcomeVerdict(Honesty.NOT_OBSERVED, "no url in the claim", needed=needed)
    if policy.run:
        if not policy.host_allowed(url):
            return OutcomeVerdict(Honesty.NOT_OBSERVED,
                                  f"refused to probe {url!r}: host not allowlisted "
                                  f"(local hosts only unless [weft.honesty] allow_hosts adds it)",
                                  needed=needed)
        got = _probe(url, str(detail.get("method") or "GET"), min(policy.timeout, 30))
        if got is None:
            return OutcomeVerdict(Honesty.NOT_OBSERVED, f"could not connect to {url}",
                                  needed=needed)
        if got == want:
            return OutcomeVerdict(Honesty.PROVEN, f"probed {url}: HTTP {got}",
                                  observed={"status": got, "url": url})
        return OutcomeVerdict(Honesty.CONTRADICTED, f"probed {url}: HTTP {got}, claimed {want}",
                              observed={"status": got, "url": url})
    if "observed_status" in evidence or "status" in evidence:
        try:
            got = int(evidence.get("observed_status", evidence.get("status")) or 0)
        except (TypeError, ValueError):
            return OutcomeVerdict(Honesty.NOT_OBSERVED, "observed_status is not an integer",
                                  needed=needed)
        if got == want:
            return OutcomeVerdict(Honesty.PLAUSIBLE,
                                  f"self-reported HTTP {got}; weft did not probe {url}")
        return OutcomeVerdict(Honesty.CONTRADICTED,
                              f"self-reported HTTP {got} but the claim says {want}",
                              observed={"status": got})
    return OutcomeVerdict(Honesty.NOT_OBSERVED, f"no probe of {url} supplied", needed=needed)


def _probe(url: str, method: str, timeout: int) -> int | None:
    req = urllib.request.Request(url, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - local only
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return None


# --- bug_fixed -----------------------------------------------------------------------------


def _grade_bug(claim: OutcomeClaim, policy: Policy) -> OutcomeVerdict:
    detail, evidence = claim.detail, claim.evidence or {}
    signature = str(detail.get("signature") or evidence.get("signature") or "").strip()
    command = str(detail.get("command") or evidence.get("command") or "").strip()
    needed = _needed("bug_fixed")
    if not signature:
        return OutcomeVerdict(Honesty.NOT_OBSERVED, "no failure signature in the claim",
                              needed=needed)
    if policy.run and command:
        if not policy.command_allowed(command):
            return OutcomeVerdict(Honesty.NOT_OBSERVED,
                                  f"refused to re-run {command!r}: not an allowlisted command",
                                  needed=needed)
        ran = _run(command, policy, str(detail.get("cwd") or ""))
        if ran is None:
            return OutcomeVerdict(Honesty.NOT_OBSERVED, f"re-running {command!r} timed out or "
                                                        f"could not start", needed=needed)
        code, output = ran
        if signature in output:
            return OutcomeVerdict(Honesty.CONTRADICTED,
                                  f"re-ran {command!r}: the signature is still present",
                                  observed={"exit_code": code, "signature_present": True})
        if code == 0:
            return OutcomeVerdict(Honesty.PROVEN, f"re-ran {command!r}: exit 0 and the "
                                                  f"signature is absent",
                                  observed={"exit_code": 0, "signature_present": False})
        return OutcomeVerdict(Honesty.PLAUSIBLE,
                              f"re-ran {command!r}: signature absent but exit code {code}",
                              observed={"exit_code": code, "output_tail": _tail(output)})
    before, after = str(evidence.get("before") or ""), str(evidence.get("after") or "")
    if before or after:
        if signature in after:
            return OutcomeVerdict(Honesty.CONTRADICTED, "the signature is still in the 'after' "
                                                        "output", observed={"signature_present":
                                                                            True})
        if signature not in before:
            return OutcomeVerdict(Honesty.NOT_OBSERVED,
                                  "the signature never appears in the 'before' output, so the "
                                  "bug was not observed", needed=needed)
        return OutcomeVerdict(Honesty.PLAUSIBLE,
                              "signature present before and absent after, per supplied logs; "
                              "weft did not observe the runs")
    return OutcomeVerdict(Honesty.NOT_OBSERVED, "no evidence supplied for bug_fixed",
                          needed=needed)


# --- running things ---------------------------------------------------------------------------


def _run(command: str, policy: Policy, cwd: str = "") -> tuple[int, str] | None:
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    workdir = policy.repo_root or None
    if cwd:
        workdir = cwd if os.path.isabs(cwd) else os.path.join(workdir or ".", cwd)
    try:
        proc = subprocess.run(argv, cwd=workdir, capture_output=True, text=True,
                              timeout=policy.timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _tail(output: str, n: int = 300) -> str:
    text = " ".join(output.split())
    return text[-n:] if len(text) > n else text


# --- gate adapter ---------------------------------------------------------------------------


_LEVELS = {
    Honesty.PROVEN: Level.ACCEPT,
    Honesty.PLAUSIBLE: Level.REVIEW,
    Honesty.NOT_OBSERVED: Level.REVIEW,
    Honesty.CONTRADICTED: Level.REJECT,
}


def check(claim: Claim, repo_root: str, config: Config | None, run: bool = False) -> Finding:
    """Gate adapter: grade an outcome claim and express it as a Finding.

    PROVEN -> ACCEPT, PLAUSIBLE/NOT_OBSERVED -> REVIEW, CONTRADICTED -> REJECT
    (a soft claim caps at REVIEW as always).
    """
    evidence = claim.attrs.get("evidence")
    detail = {k: v for k, v in claim.attrs.items() if k != "evidence"}
    outcome = OutcomeClaim(kind=claim.kind, detail=detail,
                           evidence=dict(evidence) if isinstance(evidence, dict) else None)
    verdict = grade(outcome, Policy.from_config(config, repo_root, run))
    reason = f"{verdict.verdict.value}: {verdict.reason}"
    if verdict.verdict is Honesty.NOT_OBSERVED and verdict.needed:
        reason += f" (to settle it: {verdict.needed})"
    attrs = {**claim.attrs, "honesty": verdict.verdict.value, "needed": verdict.needed}
    if verdict.observed:
        attrs["observed"] = dict(verdict.observed)
    graded = Claim(claim.kind, claim.subject, claim.location, attrs, claim.hard, claim.source)
    return Finding(graded, _LEVELS[verdict.verdict], reason, "honesty").capped()


def allowed_commands(extra: Iterable[str] = ()) -> tuple[str, ...]:
    return tuple(DEFAULT_ALLOWED_COMMANDS) + tuple(extra)
