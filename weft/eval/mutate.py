"""Mutation harness: inject known-bad edges into a *copy* of a repo and confirm
the gate detects and blocks each. Deterministic by seed. A detection with no
usable suggestion counts as a miss (no survivorship bias). Detected and blocked
are reported separately, per oracle.

Mutations (each has a machine-checkable "correct" suggestion):
  env_vars          typo a literal env read so it matches no declaration
  imports_lockfile  typo a locked third-party import into a phantom package
  routes_fastapi    typo a handler reference, typo an included router, or rename
                    the handler's ``def`` so the route dangles

Candidates are references the untouched gate ACCEPTs, so a miss is the gate's
fault, not the repo's. The user's repo is never modified: it is copied into a
temp dir (junk directories excluded) with its own throwaway index.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any

from ..change import Change
from ..config import IGNORED_DIRS, Config
from ..gate import Session
from ..oracles.imports_lockfile import norm
from ..types import Finding, Level
from . import audit as _audit
from .fixture import write_fixture

_DEFAULT_COUNT = 5


@dataclass
class MutationReport:
    seed: int
    total: int
    detected: int
    blocked: int
    suggested: int  # blocked AND the correct name was among the suggestions
    per_oracle: dict[str, dict[str, int]] = field(default_factory=dict)
    mutations: list[dict[str, Any]] = field(default_factory=list)
    label: str = "field"  # "upper bound" when run on the fixture the oracles were tuned on

    @property
    def misses(self) -> int:
        return self.total - self.suggested

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "total": self.total,
            "detected": self.detected,
            "blocked": self.blocked,
            "suggested": self.suggested,
            "misses": self.misses,
            "label": self.label,
            "per_oracle": {k: dict(v) for k, v in sorted(self.per_oracle.items())},
            "mutations": list(self.mutations),
        }


@dataclass(frozen=True)
class Mutation:
    oracle: str
    op: str  # "typo_env" | "typo_import" | "typo_handler" | "typo_router" | "rename_def"
    file: str  # file whose content changes
    line: int  # 1-based line in `file`
    original: str  # token replaced
    mutated: str  # replacement token
    check_file: str  # file the gate is run on
    expect_suggestion: str  # the name a usable suggestion must contain
    related: str  # token a finding must mention to count as a detection


def run(
    repo_root: str | None,
    seed: int = 13,
    count: int | None = None,
    config: Config | None = None,
) -> MutationReport:
    """Run the harness on ``repo_root`` (copied), or on the built-in fixture if None."""
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory(prefix="weft-mutate-") as tmp:
        work = os.path.join(tmp, "repo")
        if repo_root is None:
            os.makedirs(work)
            write_fixture(work)
            label = "upper bound"
        else:
            _copy_repo(repo_root, work)
            label = "field"
        store = os.path.join(tmp, "index.sqlite")
        with Session(work, config=config, store_path=store) as s:
            s.sync()
            candidates = _candidates(s)
            per_count = count if count is not None else _DEFAULT_COUNT
            chosen: list[_Candidate] = []
            for oracle in sorted(candidates):
                pool = candidates[oracle]
                take = min(per_count, len(pool))
                chosen.extend(rng.sample(pool, take) if take < len(pool) else list(pool))
            mutations: list[Mutation] = []
            for cand in chosen:
                m = _make_mutation(cand, rng, s)
                if m is not None:
                    mutations.append(m)
            report = MutationReport(seed, 0, 0, 0, 0, label=label)
            for m in sorted(mutations, key=lambda x: (x.oracle, x.file, x.line, x.original)):
                outcome = _apply_and_check(s, m)
                _tally(report, m, outcome)
        return report


# --- candidates ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    oracle: str
    kind: str
    file: str
    line: int
    subject: str
    attrs: dict[str, Any]

    def __lt__(self, other: _Candidate) -> bool:
        return (self.file, self.line, self.subject) < (other.file, other.line, other.subject)

    def __hash__(self) -> int:
        return hash((self.oracle, self.kind, self.file, self.line, self.subject))


def _candidates(s: Session) -> dict[str, list[_Candidate]]:
    """References the untouched gate accepts, grouped by oracle, sorted."""
    out: dict[str, list[_Candidate]] = {}
    for rel in _audit.select_files(s, None):
        try:
            change = Change.from_file(os.path.join(s.store.repo_root, rel), s.store.repo_root)
        except OSError:
            continue
        for f in s.check_change(change, sync=False).findings:
            if f.level is not Level.ACCEPT or not f.claim.hard:
                continue
            if not _eligible(f):
                continue
            c = _Candidate(
                f.oracle,
                f.claim.kind,
                f.claim.location.file,
                f.claim.location.line,
                f.claim.subject,
                dict(f.claim.attrs),
            )
            out.setdefault(f.oracle, []).append(c)
    deduped: dict[str, list[_Candidate]] = {}
    for oracle, cands in out.items():
        seen: set[tuple[str, int, str]] = set()
        for c in sorted(set(cands)):
            key = (c.file, c.line, str(c.attrs.get("handler") or c.subject))
            if key in seen:
                continue
            seen.add(key)
            deduped.setdefault(oracle, []).append(c)
    return deduped


def _eligible(f: Finding) -> bool:
    match f.oracle:
        case "env_vars":
            # A read with an inline default is never a broken wire, so it is no candidate.
            return (
                f.reason.startswith("declared in")
                and f.claim.subject.isidentifier()
                and not f.claim.attrs.get("default")
            )
        case "imports_lockfile":
            if not f.reason.startswith("in ") or f.claim.attrs.get("optional"):
                return False  # an optional (try/except) import is never a broken wire
            top = str(f.claim.attrs.get("top") or f.claim.subject)
            if f.claim.attrs.get("lang") == "node":
                # Plain package names only (a scoped or sub-path spec is harder to strike).
                return bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]*", top)) and "/" not in top
            # Only where the suggestion can name the import: dist name == import name.
            m = re.search(r" as (\S+)", f.reason)
            return m is not None and norm(m.group(1)) == norm(top) and top.isidentifier()
        case "routes_fastapi":
            if f.claim.kind == "router_include":
                return str(f.claim.attrs.get("child_kind")) == "name"
            style = str(f.claim.attrs.get("style"))
            hk = str(f.claim.attrs.get("handler_kind"))
            return (
                style != "decorator"
                and hk == "name"
                and "defined in this file" in f.reason
                or style != "decorator"
                and hk == "name"
                and "resolves to" in f.reason
            )
    return False


# --- mutations -------------------------------------------------------------------------------


def _typo(name: str, rng: random.Random) -> str:
    letters = "abcdefghijklmnopqrstuvwxyz"
    for _ in range(20):
        ops = ["swap", "dup", "sub"] + (["del"] if len(name) > 3 else [])
        op = rng.choice(ops)
        i = rng.randrange(len(name))
        if op == "del":
            cand = name[:i] + name[i + 1 :]
        elif op == "swap" and len(name) > 1:
            j = min(i + 1, len(name) - 1)
            if j == i:
                i, j = i - 1, i
            cand = name[:i] + name[j] + name[i] + name[j + 1 :]
        elif op == "dup":
            cand = name[:i] + name[i] + name[i:]
        else:
            ch = rng.choice(letters)
            ch = ch.upper() if name[i].isupper() else ch
            cand = name[:i] + ch + name[i + 1 :]
        if cand != name and cand.isidentifier() and not cand[0].isdigit():
            return cand
    return name + "x"


def _typo_spec(name: str, rng: random.Random) -> str:
    """Typo for a Node package name (dashes and dots allowed): swap or duplicate a letter."""
    letters = [i for i, ch in enumerate(name) if ch.isalnum()]
    if len(letters) < 2:
        return name + "x"
    i = rng.choice(letters[:-1])
    j = i + 1
    if name[j].isalnum() and name[i] != name[j]:
        return name[:i] + name[j] + name[i] + name[j + 1 :]
    return name[:i] + name[i] + name[i:]


def _make_mutation(c: _Candidate, rng: random.Random, s: Session) -> Mutation | None:
    match c.oracle:
        case "env_vars":
            mutated = _typo(c.subject, rng)
            return Mutation(
                "env_vars",
                "typo_env",
                c.file,
                c.line,
                c.subject,
                mutated,
                c.file,
                expect_suggestion=c.subject,
                related=mutated,
            )
        case "imports_lockfile":
            top = str(c.attrs.get("top") or c.subject)
            mutated = _typo(top, rng) if top.isidentifier() else _typo_spec(top, rng)
            return Mutation(
                "imports_lockfile",
                "typo_import",
                c.file,
                c.line,
                top,
                mutated,
                c.file,
                expect_suggestion=top,
                related=mutated,
            )
        case "routes_fastapi":
            if c.kind == "router_include":
                mutated = _typo(c.subject, rng)
                return Mutation(
                    "routes_fastapi",
                    "typo_router",
                    c.file,
                    c.line,
                    c.subject,
                    mutated,
                    c.file,
                    expect_suggestion=c.subject,
                    related=mutated,
                )
            handler = str(c.attrs.get("handler"))
            def_file = _def_file(s, c.file, handler)
            if def_file is not None and rng.random() < 0.5:
                renamed = _typo(handler, rng)
                line = _def_line(s, def_file, handler)
                if line:
                    return Mutation(
                        "routes_fastapi",
                        "rename_def",
                        def_file,
                        line,
                        handler,
                        renamed,
                        c.file,
                        expect_suggestion=renamed,
                        related=handler,
                    )
            mutated = _typo(handler, rng)
            return Mutation(
                "routes_fastapi",
                "typo_handler",
                c.file,
                c.line,
                handler,
                mutated,
                c.file,
                expect_suggestion=handler,
                related=mutated,
            )
    return None


def _def_file(s: Session, file: str, handler: str) -> str | None:
    text = s.ctx.read_text(file) or ""
    if re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(handler)}\s*\(", text, re.M):
        return file
    m = re.search(rf"^from\s+([\w.]+)\s+import\s+(?:[^\n]*\b){re.escape(handler)}\b", text, re.M)
    if not m:
        return None
    from ..oracle import file_of_module

    return file_of_module(s.ctx, m.group(1))


def _def_line(s: Session, file: str, handler: str) -> int:
    text = s.ctx.read_text(file) or ""
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(rf"^\s*(?:async\s+)?def\s+{re.escape(handler)}\s*\(", line):
            return i
    return 0


def _apply_and_check(s: Session, m: Mutation) -> dict[str, Any]:
    full = os.path.join(s.store.repo_root, m.file)
    with open(full, encoding="utf-8") as fh:
        original = fh.read()
    lines = original.split("\n")
    if m.line - 1 >= len(lines):
        return {"detected": False, "blocked": False, "suggested": False, "error": "line gone"}
    # A call can span lines (`include_router(\n    router,`): the claim carries the
    # call's first line, so look a few lines ahead for the token.
    idx, n, new_line = m.line - 1, 0, ""
    for idx in range(m.line - 1, min(m.line + 7, len(lines))):
        for pattern in _patterns(m):
            new_line, n = re.subn(pattern, m.mutated, lines[idx], count=1)
            if n:
                break
        if n:
            break
    if n == 0:
        return {
            "detected": False,
            "blocked": False,
            "suggested": False,
            "error": "token not found near line",
        }
    lines[idx] = new_line
    try:
        with open(full, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        s.sync()
        check_full = os.path.join(s.store.repo_root, m.check_file)
        res = s.check_change(Change.from_file(check_full, s.store.repo_root), sync=False)
    finally:
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(original)
        s.sync()
    related = [f for f in res.findings if f.oracle == m.oracle and _mentions(f, m)]
    detected = any(f.level in (Level.REVIEW, Level.REJECT) for f in related)
    blocked = any(f.level is Level.REJECT for f in related)
    suggested = blocked and any(
        m.expect_suggestion in sug or norm(sug) == norm(m.expect_suggestion)
        for f in related
        if f.level is Level.REJECT
        for sug in f.suggestions
    )
    return {
        "detected": detected,
        "blocked": blocked,
        "suggested": suggested,
        "findings": [f.to_dict() for f in related],
    }


def _patterns(m: Mutation) -> list[str]:
    """Where on the line to strike: the quoted literal first for env reads and
    imports, then a property access, then any whole-word occurrence."""
    tok = re.escape(m.original)
    if m.op == "typo_env":
        return [rf"(?<=['\"]){tok}(?=['\"])", rf"(?<=\.){tok}(?![\w])", rf"(?<![\w]){tok}(?![\w])"]
    if m.op == "typo_import":
        return [rf"(?<=['\"]){tok}(?=['\"/])", rf"(?<![\w.]){tok}(?![\w])"]
    # handlers and routers: never inside a string (a route path often echoes the name)
    return [rf"(?<![\w./'\"]){tok}(?![\w'\"])"]


def _mentions(f: Finding, m: Mutation) -> bool:
    hay = " ".join(
        [
            f.claim.subject,
            f.reason,
            str(f.claim.attrs.get("handler", "")),
            str(f.claim.attrs.get("top", "")),
        ]
    )
    return re.search(rf"(?<![\w]){re.escape(m.related)}(?![\w])", hay) is not None


def _tally(report: MutationReport, m: Mutation, outcome: dict[str, Any]) -> None:
    per = report.per_oracle.setdefault(
        m.oracle, {"total": 0, "detected": 0, "blocked": 0, "suggested": 0, "misses": 0}
    )
    report.total += 1
    per["total"] += 1
    if outcome["detected"]:
        report.detected += 1
        per["detected"] += 1
    if outcome["blocked"]:
        report.blocked += 1
        per["blocked"] += 1
    if outcome["suggested"]:
        report.suggested += 1
        per["suggested"] += 1
    else:
        per["misses"] += 1
    report.mutations.append(
        {
            "oracle": m.oracle,
            "op": m.op,
            "file": m.file,
            "line": m.line,
            "original": m.original,
            "mutated": m.mutated,
            "expect_suggestion": m.expect_suggestion,
            **{k: v for k, v in outcome.items() if k != "findings"},
            "suggestions": sorted(
                {s for f in outcome.get("findings", []) for s in f["suggestions"]}
            ),
        }
    )


def _copy_repo(src: str, dst: str) -> None:
    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {
            n
            for n in names
            if n in IGNORED_DIRS
            or n.endswith(".egg-info")
            or n.endswith((".sqlite", ".sqlite-wal", ".sqlite-shm"))
        }

    shutil.copytree(src, dst, ignore=ignore, symlinks=True)


def render_text(report: MutationReport) -> str:
    lines = [
        f"mutation harness (seed {report.seed}): {report.total} mutations, "
        f"{report.detected} detected, {report.blocked} blocked, "
        f"{report.suggested} with a usable suggestion, {report.misses} misses"
    ]
    for name, c in sorted(report.per_oracle.items()):
        lines.append(
            f"  {name:18} total {c['total']:3}  detected {c['detected']:3}  "
            f"blocked {c['blocked']:3}  suggested {c['suggested']:3}  "
            f"misses {c['misses']:3}"
        )
    for m in report.mutations:
        status = (
            "ok  "
            if m["suggested"]
            else ("weak" if m["blocked"] else ("soft" if m["detected"] else "MISS"))
        )
        extra = f"  [{m['error']}]" if m.get("error") else ""
        lines.append(
            f"  {status} {m['oracle']:16} {m['op']:13} {m['file']}:{m['line']}  "
            f"{m['original']} -> {m['mutated']}  suggested {m['suggestions']}{extra}"
        )
    if report.label != "field":
        lines.append(f"  ({report.label}: measured on the fixture the oracles were tuned on)")
    return "\n".join(lines)
