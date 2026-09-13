"""Small, deterministic secret scrubbing for explicitly saved memory.

Adapted from Mnemo's redaction boundary. This is a best-effort guard, not a
credential scanner or a guarantee that arbitrary sensitive prose is safe.
"""

from __future__ import annotations

import re

_RULES = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        "[REDACTED PRIVATE KEY]",
    ),
    (
        "bearer",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{12,}=*"),
        "Bearer [REDACTED]",
    ),
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b([a-z0-9_]*(?:password|passwd|secret|token|api[_-]?key))"
            r"[\"']?\s*[:=]\s*(?:\"[^\"]{4,}\"|'[^']{4,}'|[^\s\"'`,;]{4,})"
        ),
        r"\1=[REDACTED]",
    ),
    (
        "url_password",
        re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:)[^\s/@]+(@)"),
        r"\1[REDACTED]\2",
    ),
)


def scrub(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for name, pattern, replacement in _RULES:

        def replace(match: re.Match[str], name: str = name, template: str = replacement) -> str:
            value = match.expand(template)
            if value != match.group():
                counts[name] = counts.get(name, 0) + 1
            return value

        text = pattern.sub(replace, text)
    return text, counts
