"""Discover oracles from installed entry points, the built-in set, and config
dotted paths. Holds nothing itself: ``load_oracles`` returns the enabled set in
config order, which is the order the gate runs them in (determinism)."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from importlib import metadata
from typing import Any

from .config import Config
from .oracle import Oracle, OracleAPI
from .oracles import BUILTIN

ENTRY_POINT_GROUP = "weft.oracles"
Registrar = Callable[[OracleAPI], None]


def entry_point_registrars() -> dict[str, metadata.EntryPoint]:
    try:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # pragma: no cover - a broken distribution must not kill the gate
        return {}
    return {ep.name: ep for ep in eps}


def available_oracles() -> list[str]:
    """Names that can be enabled by bare name: entry points plus built-ins."""
    return sorted(set(entry_point_registrars()) | set(BUILTIN))


def resolve_registrar(name: str) -> Registrar:
    """Turn a config entry into the ``register(api)`` callable it names."""
    eps = entry_point_registrars()
    if name in eps:
        loaded = eps[name].load()
        return _as_registrar(loaded, name)
    if name in BUILTIN:
        return _as_registrar(_load_dotted(BUILTIN[name]), name)
    if "." in name or ":" in name:
        return _as_registrar(_load_dotted(name), name)
    raise ValueError(
        f"unknown oracle {name!r}: not an installed entry point, a built-in, or a dotted path "
        f"(available: {', '.join(available_oracles())})"
    )


def load_oracles(config: Config) -> dict[str, Oracle]:
    api = OracleAPI()
    for name in config.oracles:
        resolve_registrar(name)(api)
    return api.oracles()


def _as_registrar(obj: Any, name: str) -> Registrar:
    if callable(obj):
        return obj  # type: ignore[no-any-return]
    raise TypeError(f"oracle entry {name!r} did not resolve to a callable register(api)")


def _load_dotted(path: str) -> Any:
    """``pkg.mod:attr`` or ``pkg.mod.attr`` or ``pkg.mod`` (implies ``register``)."""
    mod_name, _, attr = path.partition(":")
    if not attr:
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            mod_name, _, attr = mod_name.rpartition(".")
            if not mod_name:
                raise
            mod = importlib.import_module(mod_name)
        else:
            attr = "register"
    else:
        mod = importlib.import_module(mod_name)
    try:
        return getattr(mod, attr)
    except AttributeError as exc:
        raise ValueError(f"{path!r}: module {mod.__name__!r} has no {attr!r}") from exc
