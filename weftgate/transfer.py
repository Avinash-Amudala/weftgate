"""Explicit, local memory transfer. No transcript discovery or legacy imports.

Mnemo databases are opened read-only. Original grounding hashes are preserved;
importing an old note never grants it fresh evidence. All writes share the public
notebook and happen in a single transaction after the source has been read.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import memory, privacy, recall
from .gate import Session
from .payload import bounded, encode

FORMAT = "weftgate.memory"
MAX_JSON = 5 * 1024 * 1024


def _page(limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be an integer from 1 to 500")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1_000_000:
        raise ValueError("offset must be an integer from 0 to 1000000")


def _json(value: Any, fallback: Any) -> Any:
    return json.loads(value) if isinstance(value, str) and value else fallback


def _read_source(path: str, limit: int, offset: int) -> tuple[list[Any], str, bool, bool]:
    if not isinstance(path, str) or not path:
        raise ValueError("source must name one explicit local memory file")
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("source must be a regular file")
    with source.open("rb") as stream:
        signature = stream.read(16)
        if signature != b"SQLite format 3\0":
            stream.seek(0)
            raw = stream.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise ValueError("memory export exceeds the 5 MiB input limit; use smaller pages")
            data = json.loads(raw)
            if (
                not isinstance(data, dict)
                or data.get("format") != FORMAT
                or type(data.get("version")) is not int
                or data.get("version") != 1
                or not isinstance(data.get("items"), list)
            ):
                raise ValueError("expected a version 1 Weftgate memory export or Mnemo database")
            items = data["items"]
            records = items[offset : offset + limit]
            return records, "weftgate", offset + limit < len(items), bool(data.get("has_more"))
    # trusted_schema prevents schema-defined functions from running. No extension,
    # plugin, embedding endpoint or legacy Python code is loaded from this source.
    conn = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        ticks = 0

        def progress() -> int:
            nonlocal ticks
            ticks += 1
            return int(ticks > 2000)

        conn.set_progress_handler(progress, 1000)
        table = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='memory' AND type='table'"
        ).fetchone()
        if not table or not str(table[0]).lstrip().upper().startswith("CREATE TABLE"):
            raise ValueError("source is not a supported Mnemo memory table")
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(memory)")}
        if not {"id", "title", "body", "kind"} <= columns:
            raise ValueError("Mnemo memory table is missing required columns")
        anchors = "substr(anchors,1,64001)" if "anchors" in columns else "NULL"
        created = "created_at" if "created_at" in columns else "0"
        claims = "substr(claims,1,16001)" if "claims" in columns else "NULL"
        rows = conn.execute(
            "SELECT substr(id,1,201),substr(title,1,121),substr(body,1,4001),"
            f"substr(kind,1,30),{created},{anchors},{claims} "
            "FROM memory ORDER BY id LIMIT ? OFFSET ?",
            (limit + 1, offset),
        ).fetchall()
        return (
            [
                {
                    "note": dict(
                        zip(
                            ("id", "title", "text", "kind", "created", "anchors", "claims"),
                            row,
                            strict=True,
                        )
                    )
                }
                for row in rows[:limit]
            ],
            "mnemo",
            len(rows) > limit,
            False,
        )
    finally:
        conn.close()


def _prepare(session: Session, raw: Any, origin: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("note"), dict):
        raise ValueError("record must contain a note object")
    note = raw["note"]
    ident, title, text = note.get("id"), note.get("title"), note.get("text")
    if not isinstance(ident, str) or not 1 <= len(ident) <= 200:
        raise ValueError("source note ID must contain 1 to 200 characters")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        raise ValueError("source title must contain 1 to 120 characters")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise ValueError("source body must contain 1 to 4000 characters")
    kind = note.get("kind", "note")
    if kind == "episode":
        raise ValueError("raw transcript episodes are excluded; export reviewed memories instead")
    if kind not in recall.KINDS:
        raise ValueError("unsupported memory kind")
    created = note.get("created", 0)
    if (
        isinstance(created, bool)
        or not isinstance(created, int | float)
        or not 0 <= created <= 10**12
        or not math.isfinite(created)
    ):
        raise ValueError("invalid creation timestamp")
    created = int(created)
    anchors = note.get("anchors")
    if isinstance(anchors, str):
        anchors = _json(anchors, [])
    if anchors is None:
        anchors = []
    if not isinstance(anchors, list) or len(anchors) > 100:
        raise ValueError("anchors must be a list of at most 100 items")
    cleaned = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            raise ValueError("each anchor must be an object")
        kind_a, locator = anchor.get("kind"), anchor.get("locator")
        if kind_a not in memory.ANCHOR_KINDS or not isinstance(locator, str):
            raise ValueError("unsupported source anchor")
        claim_kind = {
            "file": "files",
            "env": "env",
            "route": "routes",
            "import": "imports",
            "symbol": "symbols",
        }[kind_a]
        recall.validate_claims(session, {claim_kind: [locator]})
        original_hash = anchor.get("content_hash")
        if original_hash is not None and (
            not isinstance(original_hash, str)
            or (original_hash and not re.fullmatch(r"sha256:[0-9a-f]{64}", original_hash))
        ):
            raise ValueError("invalid original source hash")
        commit = anchor.get("commit")
        if commit is not None and (
            not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{7,64}", commit)
        ):
            raise ValueError("invalid original commit identifier")
        cleaned.append(
            {"kind": kind_a, "locator": locator, "content_hash": original_hash, "commit": commit}
        )
    # Preserve lack of evidence in older stores. Existence now must not turn an
    # old, unanchored file claim into a newly verified memory during migration.
    legacy_claims = note.get("claims", {})
    if legacy_claims is None:
        legacy_claims = {}
    if isinstance(legacy_claims, str):
        legacy_claims = _json(legacy_claims, {})
    if not isinstance(legacy_claims, dict):
        raise ValueError("legacy claims must be a JSON object")
    if isinstance(legacy_claims, dict):
        claims = recall.validate_claims(
            session, {k: v for k, v in legacy_claims.items() if k in recall.CLAIM_KINDS}
        )
        kind_map = {
            "files": "file",
            "env": "env",
            "routes": "route",
            "imports": "import",
            "symbols": "symbol",
        }
        known = {(a["kind"], a["locator"]) for a in cleaned}
        for key, values in claims.items():
            for value in values:
                if (kind_map[key], value) not in known:
                    cleaned.append({"kind": kind_map[key], "locator": value, "content_hash": None})
                    known.add((kind_map[key], value))
    if len(cleaned) > 100:
        raise ValueError("combined source claims exceed 100 anchors")
    title, title_counts = privacy.scrub(title.strip())
    text, text_counts = privacy.scrub(text.strip())
    ident = (
        "mnemo-" + hashlib.sha256(ident.encode()).hexdigest()[:24] if origin == "mnemo" else ident
    )
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", ident):
        raise ValueError("invalid destination note ID")
    state, _ = recall.state_of(session, cleaned)
    return {
        "id": ident,
        "title": title,
        "text": text,
        "kind": kind,
        "created": created,
        "anchors": cleaned,
        "state": state,
        "redactions": sum(title_counts.values()) + sum(text_counts.values()),
    }


def import_notes(
    session: Session,
    source: str,
    *,
    apply: bool = False,
    limit: int = 100,
    offset: int = 0,
    budget: int | None = None,
) -> dict[str, Any]:
    _page(limit, offset)
    if not isinstance(apply, bool):
        raise ValueError("apply must be a boolean")
    try:
        rows, origin, has_more, source_export_has_more = _read_source(source, limit, offset)
    except (sqlite3.Error, RecursionError) as exc:
        raise ValueError("source is corrupt, too complex or unsupported") from exc
    session.sync()
    recall._init(session)
    ready: list[dict[str, Any]] = []
    results = []
    existing = duplicates = rejected = 0
    seen: set[str] = set()
    for index, row in enumerate(rows, start=offset):
        try:
            note = _prepare(session, row, origin)
        except (ValueError, TypeError, KeyError) as exc:
            rejected += 1
            results.append({"record": index, "action": "skipped", "reason": str(exc)})
            continue
        if note["id"] in seen:
            duplicates += 1
            continue
        seen.add(note["id"])
        old = session.store.db.execute(
            "SELECT id FROM recall_notes WHERE id=?", (note["id"],)
        ).fetchone()
        if old:
            existing += 1
            results.append({"id": note["id"], "action": "kept_existing"})
            continue
        ready.append(note)
        results.append(
            {"note": {k: note[k] for k in ("id", "title", "text", "kind", "state", "redactions")}}
        )
    report = bounded(
        results,
        {
            "operation": "memory_import",
            "origin": origin,
            "applied": apply,
            "imported": len(ready) if apply else 0,
            "eligible": len(ready),
            "kept_existing": existing,
            "duplicate_ids": duplicates,
            "skipped": rejected,
            "has_more": has_more,
            "next_offset": offset + len(rows),
            "trust": recall.TRUST,
            "source_opened_read_only": True,
            "source_export_has_more": source_export_has_more,
        },
        budget,
    )
    if apply:
        with session.store.transaction():
            for note in ready:
                session.store.db.execute(
                    "INSERT INTO recall_notes VALUES(?,?,?,?,?,?,?)",
                    (
                        note["id"],
                        note["title"],
                        note["text"],
                        note["kind"],
                        note["created"],
                        encode(note["anchors"]),
                        note["state"],
                    ),
                )
    return report


def export_notes(
    session: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    budget: int | None = None,
) -> dict[str, Any]:
    _page(limit, offset)
    recall._init(session)
    session.sync()
    rows = session.store.db.execute(
        "SELECT id,title,body,kind,created,anchors FROM recall_notes ORDER BY id LIMIT ? OFFSET ?",
        (limit + 1, offset),
    ).fetchall()
    items = []
    for ident, title, body, kind, created, anchors in rows[:limit]:
        items.append(
            {
                "note": {
                    "id": ident,
                    "title": privacy.scrub(title)[0],
                    "text": privacy.scrub(body)[0],
                    "kind": kind,
                    "created": created,
                    "anchors": json.loads(anchors),
                }
            }
        )
    meta = {
        "operation": "memory_export",
        "format": FORMAT,
        "version": 1,
        "has_more": False,
        "next_offset": offset,
        "trust": recall.TRUST,
    }
    budget = 16000 if budget is None else budget
    selected: list[dict[str, Any]] = []
    for item in items:
        count = len(selected) + 1
        candidate_meta = {**meta, "has_more": len(rows) > count, "next_offset": offset + count}
        attempt = bounded(selected + [item], candidate_meta, budget)
        if attempt["usage"]["omitted"]:
            break
        selected.append(item)
    if items and not selected:
        raise ValueError("increase budget to fit the next note without truncation")
    meta.update(has_more=len(rows) > len(selected), next_offset=offset + len(selected))
    return bounded(selected, meta, budget)
