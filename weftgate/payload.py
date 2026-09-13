"""Deterministic, bounded JSON for agent context. No model tokenizer is assumed."""

from __future__ import annotations

import json
import os
from typing import Any


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def bounded(
    items: list[dict[str, Any]], metadata: dict[str, Any], budget: int | None = None
) -> dict[str, Any]:
    """Cap UTF-8 JSON bytes at 4 * budget. Tokens are an estimate, never a guarantee.

    Omit whole items, preserving ranked order. Include the accounting envelope in
    the cap. The MCP text payload uses this exact serialization too.
    """
    if budget is None:
        try:
            budget = int(os.environ.get("WEFTGATE_CONTEXT_BUDGET", "1500"))
        except ValueError as exc:
            raise ValueError("WEFTGATE_CONTEXT_BUDGET must be an integer") from exc
    if isinstance(budget, bool) or not isinstance(budget, int) or not 256 <= budget <= 16000:
        raise ValueError("budget must be an integer from 256 to 16000 (estimated tokens)")
    out: dict[str, Any] = {
        **metadata,
        "items": [],
        "usage": {
            "max_bytes": budget * 4,
            "bytes": 0,
            "estimated_tokens": 0,
            "omitted": len(items),
            "token_estimate": "ceil(UTF-8 bytes / 4); model dependent",
        },
    }
    selected: list[dict[str, Any]] = out["items"]
    usage = out["usage"]

    def measure() -> int:
        # The number of digits in the size fields can change the size itself.
        for _ in range(8):
            n = len(encode(out).encode("utf-8"))
            if usage["bytes"] == n and usage["estimated_tokens"] == (n + 3) // 4:
                return n
            usage["bytes"] = n
            usage["estimated_tokens"] = (n + 3) // 4
        return len(encode(out).encode("utf-8"))

    if measure() > budget * 4:
        raise ValueError("response metadata exceeds the context budget; shorten the query")
    for item in items:
        selected.append(item)
        usage["omitted"] = len(items) - len(selected)
        if measure() > budget * 4:
            selected.pop()
            usage["omitted"] = len(items) - len(selected)
    measure()
    return out
