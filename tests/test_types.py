"""The shared vocabulary: verdict math and the soft-claim cap."""

import json

from weftgate.types import Claim, Finding, GateResult, Level, Location, worst


def _claim(subject: str = "X", hard: bool = True, source: str = "code", line: int = 1) -> Claim:
    loc = Location("f.py", line)
    return Claim(kind="k", subject=subject, location=loc, hard=hard, source=source)


def test_worst_ignores_unverifiable():
    assert worst([]) is Level.ACCEPT
    assert worst([Level.UNVERIFIABLE]) is Level.ACCEPT
    assert worst([Level.UNVERIFIABLE, Level.ACCEPT]) is Level.ACCEPT
    assert worst([Level.ACCEPT, Level.REVIEW]) is Level.REVIEW
    assert worst([Level.REVIEW, Level.REJECT, Level.UNVERIFIABLE]) is Level.REJECT


def test_soft_claim_can_never_reject():
    f = Finding(_claim(hard=False), Level.REJECT, "r", "o")
    assert f.capped().level is Level.REVIEW
    hard = Finding(_claim(hard=True), Level.REJECT, "r", "o")
    assert hard.capped().level is Level.REJECT


def test_prose_claims_are_forced_soft():
    c = _claim(source="prose", hard=True)
    assert c.hard is False
    result = GateResult.build([Finding(c, Level.REJECT, "r", "o")])
    assert result.verdict is Level.REVIEW


def test_gate_result_verdict_stats_and_order():
    findings = [
        Finding(_claim("b", line=5), Level.REVIEW, "r", "o"),
        Finding(_claim("a", line=2), Level.UNVERIFIABLE, "r", "o"),
        Finding(_claim("c", line=1), Level.ACCEPT, "r", "o"),
    ]
    res = GateResult.build(findings)
    assert res.verdict is Level.REVIEW
    assert [f.claim.subject for f in res.findings] == ["c", "a", "b"]
    assert res.stats["review"] == 1 and res.stats["unverifiable"] == 1
    assert res.stats["claims"] == 3
    # UNVERIFIABLE alone never raises the verdict.
    only = GateResult.build([findings[1]])
    assert only.verdict is Level.ACCEPT


def test_to_dict_is_json_serialisable_and_stable():
    c = Claim("k", "s", Location("f.py", 3, 4), attrs={"z": {1, 2}, "a": ("x",)})
    res = GateResult.build([Finding(c, Level.REJECT, "why", "o", ("s1",))])
    d = res.to_dict()
    text = json.dumps(d, sort_keys=True)
    assert json.loads(text) == d
    assert d["findings"][0]["attrs"] == {"a": ["x"], "z": [1, 2]}
    assert d["findings"][0]["suggestions"] == ["s1"]
    assert str(Level.REJECT) == "reject"
