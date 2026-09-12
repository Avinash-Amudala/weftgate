"""Audit sweep: run the gate over the existing, already-merged codebase and report
latent broken edges. Reuses the same oracle check paths as the live gate. This is
both the correctness check and the adoption loop (``weft audit``).

One sync, then one whole-file Change per source file through
``Session.check_change``. Only non-ACCEPT findings are kept in the result (an
audit of a large repo would otherwise carry thousands of accepts); the accept
count is in the stats. Label any tuned number an upper bound.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..change import Change
from ..gate import Session, blocks
from ..types import Finding, GateResult, Level

SOURCE_SUFFIXES = (
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".mts",
    ".cts",
    ".vue",
    ".svelte",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".php",
)
_MAX_BYTES = 2_000_000


@dataclass
class AuditReport:
    repo_root: str
    files_scanned: int
    result: GateResult
    per_oracle: dict[str, dict[str, int]] = field(default_factory=dict)
    label: str = "field"  # "field" for a user's own repo, "upper bound" when tuned on it

    @property
    def rejects(self) -> int:
        return int(self.result.stats.get("reject", 0))

    @property
    def reviews(self) -> int:
        return int(self.result.stats.get("review", 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "files_scanned": self.files_scanned,
            "label": self.label,
            "per_oracle": {k: dict(v) for k, v in sorted(self.per_oracle.items())},
            **self.result.to_dict(),
        }


def run(
    repo_root: str,
    paths: list[str] | None = None,
    store_path: str | None = None,
    session: Session | None = None,
    label: str = "field",
) -> AuditReport:
    own = session is None
    s = session or Session(repo_root, store_path=store_path)
    try:
        s.sync()
        files = select_files(s, paths)
        findings: list[Finding] = []
        per_oracle: dict[str, dict[str, int]] = {
            name: {lv.value: 0 for lv in Level} for name in s.oracles
        }
        accepts = 0
        for rel in files:
            full = os.path.join(s.store.repo_root, rel)
            try:
                change = Change.from_file(full, s.store.repo_root)
            except OSError:
                continue
            res = s.check_change(change, sync=False)
            for f in res.findings:
                per_oracle.setdefault(f.oracle, {lv.value: 0 for lv in Level})
                per_oracle[f.oracle][f.level.value] += 1
                if f.level is Level.ACCEPT:
                    accepts += 1
                else:
                    findings.append(f)
        extra: dict[str, Any] = {
            "mode": "audit",
            "files": len(files),
            "accepted": accepts,
            "oracles": list(s.oracles),
            "block_on": s.config.block_on,
            "commit": s.ctx.git_commit,
        }
        if s.sync_errors:
            extra["sync_errors"] = dict(s.sync_errors)
        result = GateResult.build(findings, extra)
        result.stats["accept"] = accepts
        result.stats["claims"] = accepts + len(result.findings)
        result.stats["blocking"] = blocks(result, s.config)
        return AuditReport(s.store.repo_root, len(files), result, per_oracle, label)
    finally:
        if own:
            s.close()


def select_files(session: Session, paths: list[str] | None) -> list[str]:
    """Source files to audit: every indexable file with a known suffix, optionally
    limited to the given files/directories (repo-relative or absolute)."""
    root = session.store.repo_root
    wanted: list[str] = []
    for p in paths or []:
        full = p if os.path.isabs(p) else os.path.join(root, p)
        rel = os.path.relpath(os.path.abspath(full), root).replace(os.sep, "/")
        wanted.append(rel.rstrip("/"))
    out: list[str] = []
    for rel in session.store.all_files():
        if not rel.endswith(SOURCE_SUFFIXES):
            continue
        if wanted and not any(rel == w or rel.startswith(w + "/") for w in wanted):
            continue
        try:
            if os.path.getsize(os.path.join(root, rel)) > _MAX_BYTES:
                continue
        except OSError:
            continue
        out.append(rel)
    return out


def render_text(report: AuditReport) -> str:
    res = report.result
    broken = [f for f in res.findings if f.level is not Level.ACCEPT]
    head = f"Scanned {report.files_scanned} files. "
    if not broken:
        lines = [head + "No broken wires found."]
    else:
        rejects = sum(1 for f in broken if f.level is Level.REJECT)
        lines = [
            head + f"{rejects} broken wire{'s' if rejects != 1 else ''} found, "
            f"{len(broken) - rejects} to review:",
            "",
        ]
        for f in broken:
            tip = f"   (did you mean {', '.join(f.suggestions)}?)" if f.suggestions else ""
            lines.append(f"  {f.level.value.upper():12} {str(f.claim.location):32} {f.reason}{tip}")
    lines.append("")
    for name, counts in sorted(report.per_oracle.items()):
        lines.append(
            f"  {name:18} accept {counts.get('accept', 0):5}  review "
            f"{counts.get('review', 0):4}  reject {counts.get('reject', 0):4}  "
            f"unverifiable {counts.get('unverifiable', 0):4}"
        )
    for name, err in sorted((res.stats.get("sync_errors") or {}).items()):
        lines.append(f"  ! {name}: {err}")
    if report.label != "field":
        lines.append(f"  ({report.label}: measured on the repo the oracles were tuned on)")
    return "\n".join(lines)
