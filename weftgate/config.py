"""Config load with precedence: ``WEFTGATE_*`` environment variables, then the repo's
``weftgate.toml`` or ``.weftgate.json``, then a user config, then defaults. Stack is
auto-detected but can be pinned. Standard library only.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_ORACLES = ["env_vars", "imports_lockfile", "routes_fastapi"]
BLOCK_ON_VALUES = ("reject", "review", "never")

# Directories never worth indexing. Shared by every walker in the tool.
IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".eggs",
        "dist",
        "build",
        "site-packages",
        ".next",
        ".nuxt",
        ".cache",
        ".idea",
        ".vscode",
        "target",
        "vendor",
        "coverage",
        ".turbo",
        ".parcel-cache",
    }
)


@dataclass
class Config:
    oracles: list[str] = field(default_factory=lambda: list(DEFAULT_ORACLES))
    block_on: str = "reject"  # reject | review | never
    env_declared_in: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)  # pinned stack; [] means auto-detect
    exclude: list[str] = field(default_factory=list)  # extra ignored dir names / globs
    per_oracle: dict[str, dict[str, Any]] = field(default_factory=dict)  # {oracle: {...}}
    sources: list[str] = field(default_factory=list)  # where values came from, for status

    # --- loading ------------------------------------------------------------------

    @classmethod
    def load(cls, repo_root: str, environ: dict[str, str] | None = None) -> Config:
        """Merge defaults <- user config <- repo config <- WEFTGATE_* environment."""
        env = os.environ if environ is None else environ
        cfg = cls()
        for label, path in (("user", user_config_path(env)), ("repo", repo_config_path(repo_root))):
            if path is None:
                continue
            data = _read_config_file(path)
            if data is None:
                continue
            cfg._apply(data)
            cfg.sources.append(f"{label}:{path}")
        cfg._apply_env(env)
        cfg.validate()
        return cfg

    def _apply(self, data: dict[str, Any]) -> None:
        if "oracles" in data:
            self.oracles = _str_list(data["oracles"], "oracles")
        if "block_on" in data:
            self.block_on = str(data["block_on"]).lower()
        if "env_declared_in" in data:
            self.env_declared_in = _str_list(data["env_declared_in"], "env_declared_in")
        if "stack" in data:
            self.stack = _str_list(data["stack"], "stack")
        if "exclude" in data:
            self.exclude = _str_list(data["exclude"], "exclude")
        for key, value in data.items():
            if isinstance(value, dict):
                merged = dict(self.per_oracle.get(key, {}))
                merged.update(value)
                self.per_oracle[key] = merged

    def _apply_env(self, env: dict[str, str] | os._Environ[str]) -> None:
        if env.get("WEFTGATE_ORACLES"):
            self.oracles = _split_csv(env["WEFTGATE_ORACLES"])
            self.sources.append("env:WEFTGATE_ORACLES")
        if env.get("WEFTGATE_BLOCK_ON"):
            self.block_on = env["WEFTGATE_BLOCK_ON"].strip().lower()
            self.sources.append("env:WEFTGATE_BLOCK_ON")
        if env.get("WEFTGATE_ENV_DECLARED_IN"):
            self.env_declared_in = _split_csv(env["WEFTGATE_ENV_DECLARED_IN"])
            self.sources.append("env:WEFTGATE_ENV_DECLARED_IN")
        if env.get("WEFTGATE_STACK"):
            self.stack = _split_csv(env["WEFTGATE_STACK"])
            self.sources.append("env:WEFTGATE_STACK")

    def validate(self) -> None:
        if self.block_on not in BLOCK_ON_VALUES:
            raise ValueError(
                f"invalid block_on {self.block_on!r}; expected one of {', '.join(BLOCK_ON_VALUES)}"
            )
        seen: set[str] = set()
        for name in self.oracles:
            if name in seen:
                raise ValueError(f"oracle {name!r} listed twice")
            seen.add(name)

    # --- accessors ------------------------------------------------------------------

    def oracle_config(self, name: str) -> dict[str, Any]:
        return dict(self.per_oracle.get(name, {}))

    def ignored_dirs(self) -> frozenset[str]:
        return IGNORED_DIRS | frozenset(self.exclude)

    def to_dict(self) -> dict[str, Any]:
        return {
            "oracles": list(self.oracles),
            "block_on": self.block_on,
            "env_declared_in": list(self.env_declared_in),
            "stack": list(self.stack),
            "exclude": list(self.exclude),
            "per_oracle": {k: dict(v) for k, v in sorted(self.per_oracle.items())},
            "sources": list(self.sources),
        }


# --- paths ----------------------------------------------------------------------------------------


def repo_config_path(repo_root: str) -> str | None:
    for name in ("weftgate.toml", ".weftgate.json"):
        path = os.path.join(repo_root, name)
        if os.path.isfile(path):
            return path
    return None


def user_config_path(env: dict[str, str] | os._Environ[str] | None = None) -> str | None:
    env = os.environ if env is None else env
    explicit = env.get("WEFTGATE_USER_CONFIG")
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    for name in ("weftgate.toml", "weftgate.json"):
        path = os.path.join(base, "weftgate", name)
        if os.path.isfile(path):
            return path
    return None


def find_repo_root(start: str = ".") -> str:
    """Walk up from ``start`` to the nearest directory holding ``.git`` or a weftgate config.

    Falls back to ``start`` itself. Used by the CLI when ``--repo`` is not given.
    """
    cur = os.path.abspath(start)
    if os.path.isfile(cur):
        cur = os.path.dirname(cur)
    probe = cur
    while True:
        for marker in (".git", "weftgate.toml", ".weftgate.json"):
            if os.path.exists(os.path.join(probe, marker)):
                return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


# --- file readers ---------------------------------------------------------------------------------


def _read_config_file(path: str) -> dict[str, Any] | None:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json"):
        loaded = json.loads(text) if text.strip() else {}
    else:
        loaded = load_toml(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: top level must be a table")
    section = loaded.get("weftgate", loaded)
    if not isinstance(section, dict):
        raise ValueError(f"{path}: [weftgate] must be a table")
    return dict(section)


def load_toml(text: str) -> dict[str, Any]:
    """Parse TOML with ``tomllib`` (3.11+), ``tomli`` if present, else a small
    built-in subset parser so the core stays standard-library-only on 3.10."""
    for mod_name in ("tomllib", "tomli"):
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            continue
        loaded = mod.loads(text)
        return dict(loaded)
    return _parse_toml_subset(text)


_TOML_KV = re.compile(r"^\s*([A-Za-z0-9_.\-\"']+)\s*=\s*(.+?)\s*$")


def _parse_toml_subset(text: str) -> dict[str, Any]:
    """The subset weftgate.toml uses: tables, dotted tables, strings, ints, floats,
    booleans, and single-line arrays of those. Comments and blank lines are skipped."""
    root: dict[str, Any] = {}
    current = root
    for raw in text.splitlines():
        line = _strip_toml_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = root
            for part in line[1:-1].split("."):
                key = _unquote(part.strip())
                current = current.setdefault(key, {})
            continue
        m = _TOML_KV.match(line)
        if not m:
            raise ValueError(f"cannot parse config line: {raw!r}")
        current[_unquote(m.group(1))] = _parse_toml_value(m.group(2))
    return root


def _strip_toml_comment(line: str) -> str:
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _unquote(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def _parse_toml_value(token: str) -> Any:
    token = token.strip()
    if token.startswith("["):
        if not token.endswith("]"):
            raise ValueError(f"unterminated array: {token!r}")
        return [_parse_toml_value(t) for t in _split_array(token[1:-1])]
    if token in ("true", "false"):
        return token == "true"
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    if re.fullmatch(r"[+-]?\d+", token):
        return int(token)
    if re.fullmatch(r"[+-]?\d*\.\d+", token):
        return float(token)
    raise ValueError(f"unsupported config value: {token!r}")


def _split_array(body: str) -> list[str]:
    items: list[str] = []
    cur: list[str] = []
    quote: str | None = None
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == ",":
            if "".join(cur).strip():
                items.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        items.append("".join(cur).strip())
    return items


def _str_list(value: Any, key: str) -> list[str]:
    if isinstance(value, str):
        return _split_csv(value)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [v.strip() for v in value if v.strip()]
    raise ValueError(f"{key} must be a list of strings")


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


# --- stack detection ------------------------------------------------------------------------------


def detect_stack(repo_root: str, config: Config | None = None) -> list[str]:
    """Best-effort stack detection used by ``weftgate setup`` and ``index_status``.

    Returns a sorted list of tags such as ``python``, ``node``, ``fastapi``. A
    pinned ``config.stack`` wins outright.
    """
    if config is not None and config.stack:
        return sorted(set(config.stack))
    found: set[str] = set()
    root_files = set(_listdir(repo_root))
    if root_files & {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "Pipfile",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
    }:
        found.add("python")
    if root_files & {"package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}:
        found.add("node")
    if root_files & {"go.mod"}:
        found.add("go")
    if root_files & {"Cargo.toml"}:
        found.add("rust")
    if root_files & {"Gemfile"}:
        found.add("ruby")
    if _mentions(
        repo_root,
        (
            "pyproject.toml",
            "requirements.txt",
            "poetry.lock",
            "uv.lock",
            "Pipfile",
            "Pipfile.lock",
            "setup.py",
            "setup.cfg",
        ),
        "fastapi",
    ):
        found.update({"python", "fastapi"})
    if _mentions(repo_root, ("package.json",), '"express"'):
        found.update({"node", "express"})
    if _mentions(repo_root, ("package.json",), '"next"'):
        found.update({"node", "nextjs"})
    if _mentions(
        repo_root, ("pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock"), "django"
    ):
        found.update({"python", "django"})
    if _mentions(
        repo_root, ("pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock"), "flask"
    ):
        found.update({"python", "flask"})
    return sorted(found)


def _listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


def _mentions(repo_root: str, names: tuple[str, ...], needle: str) -> bool:
    """Whether ``needle`` appears as a whole token (so ``routes_fastapi`` is not ``fastapi``)."""
    pattern = re.compile(rf"(?<![\w-]){re.escape(needle.strip(chr(34)))}(?![\w-])", re.I)
    for name in names:
        path = os.path.join(repo_root, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                if pattern.search(fh.read(2_000_000)):
                    return True
        except OSError:
            continue
    return False
