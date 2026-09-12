"""The honesty gate: never PROVEN without a machine-checkable signal."""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading

from tests.conftest import write
from weft.cli import main as cli_main
from weft.gate import Session, claims_from_json
from weft.honesty import Honesty, OutcomeClaim, Policy, grade
from weft.mcp_server import call_tool
from weft.types import Level

PY = sys.executable


def _policy(run: bool = False, **kw) -> Policy:
    return Policy(run=run, allow_commands=(*Policy().allow_commands, PY), timeout=60, **kw)


# --- tests_pass ------------------------------------------------------------------------------


def test_no_evidence_is_not_observed_never_proven():
    for kind in ("tests_pass", "endpoint_status", "bug_fixed", "made_up"):
        v = grade(
            OutcomeClaim(
                kind, {"command": "pytest", "url": "http://localhost:1/", "signature": "boom"}
            )
        )
        assert v.verdict is Honesty.NOT_OBSERVED and v.verdict is not Honesty.PROVEN
        assert v.needed


def test_self_reported_exit_code_is_only_plausible():
    v = grade(OutcomeClaim("tests_pass", {"command": "pytest -q"}, {"exit_code": 0}))
    assert v.verdict is Honesty.PLAUSIBLE
    v = grade(OutcomeClaim("tests_pass", {"command": "pytest -q"}, {"exit_code": 1}))
    assert v.verdict is Honesty.CONTRADICTED
    v = grade(OutcomeClaim("tests_pass", {}, {"output": "== 12 passed in 0.3s =="}))
    assert v.verdict is Honesty.PLAUSIBLE
    v = grade(OutcomeClaim("tests_pass", {}, {"output": "== 1 failed, 11 passed =="}))
    assert v.verdict is Honesty.CONTRADICTED


def test_junit_report_can_prove_or_contradict(tmp_path):
    good = write(
        str(tmp_path),
        "good.xml",
        '<testsuites><testsuite tests="3" failures="0" errors="0"/></testsuites>',
    )
    bad = write(
        str(tmp_path),
        "bad.xml",
        '<testsuite tests="3" failures="1" errors="0"><testcase name="a"/></testsuite>',
    )
    empty = write(str(tmp_path), "empty.xml", '<testsuite tests="0"/>')
    assert grade(OutcomeClaim("tests_pass", {"report": good})).verdict is Honesty.PROVEN
    assert grade(OutcomeClaim("tests_pass", {}, {"junit": bad})).verdict is Honesty.CONTRADICTED
    assert grade(OutcomeClaim("tests_pass", {"report": empty})).verdict is Honesty.NOT_OBSERVED
    v = grade(OutcomeClaim("tests_pass", {"report": "nope.xml"}), Policy(repo_root=str(tmp_path)))
    assert v.verdict is Honesty.NOT_OBSERVED
    write(str(tmp_path), "notxml.xml", "hello")
    assert (
        grade(OutcomeClaim("tests_pass", {"report": str(tmp_path / "notxml.xml")})).verdict
        is Honesty.NOT_OBSERVED
    )


def test_rerun_proves_or_contradicts_only_when_allowed(tmp_path):
    ok = f'{PY} -c "import sys; sys.exit(0)"'
    fail = f"{PY} -c \"import sys; print('nope'); sys.exit(3)\""
    assert (
        grade(OutcomeClaim("tests_pass", {"command": ok}), _policy(run=True)).verdict
        is Honesty.PROVEN
    )
    v = grade(OutcomeClaim("tests_pass", {"command": fail}), _policy(run=True))
    assert v.verdict is Honesty.CONTRADICTED and v.observed["exit_code"] == 3
    assert "nope" in v.observed["output_tail"]
    assert v.reason == f"re-ran {fail!r}: exit code 3"  # the reason carries no volatile output
    # run=False: never executed, never proven.
    assert (
        grade(OutcomeClaim("tests_pass", {"command": ok}), _policy(run=False)).verdict
        is Honesty.NOT_OBSERVED
    )
    # A command outside the allowlist is refused and not executed.
    marker = tmp_path / "ran.txt"
    sneaky = f"{PY} -c \"open(r'{marker}', 'w').write('x')\""
    v = grade(OutcomeClaim("tests_pass", {"command": sneaky}), Policy(run=True))
    assert v.verdict is Honesty.NOT_OBSERVED and "allowlisted" in v.reason
    assert not marker.exists()
    # A refused re-run still grades whatever evidence was supplied.
    v = grade(OutcomeClaim("tests_pass", {"command": sneaky}, {"exit_code": 1}), Policy(run=True))
    assert v.verdict is Honesty.CONTRADICTED and "allowlisted" in v.reason
    assert not marker.exists()
    assert Policy().command_allowed("pytest -q tests/") and Policy().command_allowed("npm test")
    assert not Policy().command_allowed("pytest_evil") and not Policy().command_allowed("rm -rf /")


# --- endpoint_status --------------------------------------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(204 if self.path == "/ok" else 404)
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence
        return


def test_endpoint_probe_and_self_report():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{port}/ok"
        assert (
            grade(
                OutcomeClaim("endpoint_status", {"url": url, "status": 204}), Policy(run=True)
            ).verdict
            is Honesty.PROVEN
        )
        v = grade(OutcomeClaim("endpoint_status", {"url": url, "status": 200}), Policy(run=True))
        assert v.verdict is Honesty.CONTRADICTED and v.observed["status"] == 204
        assert (
            grade(
                OutcomeClaim(
                    "endpoint_status", {"url": f"http://127.0.0.1:{port}/x", "status": 404}
                ),
                Policy(run=True),
            ).verdict
            is Honesty.PROVEN
        )
    finally:
        server.shutdown()
        server.server_close()
    # Without run=True nothing is probed; self-reports are plausible at best.
    v = grade(OutcomeClaim("endpoint_status", {"url": url, "status": 204}))
    assert v.verdict is Honesty.NOT_OBSERVED
    v = grade(
        OutcomeClaim("endpoint_status", {"url": url, "status": 204}, {"observed_status": 204})
    )
    assert v.verdict is Honesty.PLAUSIBLE
    v = grade(
        OutcomeClaim("endpoint_status", {"url": url, "status": 204}, {"observed_status": 500})
    )
    assert v.verdict is Honesty.CONTRADICTED
    # Non-local hosts are never probed on the default policy.
    v = grade(
        OutcomeClaim("endpoint_status", {"url": "https://example.com/", "status": 200}),
        Policy(run=True),
    )
    assert v.verdict is Honesty.NOT_OBSERVED and "allowlisted" in v.reason
    # A closed local port is a failed observation, not a contradiction.
    v = grade(
        OutcomeClaim("endpoint_status", {"url": "http://127.0.0.1:1/", "status": 200}),
        Policy(run=True),
    )
    assert v.verdict is Honesty.NOT_OBSERVED


# --- bug_fixed --------------------------------------------------------------------------------


def test_bug_fixed_requires_the_observed_signature():
    sig = "TypeError: cannot add int and str"
    v = grade(
        OutcomeClaim(
            "bug_fixed",
            {"signature": sig},
            {"before": f"Traceback...\n{sig}\n", "after": "all good\n"},
        )
    )
    assert v.verdict is Honesty.PLAUSIBLE
    v = grade(
        OutcomeClaim(
            "bug_fixed", {"signature": sig}, {"before": f"{sig}\n", "after": f"still: {sig}\n"}
        )
    )
    assert v.verdict is Honesty.CONTRADICTED
    v = grade(
        OutcomeClaim(
            "bug_fixed", {"signature": sig}, {"before": "a different error\n", "after": "ok\n"}
        )
    )
    assert v.verdict is Honesty.NOT_OBSERVED
    assert grade(OutcomeClaim("bug_fixed", {})).verdict is Honesty.NOT_OBSERVED
    fixed = f"{PY} -c \"print('fine')\""
    still = f"{PY} -c \"print('{sig}')\""
    assert (
        grade(
            OutcomeClaim("bug_fixed", {"signature": sig, "command": fixed}), _policy(run=True)
        ).verdict
        is Honesty.PROVEN
    )
    assert (
        grade(
            OutcomeClaim("bug_fixed", {"signature": sig, "command": still}), _policy(run=True)
        ).verdict
        is Honesty.CONTRADICTED
    )
    other = f'{PY} -c "import sys; sys.exit(2)"'
    assert (
        grade(
            OutcomeClaim("bug_fixed", {"signature": sig, "command": other}), _policy(run=True)
        ).verdict
        is Honesty.PLAUSIBLE
    )


# --- gate wiring ------------------------------------------------------------------------------


def test_claim_mode_wiring_and_surfaces(tmp_path, capsys):
    root = str(tmp_path / "repo")
    write(root, ".env.example", "A=\n")
    write(
        root,
        "weft.toml",
        # A TOML literal string ('...') keeps Windows backslashes intact.
        f"[weft]\noracles = ['env_vars']\n[weft.honesty]\nallow_commands = ['{PY}']\n",
    )
    ok = f'{PY} -c "import sys; sys.exit(0)"'
    # "custom-runner" is not allowlisted, so run=True must not execute it; its
    # self-reported exit code is graded instead.
    claims = [
        {"kind": "tests_pass", "command": ok},
        {"kind": "tests_pass", "command": "custom-runner", "evidence": {"exit_code": 1}},
        {"kind": "env_var", "subject": "A"},
    ]
    store = str(tmp_path / "i.sqlite")
    with Session(root, store_path=store) as s:
        res = s.check_claims(claims_from_json(claims))
        by = {f.claim.subject: f for f in res.findings}
        assert by[ok].level is Level.REVIEW and by[ok].claim.attrs["honesty"] == "not_observed"
        assert by["custom-runner"].level is Level.REJECT
        assert by["A"].level is Level.ACCEPT
        res = s.check_claims(claims_from_json(claims), run=True)
        by = {f.claim.subject: f for f in res.findings}
        assert by[ok].level is Level.ACCEPT and by[ok].claim.attrs["honesty"] == "proven"
        assert by[ok].claim.attrs["observed"]["exit_code"] == 0
        assert by["custom-runner"].level is Level.REJECT
        assert "allowlisted" in by["custom-runner"].reason
        # Deterministic: same input, same output.
        assert s.check_claims(claims_from_json(claims), run=True).to_dict() == res.to_dict()
    # CLI --run and MCP run=true agree.
    code = cli_main(
        ["--repo", root, "--store", store, "--format", "json", "claim", "--run", json.dumps(claims)]
    )
    via_cli = json.loads(capsys.readouterr().out)
    via_mcp = call_tool(
        "check_claim", {"repo": root, "claims": claims, "run": True}, store_path=store
    )
    assert via_cli == via_mcp and code == 1  # the contradicted claim blocks
    prose = claims_from_json(
        [
            {
                "kind": "tests_pass",
                "command": "custom-runner",
                "evidence": {"exit_code": 1},
                "source": "prose",
            }
        ]
    )
    with Session(root, store_path=store) as s:
        assert s.check_claims(prose).verdict is Level.REVIEW  # prose never rejects
    assert os.path.exists(store)
