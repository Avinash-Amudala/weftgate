"""The honest token metric (docs/ADDENDUM section A6): a local ledger of every
blocking verdict the gate produced before code shipped. A hallucinated reference
that ships costs a full failed round trip (the attempt, the error, the correction),
so each avoided one is the number to lead with. Nothing here is a marketing
percentage: it is a count of concrete events on the user's own repos.

One JSON line per event under the cache directory (``WEFTGATE_LEDGER=0`` disables it).
Standard library only; never raises into the gate.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from .store import cache_dir
from .types import GateResult, Level

# A conservative estimate of what one shipped broken wire costs an agent loop: the
# failed attempt, the error output, and the corrective turn. Reported as an estimate.
ROUND_TRIP_TOKENS = 6_000


def enabled() -> bool:
    return os.environ.get("WEFTGATE_LEDGER", "1") not in ("0", "false", "no", "off")


def path() -> str:
    return os.path.join(cache_dir(), "ledger.jsonl")


def record(result: GateResult, repo_root: str, surface: str) -> None:
    """Append one event when the result blocks. Silently no-op on any failure."""
    if not enabled() or not result.stats.get("blocking"):
        return
    rejects = [f for f in result.findings if f.level is Level.REJECT]
    if not rejects:
        return
    event = {
        "ts": int(time.time()),
        "repo": os.path.basename(os.path.abspath(repo_root)) or repo_root,
        "surface": surface,  # cli | mcp | hook | action
        "mode": result.stats.get("mode"),
        "rejects": len(rejects),
        "oracles": sorted({f.oracle for f in rejects}),
        "files": sorted({f.claim.location.file for f in rejects})[:20],
    }
    try:
        with open(path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        return


def read(limit: int | None = None) -> list[dict[str, Any]]:
    try:
        with open(path(), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events[-limit:] if limit else events


def summary(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = read() if events is None else events
    blocks = len(events)
    rejects = sum(int(e.get("rejects", 0)) for e in events)
    by_repo: dict[str, int] = {}
    by_oracle: dict[str, int] = {}
    by_surface: dict[str, int] = {}
    for e in events:
        by_repo[str(e.get("repo"))] = by_repo.get(str(e.get("repo")), 0) + 1
        by_surface[str(e.get("surface"))] = by_surface.get(str(e.get("surface")), 0) + 1
        for o in e.get("oracles", []) or []:
            by_oracle[str(o)] = by_oracle.get(str(o), 0) + 1
    return {
        "path": path(),
        "enabled": enabled(),
        "blocks": blocks,
        "broken_wires": rejects,
        "estimated_tokens_saved": blocks * ROUND_TRIP_TOKENS,
        "estimate_note": (
            f"assumes one avoided retry loop of about {ROUND_TRIP_TOKENS} tokens "
            f"per blocked change; an estimate, not a measurement"
        ),
        "by_repo": dict(sorted(by_repo.items())),
        "by_oracle": dict(sorted(by_oracle.items())),
        "by_surface": dict(sorted(by_surface.items())),
        "first": events[0]["ts"] if events else None,
        "last": events[-1]["ts"] if events else None,
    }


def render_text(info: dict[str, Any]) -> str:
    if not info["blocks"]:
        return (
            f"ledger: no blocked changes recorded yet ({info['path']})\n"
            f"every reject weftgate raises before code ships is counted here"
        )
    lines = [
        f"ledger: {info['blocks']} blocked change(s), {info['broken_wires']} broken wire(s) "
        f"caught before they shipped",
        f"  estimated tokens saved: ~{info['estimated_tokens_saved']:,}  ({info['estimate_note']})",
    ]
    for label, key in (
        ("by repo", "by_repo"),
        ("by oracle", "by_oracle"),
        ("by surface", "by_surface"),
    ):
        items = ", ".join(f"{k} {v}" for k, v in info[key].items())
        lines.append(f"  {label:10} {items}")
    lines.append(f"  file: {info['path']}")
    return "\n".join(lines)


def clear() -> None:
    try:
        os.remove(path())
    except OSError:
        pass
