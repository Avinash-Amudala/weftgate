"""Run the enabled oracles over a change (diff mode) or a claim set (claim mode)
and return a GateResult. Runs each oracle's sync before checking so the gate is
never stale. Indexing failures are tolerated: the oracle then returns
UNVERIFIABLE, which never blocks. An oracle that crashes while extracting or
checking produces one UNVERIFIABLE finding instead of taking the gate down.

The CLI and the MCP server both call :class:`Session` (or the module-level
wrappers), which is what keeps the two surfaces from ever diverging.

Standard library only.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from . import honesty
from .change import Change
from .config import Config
from .oracle import Context, Oracle
from .registry import load_oracles
from .store import Store
from .types import Claim, Finding, GateResult, Level, Location

_SYNC_ERROR_LIMIT = 400


class Session:
    """One repo, one store, one enabled oracle set. Reusable across many checks."""

    def __init__(
        self,
        repo_root: str,
        config: Config | None = None,
        store: Store | None = None,
        store_path: str | None = None,
        oracles: dict[str, Oracle] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.config = config or Config.load(repo_root)
        self.store = store or Store(repo_root, path=store_path, ignored_dirs=self.config.exclude)
        self.oracles = oracles if oracles is not None else load_oracles(self.config)
        self.ctx = Context(
            repo_root=self.store.repo_root,
            store=self.store,
            config=self.config,
            git_commit=self.store.get_meta("build_commit") or None,
        )
        self._synced = False
        self.sync_errors: dict[str, str] = {}

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- indexing -----------------------------------------------------------------------

    def sync(self, force_rebuild: bool = False) -> dict[str, dict[str, Any]]:
        """Build or incrementally sync every enabled oracle's index, atomically per
        oracle. Never raises: a failing oracle is marked unbuilt and reported."""
        commit = self.store.current_commit()
        self.store.forget_sync_cache()
        report: dict[str, dict[str, Any]] = {}
        for name, oracle in self.oracles.items():
            version = str(getattr(oracle, "version", "1"))
            fresh = (
                self.store.is_built(name)
                and self.store.oracle_version(name) == version
                and not self.store.needs_rebuild(name)
            )
            action = "sync" if fresh and not force_rebuild else "build"
            try:
                if action == "build":
                    self._build(oracle, name, commit, version)
                else:
                    since = self.store.oracle_commit(name)
                    sync = getattr(oracle, "sync", None)
                    if sync is not None:
                        sync(self.ctx, since)
                    self.store.mark_built(name, commit, version)
            except Exception as first:  # noqa: BLE001 - indexing must never break the gate
                # One retry as a full rebuild; if that fails too, the oracle is unbuilt
                # and will answer UNVERIFIABLE (never REJECT) until the cause is fixed.
                try:
                    self._build(oracle, name, commit, version)
                    action = "rebuild"
                except Exception as second:  # noqa: BLE001
                    self._unbuild(name)
                    action = "failed"
                    self.sync_errors[name] = _short(second or first)
            report[name] = {"action": action, **self.store.oracle_status(name)}
        self.store.finish_sync(commit)
        self.ctx.git_commit = commit
        self._synced = True
        return report

    def _build(self, oracle: Oracle, name: str, commit: str | None, version: str) -> None:
        build = getattr(oracle, "build", None)
        if build is not None:
            build(self.ctx)
        self.store.mark_built(name, commit, version)

    def _unbuild(self, name: str) -> None:
        try:
            self.store.mark_unbuilt(name)
            self.store.namespace(name).drop_all()
        except Exception:  # noqa: BLE001 - best effort
            pass

    def _ensure_synced(self, sync: bool) -> None:
        if sync and not self._synced:
            self.sync()

    # --- diff mode ----------------------------------------------------------------------

    def check_change(self, change: Change, sync: bool = True) -> GateResult:
        self._ensure_synced(sync)
        change = change.relative_to(self.repo_root)
        findings: list[Finding] = []
        for name, oracle in self.oracles.items():
            try:
                claims = oracle.extract(change, self.ctx)
            except Exception as exc:  # noqa: BLE001
                findings.append(_crash_finding(name, change.files(), "extract", exc))
                continue
            for claim in claims:
                findings.append(self._check_one(oracle, name, claim))
        return self._result(findings, {"files": change.files(), "mode": "diff"})

    # --- claim mode ---------------------------------------------------------------------

    def check_claims(self, claims: list[Claim], sync: bool = True, run: bool = False) -> GateResult:
        self._ensure_synced(sync)
        by_kind: dict[str, tuple[str, Oracle]] = {}
        for name, oracle in self.oracles.items():
            for kind in oracle.kinds:
                by_kind.setdefault(kind, (name, oracle))
        findings: list[Finding] = []
        for claim in claims:
            if claim.kind in honesty.KINDS:
                findings.append(honesty.check(claim, self.repo_root, self.config, run=run))
                continue
            owner = by_kind.get(claim.kind)
            if owner is None:
                findings.append(
                    Finding(
                        claim,
                        Level.UNVERIFIABLE,
                        f"no enabled oracle handles claim kind {claim.kind!r}",
                        "gate",
                    )
                )
                continue
            name, oracle = owner
            findings.append(self._check_one(oracle, name, claim))
        return self._result(findings, {"mode": "claim"})

    def suggest(self, kind: str, subject: str, sync: bool = True) -> list[str]:
        self._ensure_synced(sync)
        claim = Claim(kind=kind, subject=subject, location=Location(""), source="assertion")
        out: list[str] = []
        for oracle in self.oracles.values():
            if kind not in oracle.kinds:
                continue
            suggest = getattr(oracle, "suggest", None)
            if suggest is None:
                continue
            try:
                out.extend(s for s in suggest(claim, self.ctx) if s not in out)
            except Exception:  # noqa: BLE001
                continue
        return out

    # --- status -------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        from .config import detect_stack

        return {
            "repo_root": self.store.repo_root,
            "store": self.store.status(),
            "config": self.config.to_dict(),
            "stack": detect_stack(self.repo_root, self.config),
            "oracles": {
                name: {
                    "kinds": list(o.kinds),
                    "version": str(getattr(o, "version", "1")),
                    **self.store.oracle_status(name),
                }
                for name, o in self.oracles.items()
            },
            "sync_errors": dict(self.sync_errors),
        }

    # --- internals ----------------------------------------------------------------------

    def _check_one(self, oracle: Oracle, name: str, claim: Claim) -> Finding:
        try:
            return oracle.check(claim, self.ctx)
        except Exception as exc:  # noqa: BLE001
            return Finding(
                claim, Level.UNVERIFIABLE, f"oracle {name!r} crashed: {_short(exc)}", name
            )

    def _result(self, findings: list[Finding], extra: dict[str, Any]) -> GateResult:
        deduped = _dedupe(findings)
        stats: dict[str, Any] = {
            "oracles": list(self.oracles),
            "block_on": self.config.block_on,
            "commit": self.ctx.git_commit,
            **extra,
        }
        if self.sync_errors:
            stats["sync_errors"] = dict(self.sync_errors)
        result = GateResult.build(deduped, stats)
        result.stats["blocking"] = blocks(result, self.config)
        return result


def blocks(result: GateResult, config: Config) -> bool:
    """Whether a hook or CI should stop on this result, per ``block_on``."""
    match config.block_on:
        case "never":
            return False
        case "review":
            return result.verdict in (Level.REJECT, Level.REVIEW)
        case _:
            return result.verdict is Level.REJECT


def _dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop exact duplicates (the same claim extracted twice from overlapping
    regions). Claims that differ in any attribute, such as two outcome claims with
    different evidence, are distinct and all kept."""
    seen: set[str] = set()
    out: list[Finding] = []
    for f in findings:
        key = json.dumps(f.to_dict(), sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _crash_finding(name: str, files: list[str], stage: str, exc: BaseException) -> Finding:
    claim = Claim(
        kind=f"{name}:{stage}",
        subject="<oracle error>",
        location=Location(files[0] if files else ""),
        hard=False,
    )
    return Finding(
        claim, Level.UNVERIFIABLE, f"oracle {name!r} crashed during {stage}: {_short(exc)}", name
    )


def _short(exc: BaseException) -> str:
    text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return text[:_SYNC_ERROR_LIMIT]


# --- claim intake -----------------------------------------------------------------------------


def claims_from_json(data: Any) -> list[Claim]:
    """Turn the JSON an agent sends into Claims. Accepts a list, or an object with
    a ``claims`` list. Each claim is ``{"kind", "subject", "file"?, "line"?, "attrs"?,
    "hard"?, "source"?}``; a few sugar shapes are normalised (``route``,
    ``env``, ``import``, ``tests_pass``). Raises ValueError on a malformed claim."""
    items = data.get("claims", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("claims must be a list or an object with a 'claims' list")
    out: list[Claim] = []
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError(f"claim #{i} must be an object")
        out.append(_claim_from_dict(raw, i))
    return out


_KIND_ALIASES = {
    "env": "env_var",
    "env_var": "env_var",
    "environment": "env_var",
    "route": "route_handler",
    "route_handler": "route_handler",
    "endpoint": "route_handler",
    "import": "import",
    "package": "import",
    "dependency": "import",
    "router_include": "router_include",
    "tests_pass": "tests_pass",
    "tests": "tests_pass",
    "endpoint_status": "endpoint_status",
    "bug_fixed": "bug_fixed",
}


def _claim_from_dict(raw: dict[str, Any], index: int) -> Claim:
    kind = str(raw.get("kind", "")).strip()
    kind = _KIND_ALIASES.get(kind, kind)
    if not kind:
        raise ValueError(f"claim #{index}: missing 'kind'")
    attrs: dict[str, Any] = dict(raw.get("attrs") or {})
    subject = raw.get("subject")
    if kind == "route_handler" and not subject:
        method = str(raw.get("method", attrs.get("method", "GET"))).upper()
        path = raw.get("path", attrs.get("path"))
        if not path:
            raise ValueError(f"claim #{index}: route claims need 'subject' or 'method'+'path'")
        subject = f"{method} {path}"
    for key in (
        "handler",
        "method",
        "path",
        "command",
        "url",
        "status",
        "signature",
        "evidence",
        "cwd",
        "timeout",
    ):
        if key in raw and key not in attrs:
            attrs[key] = raw[key]
    if kind in honesty.KINDS and not subject:
        subject = str(attrs.get("command") or attrs.get("url") or attrs.get("signature") or kind)
    if not subject:
        raise ValueError(f"claim #{index}: missing 'subject'")
    source = str(raw.get("source", "assertion"))
    hard = bool(raw.get("hard", True))
    loc = Location(
        str(raw.get("file", "")), int(raw.get("line", 0) or 0), int(raw.get("col", 0) or 0)
    )
    return Claim(
        kind=kind, subject=str(subject), location=loc, attrs=attrs, hard=hard, source=source
    )


# --- module-level wrappers (what the CLI and MCP server call) -----------------------------------


def check_change(repo_root: str, change: Change, store_path: str | None = None) -> GateResult:
    with Session(repo_root, store_path=store_path) as s:
        return s.check_change(change)


def check_claims(
    repo_root: str, claims: list[Claim], run: bool = False, store_path: str | None = None
) -> GateResult:
    with Session(repo_root, store_path=store_path) as s:
        return s.check_claims(claims, run=run)


def index(repo_root: str, rebuild: bool = False, store_path: str | None = None) -> dict[str, Any]:
    with Session(repo_root, store_path=store_path) as s:
        report = s.sync(force_rebuild=rebuild)
        return {
            "repo_root": s.store.repo_root,
            "store": s.store.path,
            "commit": s.ctx.git_commit,
            "oracles": report,
            "sync_errors": dict(s.sync_errors),
        }


def status(repo_root: str, store_path: str | None = None) -> dict[str, Any]:
    with Session(repo_root, store_path=store_path) as s:
        return s.status()


def suggest(repo_root: str, kind: str, subject: str, store_path: str | None = None) -> list[str]:
    with Session(repo_root, store_path=store_path) as s:
        return s.suggest(kind, subject)
