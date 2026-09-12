"""The shared vocabulary. Everything else depends on these. Standard library only.

Four levels, three frozen records, and one rule: ``UNVERIFIABLE`` never raises
the overall verdict, and a soft claim can never be a ``REJECT``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:  # pragma: no cover - exercised only on Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        """Minimal backport of :class:`enum.StrEnum` for Python 3.10."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = [
    "Claim",
    "Finding",
    "GateResult",
    "Level",
    "Location",
    "StrEnum",
    "worst",
]


class Level(StrEnum):
    """Verdict level for a single claim.

    Only REJECT is blocking-eligible. REVIEW is advisory. UNVERIFIABLE means the
    oracle could not run at all and must never raise the overall verdict.
    """

    ACCEPT = "accept"
    REVIEW = "review"
    REJECT = "reject"
    UNVERIFIABLE = "unverifiable"


# Ordering used to compute the worst blocking-eligible level. UNVERIFIABLE is
# deliberately below ACCEPT so it can never become the overall verdict.
_RANK: dict[Level, int] = {
    Level.UNVERIFIABLE: -1,
    Level.ACCEPT: 0,
    Level.REVIEW: 1,
    Level.REJECT: 2,
}


def worst(levels: list[Level]) -> Level:
    """Overall verdict = worst blocking-eligible level; UNVERIFIABLE never raises it."""
    blocking = [lv for lv in levels if lv is not Level.UNVERIFIABLE]
    if not blocking:
        return Level.ACCEPT
    return max(blocking, key=lambda lv: _RANK[lv])


@dataclass(frozen=True)
class Location:
    file: str
    line: int = 0
    col: int = 0

    def __str__(self) -> str:
        return f"{self.file}:{self.line}" if self.line else self.file


@dataclass(frozen=True)
class Claim:
    """One relational assertion to be checked, with where it came from.

    ``hard`` claims may REJECT; soft claims cap at REVIEW. ``source`` is "code"
    for claims extracted from a change, "assertion" for structured claims an
    agent states directly, and "prose" for claims derived from free text (which
    are always soft, per the soft-fail rule).
    """

    kind: str  # e.g. "env_var", "route_handler", "import"
    subject: str  # the referenced thing, e.g. "DATABASE_URL"
    location: Location
    attrs: dict[str, Any] = field(default_factory=dict)  # oracle-specific payload
    hard: bool = True  # hard claims may REJECT; soft claims cap at REVIEW
    source: str = "code"  # "code" | "assertion" | "prose"

    def __post_init__(self) -> None:
        if self.source == "prose" and self.hard:
            # A prose-derived claim is never hard: it softens reject to review.
            object.__setattr__(self, "hard", False)

    def sort_key(self) -> tuple[str, int, int, str, str]:
        return (self.location.file, self.location.line, self.location.col, self.kind, self.subject)


@dataclass(frozen=True)
class Finding:
    claim: Claim
    level: Level
    reason: str
    oracle: str
    suggestions: tuple[str, ...] = ()

    def capped(self) -> Finding:
        """Enforce the soft-claim rule: a soft claim can never be a REJECT."""
        if not self.claim.hard and self.level is Level.REJECT:
            return Finding(self.claim, Level.REVIEW, self.reason, self.oracle, self.suggestions)
        return self

    def sort_key(self) -> tuple[str, int, int, str, str, str]:
        return (*self.claim.sort_key(), self.oracle)

    def to_dict(self) -> dict[str, Any]:
        """The one JSON shape shared by the CLI and the MCP server."""
        return {
            "level": self.level.value,
            "oracle": self.oracle,
            "kind": self.claim.kind,
            "subject": self.claim.subject,
            "file": self.claim.location.file,
            "line": self.claim.location.line,
            "col": self.claim.location.col,
            "hard": self.claim.hard,
            "source": self.claim.source,
            "reason": self.reason,
            "suggestions": list(self.suggestions),
            "attrs": _jsonable(self.claim.attrs),
        }


@dataclass(frozen=True)
class GateResult:
    verdict: Level
    findings: tuple[Finding, ...]
    stats: dict[str, Any]

    @classmethod
    def build(
        cls, findings: list[Finding], extra_stats: dict[str, Any] | None = None
    ) -> GateResult:
        """Cap soft claims, order findings deterministically, and compute the verdict."""
        capped = sorted((f.capped() for f in findings), key=Finding.sort_key)
        verdict = worst([f.level for f in capped])
        stats: dict[str, Any] = {lv.value: sum(1 for f in capped if f.level is lv) for lv in Level}
        stats["claims"] = len(capped)
        if extra_stats:
            stats.update(extra_stats)
        return cls(verdict, tuple(capped), stats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "stats": _jsonable(self.stats),
            "findings": [f.to_dict() for f in self.findings],
        }


def _jsonable(value: Any) -> Any:
    """Coerce a nested structure to plain JSON-compatible types, deterministically."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
