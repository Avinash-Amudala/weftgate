"""Public memory must retain Mnemo's checks without needing a second install."""

import hashlib
import json

import pytest

from tests.conftest import write
from weftgate import privacy, recall
from weftgate.eval.fixture import write_fixture
from weftgate.gate import Session


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "repo")
    write_fixture(root)
    return root


def test_explicit_false_claim_is_not_stored_and_has_suggestion(repo):
    with Session(repo) as session:
        result = recall.remember(
            session, "Database", "Use the configured database.", claims={"env": ["DATABSE_URL"]}
        )
        assert result["stored"] is False and result["verdict"] == "reject"
        assert "DATABASE_URL" in result["anchors"][0]["did_you_mean"]
        assert recall.recall(session)["matches"] == 0


def test_prose_is_not_promoted_to_a_hard_claim(repo):
    with Session(repo) as session:
        result = recall.remember(session, "Investigate", "Is DATABSE_URL the right name?")
        assert result["stored"] is True and result["state"] == "unverified"


def test_unknown_evidence_is_retained_for_review_instead_of_rejected(repo):
    with Session(repo) as session:
        session.oracles = {}
        result = recall.remember(
            session, "Database", "Use the configured database.", claims={"env": ["DATABASE_URL"]}
        )
        assert result["stored"] is True and result["verdict"] == "review"
        assert not recall.recall(session)["items"]
        assert recall.recall(session, include_stale=True)["items"][0]["state"] == "stale"


def test_import_contract_drift_keeps_original_evidence(repo):
    with Session(repo) as session:
        saved = recall.remember(
            session, "HTTP requests", "Use the declared client.", claims={"imports": ["requests"]}
        )
        assert saved["state"] == "anchored"
        original = session.store.db.execute("SELECT anchors FROM recall_notes").fetchone()[0]
        write(repo, "requirements.txt", "requests==9.9.9\nfastapi==0.115.0\nSQLAlchemy==2.0.0\n")
        for _ in range(2):
            assert recall.recall(session, "HTTP")["hidden_stale"] == 1
        assert (
            session.store.db.execute("SELECT anchors FROM recall_notes").fetchone()[0] == original
        )


def test_memory_claims_share_route_and_symbol_indexes(repo):
    with Session(repo) as session:
        good = recall.remember(
            session,
            "Order handler",
            "Review order behavior here.",
            claims={"routes": ["POST /api/orders"], "symbols": ["app/orders.py:create_order"]},
        )
        assert good["state"] == "anchored"
        found = recall.recall(session, "order")["items"][0]
        assert {s["kind"] for s in found["sources"]} == {"route", "symbol"}
        bad = recall.remember(
            session, "Broken route", "A declared route.", claims={"routes": ["POST /absent"]}
        )
        assert bad["stored"] is False


@pytest.mark.parametrize(
    "claims",
    [
        {"cli": ["rm -rf /tmp"]},
        {"env": "DATABASE_URL"},
        {"files": [1]},
        {"symbols": ["../outside.py:name"]},
    ],
)
def test_claim_input_validation_is_atomic(repo, claims):
    with Session(repo) as session:
        with pytest.raises(ValueError):
            recall.remember(session, "Bad input", "Do not save this.", claims=claims)
        assert recall.recall(session)["matches"] == 0


def test_secret_scrubbing_applies_before_storage_and_to_legacy_reads(repo):
    secret = "redaction-test-" + "x" * 24
    with Session(repo) as session:
        saved = recall.remember(session, "Header", "Authorization: " + "Bearer " + secret)
        assert saved["redactions"] == {"bearer": 1}
        body = session.store.db.execute("SELECT body FROM recall_notes").fetchone()[0]
        assert secret not in body
        session.store.db.execute("UPDATE recall_notes SET body=?", ("Bearer " + secret,))
        assert secret not in json.dumps(recall.recall(session))


def test_redaction_handles_quoted_values_and_is_idempotent():
    raw = 'PASSWORD="synthetic password with spaces"; url=https://user:dummy-password@example.test'
    clean, counts = privacy.scrub(raw)
    assert "synthetic" not in clean and "dummy-password" not in clean
    assert counts == {"secret_assignment": 1, "url_password": 1}
    assert privacy.scrub(clean) == (clean, {})
    assert privacy.scrub("Use the API_KEY environment variable.") == (
        "Use the API_KEY environment variable.",
        {},
    )


def test_unicode_search_and_empty_search_tokens_do_not_return_unrelated_notes(repo):
    with Session(repo) as session:
        recall.remember(session, "数据库", "Use the database carefully.")
        recall.remember(session, "Café", "Keep accented words searchable.")
        assert recall.recall(session, "数据库")["matches"] == 1
        assert recall.recall(session, "café")["matches"] == 1
        assert recall.recall(session, "???")["matches"] == 0


def test_existing_v02_note_identity_does_not_duplicate_after_upgrade(repo):
    from weftgate.payload import encode

    with Session(repo) as session:
        saved = recall.remember(session, "Existing note", "Keep it.", files=["app/orders.py"])
        previous_id = hashlib.sha256(
            encode(["Existing note", "Keep it.", "decision", ["app/orders.py"]]).encode()
        ).hexdigest()[:20]
        assert saved["id"] == previous_id
