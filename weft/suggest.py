"""Did-you-mean: bounded-Levenshtein plus a token-overlap bonus, budget-capped.

Deterministic. Used to make a REJECT actionable instead of just a complaint.
Standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_SUGGESTIONS = 3
_MAX_DISTANCE = 3
_MAX_CANDIDATES = 50_000  # budget: beyond this only prefix-sharing candidates are scored

_TOKEN_SPLIT = re.compile(r"[_\-./:\s]+|(?<=[a-z0-9])(?=[A-Z])")


def levenshtein(a: str, b: str, cap: int) -> int:
    """Edit distance, giving up early with ``cap + 1`` once it exceeds ``cap``."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            best = min(best, cur[j])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def tokens(name: str) -> frozenset[str]:
    return frozenset(t.lower() for t in _TOKEN_SPLIT.split(name) if t)


def did_you_mean(
    name: str,
    candidates: Iterable[str],
    limit: int = MAX_SUGGESTIONS,
    max_distance: int | None = None,
) -> list[str]:
    """Closest candidates to ``name``: small edit distance, or shared name tokens
    (at least two, or every token of one side: STRIPE_SECRET -> STRIPE_SECRET_KEY).

    Ranked by (distance minus token overlap, distance, candidate) so the output
    is stable for the same inputs. Never returns ``name`` itself.
    """
    cap = _MAX_DISTANCE if max_distance is None else max_distance
    cap = max(cap, min(4, len(name) // 4))
    lname = name.lower()
    ltoks = tokens(name)
    scored: list[tuple[int, int, str]] = []
    pool = sorted(set(candidates))
    if len(pool) > _MAX_CANDIDATES:
        pool = [c for c in pool if c[:1].lower() == lname[:1]]
    for cand in pool:
        if cand == name:
            continue
        lc = cand.lower()
        d = levenshtein(lname, lc, cap)
        ctoks = tokens(cand)
        overlap = len(ltoks & ctoks) if ltoks else 0
        by_tokens = overlap >= 2 or (bool(ltoks) and overlap == len(ltoks)) or (
            bool(ctoks) and overlap == len(ctoks))
        if d <= cap or by_tokens:
            scored.append((d - overlap, d, cand))
    scored.sort()
    return [c for _, _, c in scored[:limit]]
