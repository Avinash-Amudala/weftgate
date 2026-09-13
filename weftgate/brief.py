"""One task brief and explicit cross-agent handoffs over the shared notebook."""

from __future__ import annotations

from itertools import zip_longest
from typing import Any

from . import context, recall, workflow
from .gate import Session
from .payload import bounded, encode


class _TreeChanged(Exception):
    """Rollback a handoff whose summary no longer matches its checked tree."""


def _changed() -> dict[str, Any]:
    return {
        "operation": "handoff",
        "stored": False,
        "state": "changed_during_check",
        "blocking": False,
        "reason": "The tree changed; review the summary before saving.",
    }


def prepare(
    session: Session,
    query: str,
    *,
    references: list[str] | None = None,
    budget: int | None = None,
) -> dict[str, Any]:
    if references is not None and (
        not isinstance(references, list)
        or len(references) > 8
        or any(not isinstance(ref, str) or not 1 <= len(ref) <= 240 for ref in references)
    ):
        raise ValueError("references must be up to 8 nonempty source references")
    memories = recall.recall(session, query, limit=8, budget=16000)
    refs = list(dict.fromkeys(references or []))
    if not refs:
        refs = list(
            dict.fromkeys(
                source["reference"] for note in memories["items"] for source in note["sources"]
            )
        )[:4]
    if not refs and query.strip():
        refs = [query]
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    resolution = []
    context_omitted = 0
    for ref in refs:
        card = context.query(session, "card", ref, budget=16000)
        resolution.append({"reference": ref, "status": card["status"]})
        context_omitted += int(card["usage"]["omitted"])
        for item in card["items"]:
            key = encode(item)
            if key not in seen:
                seen.add(key)
                sources.append({"context": item})
    notes = [{"memory": note} for note in memories["items"]]
    # Interleave evidence and memory so neither consumes the entire small budget.
    items = [item for pair in zip_longest(notes, sources) for item in pair if item is not None]
    return bounded(
        items,
        {
            "operation": "brief",
            "query": query,
            "memory_matches": memories["matches"],
            "hidden_stale": memories["hidden_stale"],
            "resolution": resolution,
            "upstream_omitted": context_omitted + int(memories["usage"]["omitted"]),
            "trust": recall.TRUST,
            "next": "Read the cited source, edit, then run checkpoint with test evidence.",
            "coverage": "Saved notes and static relationships; application context is incomplete.",
        },
        budget,
    )


def handoff(
    session: Session,
    title: str,
    text: str,
    *,
    files: list[str] | None = None,
    claims: dict[str, list[str]] | None = None,
    note_id: str | None = None,
    run: bool = False,
    budget: int | None = None,
) -> dict[str, Any]:
    # Validate all inputs before any opt-in test execution or note write.
    bounded([], {}, budget)
    preview = recall._prepare(
        session, title, text, files=files, claims=claims, kind="handoff", note_id=note_id
    )
    if not preview["stored"]:
        return {"operation": "handoff", **preview}
    report = workflow.checkpoint(session, run=run, budget=16000)
    if not report["tree_unchanged"] or workflow.fingerprint(session) != report["tree_fingerprint"]:
        return _changed()
    evidence = {
        key: report[key]
        for key in (
            "state",
            "gate_verdict",
            "tests_observed",
            "tree_fingerprint",
            "tree_unchanged",
            "commit",
        )
    }
    try:
        with session.store.transaction():
            saved = recall.remember(
                session, title, text, files=files, claims=claims, kind="handoff", note_id=note_id
            )
            if not saved["stored"]:
                return {"operation": "handoff", **saved}
            if workflow.fingerprint(session) != report["tree_fingerprint"]:
                raise _TreeChanged
            session.store.db.execute(
                "INSERT INTO recall_handoffs VALUES(?,?)", (saved["id"], encode(evidence))
            )
            result = bounded(
                report["items"],
                {
                    "operation": "handoff",
                    "stored": True,
                    "id": saved["id"],
                    "state": report["state"],
                    "blocking": report["blocking"],
                    "evidence": evidence,
                    "redactions": saved["redactions"],
                    "trust": recall.TRUST,
                    "next": "Use brief in the next agent session. The summary is unverified prose.",
                },
                budget,
            )
    except _TreeChanged:
        return _changed()
    return result
