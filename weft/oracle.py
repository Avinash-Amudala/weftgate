"""The oracle contract and the registration API.

An oracle answers one narrow, exact, machine-checkable question about a
relationship in the codebase. See docs/DESIGN.md section 5 and AGENTS.md
section 6. The single rule that matters: ``check()`` returns UNVERIFIABLE,
never REJECT, when it cannot run; and REJECT only on a proven absence.

This module also carries the small helpers every oracle wants: finding
constructors that keep verdict semantics in one place, and file helpers that
walk the repo through the store so every oracle sees the same file set.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .types import Claim, Finding, Level

if TYPE_CHECKING:
    from .change import Change
    from .config import Config
    from .store import Store


@dataclass
class Context:
    """Everything an oracle needs to do its job for one repo."""

    repo_root: str
    store: Store  # per-oracle namespaced SQLite; see store.py
    config: Config
    git_commit: str | None = None  # commit the index was built at, if any

    def oracle_config(self, name: str) -> dict[str, Any]:
        return self.config.oracle_config(name)

    def path(self, rel: str) -> str:
        return os.path.join(self.repo_root, rel)

    def read_text(self, rel: str, limit: int = 4_000_000) -> str | None:
        """Read a repo-relative file as text; ``None`` if missing, unreadable, or huge."""
        full = self.path(rel)
        try:
            if os.path.getsize(full) > limit:
                return None
            with open(full, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    def files(self, suffixes: Sequence[str] = ()) -> list[str]:
        """Every indexable repo file (repo-relative, sorted), optionally by suffix."""
        allf = self.store.all_files()
        if not suffixes:
            return allf
        return [f for f in allf if f.endswith(tuple(suffixes))]


@runtime_checkable
class Oracle(Protocol):
    name: str
    kinds: tuple[str, ...]

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        """Diff mode: pull candidate references out of a change. [] if none."""
        ...

    def check(self, claim: Claim, ctx: Context) -> Finding:
        """Resolve one claim. UNVERIFIABLE if the index/extra is absent."""
        ...

    # Optional lifecycle + helpers. BaseOracle provides no-op defaults so an
    # oracle only overrides what it needs:
    #   build(ctx) -> None                 build/refresh the whole index
    #   sync(ctx, since) -> None           reindex what changed since `since`
    #   suggest(claim, ctx) -> list[str]   did-you-mean candidates
    #   version: str                       bump to force a rebuild of the index


class BaseOracle:
    """Convenience base with safe no-op lifecycle. Subclass and override."""

    name: str = "base"
    kinds: tuple[str, ...] = ()
    version: str = "1"  # bump when the index layout changes; forces a rebuild

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        return []

    def check(self, claim: Claim, ctx: Context) -> Finding:
        raise NotImplementedError

    def build(self, ctx: Context) -> None:
        return None

    def sync(self, ctx: Context, since: str | None) -> None:
        return None

    def suggest(self, claim: Claim, ctx: Context) -> list[str]:
        return []

    # --- finding helpers: keep verdict semantics in one place ---------------------------

    def accept(self, claim: Claim, reason: str) -> Finding:
        return Finding(claim, Level.ACCEPT, reason, self.name)

    def review(self, claim: Claim, reason: str, suggestions: Iterable[str] = ()) -> Finding:
        return Finding(claim, Level.REVIEW, reason, self.name, tuple(suggestions))

    def reject(self, claim: Claim, reason: str, suggestions: Iterable[str] = ()) -> Finding:
        """A proven absence. Capped to REVIEW automatically when the claim is soft."""
        return Finding(claim, Level.REJECT, reason, self.name, tuple(suggestions)).capped()

    def unverifiable(self, claim: Claim, reason: str) -> Finding:
        return Finding(claim, Level.UNVERIFIABLE, reason, self.name)

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "kinds": list(self.kinds), "version": self.version}


class OracleAPI:
    """Passed to each plugin's register(api) entry point."""

    def __init__(self) -> None:
        self._oracles: dict[str, Oracle] = {}

    def register_oracle(self, oracle: Oracle) -> None:
        if not isinstance(oracle, Oracle):
            raise TypeError(
                f"{oracle!r} does not satisfy the Oracle protocol "
                "(needs name, kinds, extract, check)"
            )
        if oracle.name in self._oracles:
            raise ValueError(f"duplicate oracle name: {oracle.name}")
        self._oracles[oracle.name] = oracle

    def oracles(self) -> dict[str, Oracle]:
        return dict(self._oracles)


def module_of_file(rel: str, roots: Sequence[str] = ("", "src", "lib")) -> str | None:
    """Dotted module name for a repo-relative Python file, or None if not a module.

    ``app/main.py`` -> ``app.main``; ``src/pkg/__init__.py`` -> ``pkg``.
    """
    if not rel.endswith(".py"):
        return None
    for root in sorted(roots, key=len, reverse=True):
        prefix = f"{root}/" if root else ""
        if root and not rel.startswith(prefix):
            continue
        body = rel[len(prefix):-3]
        parts = body.split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts or not all(p.isidentifier() for p in parts):
            continue
        return ".".join(parts)
    return None


def file_of_module(
    ctx: Context, module: str, roots: Sequence[str] = ("", "src", "lib")
) -> str | None:
    """Repo-relative file for a dotted module, or None if it is not in the repo."""
    rel = module.replace(".", "/")
    for root in roots:
        base = os.path.join(ctx.repo_root, root) if root else ctx.repo_root
        for cand in (f"{rel}.py", f"{rel}/__init__.py"):
            full = os.path.join(base, cand)
            if os.path.isfile(full):
                return (f"{root}/{cand}" if root else cand)
    return None
