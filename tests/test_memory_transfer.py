"""Memory migration keeps the source intact and never manufactures fresh evidence."""

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from tests.conftest import write
from weftgate import memory, recall, transfer
from weftgate.cli import main
from weftgate.eval.fixture import write_fixture
from weftgate.gate import Session
from weftgate.mcp_server import call_tool
from weftgate.payload import encode


@pytest.fixture
def repo(tmp_path):
    root = str(tmp_path / "repo")
    write_fixture(root)
    return root


def source_db(path, notes):
    with closing(sqlite3.connect(path)) as db:
        db.execute(
            "CREATE TABLE memory(id TEXT, title TEXT, body TEXT, kind TEXT, "
            "created_at INTEGER, anchors TEXT, claims TEXT)"
        )
        db.executemany("INSERT INTO memory VALUES(?,?,?,?,?,?,?)", notes)
        db.commit()


def test_mnemo_preview_then_import_is_read_only_idempotent_and_redacted(repo, tmp_path):
    source = tmp_path / "mnemo.sqlite"
    secret = "synthetic-test-" + "x" * 24
    source_db(source, [("one", "API usage", "Bearer " + secret, "decision", 1234.5, "[]", "{}")])
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    with Session(repo) as session:
        preview = transfer.import_notes(session, str(source))
        assert preview["eligible"] == 1 and preview["imported"] == 0
        assert recall.recall(session)["matches"] == 0
        assert secret not in encode(preview)
        applied = transfer.import_notes(session, str(source), apply=True)
        assert applied["imported"] == 1
        assert transfer.import_notes(session, str(source), apply=True)["kept_existing"] == 1
        notes = recall.recall(session)
        assert notes["matches"] == 1 and notes["items"][0]["state"] == "unverified"
        assert secret not in encode(notes)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_original_hashes_and_missing_evidence_are_preserved(repo, tmp_path):
    source = tmp_path / "mnemo.sqlite"
    with Session(repo) as session:
        anchors = memory.anchor(session, claims={"files": ["app/orders.py"]})["anchors"]
        source_db(
            source,
            [
                (
                    "stale",
                    "Order decision",
                    "Keep the old decision for review.",
                    "decision",
                    0,
                    encode(anchors),
                    "{}",
                ),
                (
                    "unanchored",
                    "Old file",
                    "Historical claim without evidence.",
                    "note",
                    0,
                    "[]",
                    '{"files":["app/tasks.py"]}',
                ),
            ],
        )
        write(repo, "app/orders.py", "def changed(): pass\n")
        report = transfer.import_notes(session, str(source), apply=True)
        assert report["imported"] == 2
        for _ in range(2):
            result = recall.recall(session)
            assert result["matches"] == 0 and result["hidden_stale"] == 2
        checked = recall.recall(session, include_stale=True)
        assert all(item["state"] == "stale" for item in checked["items"])
        raw = session.store.db.execute(
            "SELECT anchors FROM recall_notes WHERE title='Order decision'"
        ).fetchone()[0]
        assert json.loads(raw)[0]["content_hash"] == anchors[0]["content_hash"]


def test_legacy_schema_without_claims_preserves_preferences_and_todos(repo, tmp_path):
    source = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE memory(id TEXT, title TEXT, body TEXT, kind TEXT)")
        db.executemany(
            "INSERT INTO memory VALUES(?,?,?,?)",
            [(kind, kind, "Keep this reviewed note.", kind) for kind in ("preference", "todo")],
        )
        db.commit()
    with Session(repo) as session:
        assert transfer.import_notes(session, str(source), apply=True)["imported"] == 2
        notes = recall.recall(session)["items"]
        assert {note["kind"] for note in notes} == {"preference", "todo"}
        assert all(note["state"] == "unverified" for note in notes)


def test_malformed_rows_and_raw_transcripts_are_reported_without_loading_plugins(repo, tmp_path):
    source = tmp_path / "mnemo.sqlite"
    source_db(
        source,
        [
            ("episode", "Chat", "A complete raw transcript.", "episode", 0, "[]", "{}"),
            ("bad", "Bad path", "Outside source.", "note", 0, "[]", '{"files":["../secret.py"]}'),
            (
                "good",
                "Safe decision",
                "Only this reviewed note transfers.",
                "decision",
                0,
                "[]",
                "{}",
            ),
        ],
    )
    with Session(repo) as session:
        report = transfer.import_notes(session, str(source), apply=True)
        assert report["imported"] == 1 and report["skipped"] == 2
        assert recall.recall(session)["items"][0]["title"] == "Safe decision"


def test_import_transaction_rolls_back_the_entire_batch_on_write_failure(repo, tmp_path):
    source = tmp_path / "mnemo.sqlite"
    source_db(
        source,
        [
            (str(i), title, "A reviewed note.", "note", 0, "[]", "{}")
            for i, title in enumerate(["first", "second"])
        ],
    )
    with Session(repo) as session:
        recall._init(session)
        session.store.db.execute(
            "CREATE TRIGGER fail_note BEFORE INSERT ON recall_notes WHEN NEW.title='second' "
            "BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            transfer.import_notes(session, str(source), apply=True)
        assert session.store.db.execute("SELECT COUNT(*) FROM recall_notes").fetchone()[0] == 0


def test_export_pages_round_trip_without_skipping_notes(repo, tmp_path):
    with Session(repo, store_path=str(tmp_path / "original.sqlite")) as original:
        for i in range(13):
            recall.remember(original, f"Note {i}", "Useful memory. " * 40, files=["app/tasks.py"])
        expected = original.store.db.execute("SELECT COUNT(*) FROM recall_notes").fetchone()[0]
        offset = 0
        with Session(repo, store_path=str(tmp_path / "copy.sqlite")) as copied:
            for page in range(20):
                exported = transfer.export_notes(original, offset=offset, budget=1100)
                assert exported["usage"]["bytes"] == len(encode(exported).encode()) <= 4400
                assert exported["items"] and exported["usage"]["omitted"] == 0
                path = tmp_path / f"page-{page}.json"
                path.write_text(encode(exported))
                transfer.import_notes(copied, str(path), apply=True)
                if not exported["has_more"]:
                    break
                assert exported["next_offset"] > offset
                offset = exported["next_offset"]
            assert recall.recall(copied, limit=50, budget=16000)["matches"] == expected


def test_portable_page_does_not_offer_an_infinite_local_cursor(repo, tmp_path):
    with Session(repo) as session:
        recall.remember(session, "Note", "A small decision.")
        exported = transfer.export_notes(session)
        exported["has_more"] = True
        path = tmp_path / "page.json"
        path.write_text(encode(exported))
        result = transfer.import_notes(session, str(path))
        assert result["source_export_has_more"] is True
        assert result["has_more"] is False


def test_source_views_are_not_accepted_as_memory_tables(repo, tmp_path):
    source = tmp_path / "invalid.sqlite"
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE VIEW memory AS SELECT 'secret' AS body")
    with Session(repo) as session, pytest.raises(ValueError, match="supported Mnemo"):
        transfer.import_notes(session, str(source))


def test_transfer_and_stats_have_cli_mcp_parity(repo, tmp_path, capsys):
    source = tmp_path / "portable.json"
    source.write_text(
        encode(
            {
                "format": transfer.FORMAT,
                "version": 1,
                "items": [
                    {
                        "note": {
                            "id": "portable",
                            "title": "Portable",
                            "text": "A useful note.",
                            "kind": "note",
                            "created": 0,
                            "anchors": [],
                        }
                    }
                ],
            }
        )
    )
    assert main(["--repo", repo, "memory", "import", str(source)]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli == call_tool("memory_import", {"source": str(source)}, repo)
    assert main(["--repo", repo, "memory", "import", str(source), "--apply"]) == 0
    capsys.readouterr()
    for cli_name, mcp_name in (("export", "memory_export"), ("stats", "memory_stats")):
        assert main(["--repo", repo, "memory", cli_name]) == 0
        cli = json.loads(capsys.readouterr().out)
        assert cli == call_tool(mcp_name, {}, repo)
