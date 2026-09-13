"""Native completion adapters. They request a bounded repair pass on proven failures.

No test execution or transcript reading occurs in a hook. Client permissions,
trust settings and loop limits remain authoritative. CI is the portable boundary.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .gate import Session
from .payload import encode
from .workflow import checkpoint


def completion(agent: str, root: str, raw: str, store_path: str | None = None) -> int:
    output: dict[str, Any] = {}
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        retry = True
        if agent in ("claude", "codex"):
            retry = payload.get("stop_hook_active") is not True
        elif agent == "cursor":
            retry = payload.get("status") == "completed" and int(payload.get("loop_count", 0)) < 2
        elif agent == "antigravity":
            retry = (
                payload.get("terminationReason") == "model_stop"
                and payload.get("fullyIdle") is True
                and int(payload.get("executionNum", 0)) < 2
            )
        else:
            raise ValueError(f"no completion adapter for {agent}")
        if retry:
            with Session(root, store_path=store_path) as session:
                report = checkpoint(session, budget=1200)
            if report["blocking"]:
                reason = (
                    "Weftgate found a proven contract failure. Repair it and re-check. "
                    + encode(report)
                )
                if agent == "cursor":
                    output = {"followup_message": reason}
                else:
                    output = {
                        "decision": "continue" if agent == "antigravity" else "block",
                        "reason": reason,
                    }
    except Exception as exc:  # noqa: BLE001 - broken/unsupported hooks must not false-block
        print(f"weftgate completion hook skipped: {exc}", file=sys.stderr)
    print(encode(output))
    return 0
