"""imports_lockfile: every third-party top-level import must resolve to the
lockfile (or manifest) or the standard library. A phantom package -> REJECT.
This is the slopsquatting guard.

Tier 0, standard library only. Python and Node to start.

Verdict ladder (Python):
  standard library                              -> ACCEPT
  the repo's own package / module               -> ACCEPT
  lockfile name (normalised) or known alias     -> ACCEPT   (PyYAML -> yaml, etc.)
  installed here, and its distribution is locked-> ACCEPT   (authoritative import name)
  installed here but not in any lockfile        -> REVIEW   (works on this machine only)
  a locked distribution's name contains it      -> REVIEW   (probably its import name)
  optional import (inside try/except ImportError)-> REVIEW  (the code handles absence)
  dynamic import with a non-literal name        -> REVIEW
  otherwise                                     -> REJECT   with did-you-mean
  no lockfile or manifest for that language     -> UNVERIFIABLE

Lockfiles and manifests read: poetry.lock, uv.lock, Pipfile.lock, Pipfile,
requirements*.txt, pyproject.toml, setup.cfg, environment.yml; package-lock.json,
npm-shrinkwrap.json, pnpm-lock.yaml, yarn.lock, package.json (with workspaces).
"""

from __future__ import annotations

import ast
import configparser
import json
import os
import re
import sys
from collections.abc import Iterable
from importlib import metadata
from typing import Any

from ..change import Change, Region
from ..config import load_toml
from ..oracle import BaseOracle, Context, OracleAPI, soften_docs
from ..suggest import did_you_mean
from ..types import Claim, Finding, Location

_PY_SUFFIXES = (".py", ".pyi")
_JS_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts", ".vue", ".svelte")
_PY_MANIFESTS = (
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Pipfile",
    "pyproject.toml",
    "setup.cfg",
    "environment.yml",
    "environment.yaml",
)
_NODE_MANIFESTS = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package.json",
)
# Lockfiles enumerate the whole resolved tree, so a name absent from one is a proven
# absence. Manifests list direct dependencies only; a transitive import (starlette via
# fastapi) is legitimately absent from them.
_LOCKFILES = (
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
)
_PINNED = re.compile(r"^\s*[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?\s*==")
# Import specs a framework resolves itself; keyed by the package whose presence enables them.
_FRAMEWORK_ALIASES: dict[str, tuple[str, ...]] = {
    "@docusaurus/core": ("@site/", "@theme/", "@generated/", "@docusaurus/"),
    "@sveltejs/kit": ("$lib/", "$app/", "$env/", "$service-worker"),
    "nuxt": ("#app", "#imports", "#components"),
    "astro": ("astro:",),
    "vite": ("virtual:",),
    "next": ("next/",),
    "@angular/core": ("@angular/",),
}
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EGG = re.compile(r"[#&]egg=([A-Za-z0-9._-]+)")
_LOCK_NAME = re.compile(r'^name\s*=\s*"([^"]+)"', re.MULTILINE)
_PNPM_PKG = re.compile(r"^\s{2}/?'?(@?[^@'\s/]+(?:/[^@'\s/]+)?)@")
_PNPM_DEP = re.compile(r"^\s{4,}'?(@?[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)?)'?:\s*$")
_YARN_KEY = re.compile(r'^"?((?:@[^/"\s]+/)?[^@"\s]+)@')
_CONDA_DEP = re.compile(r"^\s*-\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")

# Well-known cases where the import name differs from the distribution name.
# import name -> normalised distribution names that provide it.
_ALIASES: dict[str, tuple[str, ...]] = {
    "yaml": ("pyyaml",),
    "sklearn": ("scikit_learn",),
    "PIL": ("pillow",),
    "bs4": ("beautifulsoup4",),
    "dateutil": ("python_dateutil",),
    "psycopg2": ("psycopg2_binary",),
    "cv2": ("opencv_python", "opencv_python_headless", "opencv_contrib_python"),
    "attr": ("attrs",),
    "attrs": ("attrs",),
    "msgpack": ("msgpack_python", "msgpack"),
    "dotenv": ("python_dotenv",),
    "google": (
        "protobuf",
        "google_api_core",
        "google_auth",
        "google_cloud_storage",
        "googleapis_common_protos",
    ),
    "jose": ("python_jose",),
    "jwt": ("pyjwt",),
    "rest_framework": ("djangorestframework",),
    "pkg_resources": ("setuptools",),
    "multipart": ("python_multipart",),
    "faker": ("faker",),
    "pymysql": ("pymysql",),
    "MySQLdb": ("mysqlclient",),
    "Crypto": ("pycryptodome",),
    "Cryptodome": ("pycryptodomex",),
    "OpenSSL": ("pyopenssl",),
    "magic": ("python_magic",),
    "ruamel": ("ruamel_yaml",),
    "zope": ("zope_interface",),
    "backports": ("backports_zoneinfo",),
    "git": ("gitpython",),
    "github": ("pygithub",),
    "gi": ("pygobject",),
    "wx": ("wxpython",),
    "serial": ("pyserial",),
    "usb": ("pyusb",),
    "docx": ("python_docx",),
    "pptx": ("python_pptx",),
    "fitz": ("pymupdf",),
    "cairo": ("pycairo",),
    "Levenshtein": ("python_levenshtein", "levenshtein"),
    "slugify": ("python_slugify",),
    "markdown": ("markdown",),
    "nacl": ("pynacl",),
    "snowflake": ("snowflake_connector_python",),
    "websocket": ("websocket_client",),
    "socks": ("pysocks",),
    "ldap": ("python_ldap",),
    "memcache": ("python_memcached",),
    "playhouse": ("peewee",),
    "flask_sqlalchemy": ("flask_sqlalchemy",),
    "sqlalchemy": ("sqlalchemy",),
    "typing_extensions": ("typing_extensions",),
    "importlib_metadata": ("importlib_metadata",),
    "tree_sitter": ("tree_sitter",),
    "mcp": ("mcp",),
    "pydantic_settings": ("pydantic_settings",),
    "azure": ("azure_core", "azure_identity", "azure_storage_blob"),
    "win32api": ("pywin32",),
    "win32con": ("pywin32",),
    "pythoncom": ("pywin32",),
    "googleapiclient": ("google_api_python_client",),
    "google_auth_oauthlib": ("google_auth_oauthlib",),
    "apiclient": ("google_api_python_client",),
    "oauth2client": ("oauth2client",),
    "sendgrid": ("sendgrid",),
    "boto": ("boto",),
    "botocore": ("botocore",),
    "aiohttp": ("aiohttp",),
    "jinja2": ("jinja2",),
    "markupsafe": ("markupsafe",),
    "werkzeug": ("werkzeug",),
    "click": ("click",),
    "Xlib": ("python_xlib",),
    "yattag": ("yattag",),
    "pkgutil_resolve_name": ("pkgutil_resolve_name",),
}

_NODE_BUILTINS = frozenset(
    {
        "assert",
        "async_hooks",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "domain",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "inspector",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "repl",
        "stream",
        "string_decoder",
        "sys",
        "timers",
        "tls",
        "trace_events",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "wasi",
        "worker_threads",
        "zlib",
        "test",
        "sqlite",
    }
)
_LOCAL_PREFIXES = (".", "/", "#", "~", "@/", "$", "src/", "~/")

_JS_IMPORT = re.compile(
    r"""(?:^|[^\w$.])(?:import|export)\s+(?:[\w*{}\s,$]+?\s+from\s+)?['"]([^'"]+)['"]"""
)
_JS_IMPORT_BARE = re.compile(r"""(?:^|[^\w$.])import\s*['"]([^'"]+)['"]""")
_JS_REQUIRE = re.compile(r"""(?:^|[^\w$.])(?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_JS_DYNAMIC = re.compile(r"""(?:^|[^\w$.])(?:require|import)\s*\(\s*(?!['"])[^)]""")
_PY_DYNAMIC = re.compile(r"(?:importlib\.import_module|__import__)\(\s*(?![\"'])[^)]")
_PY_LITERAL_DYNAMIC = re.compile(r"(?:importlib\.import_module|__import__)\(\s*['\"]([\w.]+)['\"]")
_PY_IMPORT_LINE = re.compile(r"^\s*(?:import\s+([\w., ]+)|from\s+([\w.]+)\s+import\b)")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _stdlib_names() -> frozenset[str]:
    names = set(getattr(sys, "stdlib_module_names", ()))
    names |= set(sys.builtin_module_names)
    names |= {"__future__", "__main__", "_typeshed", "typing_extensions_stub"}
    names.discard("typing_extensions_stub")
    return frozenset(names)


_STDLIB = _stdlib_names()
_ENV_DISTS: dict[str, list[str]] | None = None
_ENV_DIST_NAMES: set[str] | None = None


def _load_env_metadata() -> None:
    """Map import names to the installed distributions that provide them, and record
    every installed distribution name. Built from each distribution's own metadata
    (``top_level.txt``, else the RECORD file list), which is what newer Pythons do
    inside ``packages_distributions``; doing it here keeps 3.10 identical to 3.13.
    Only ever used to *soften* a verdict or to confirm the environment matches the
    project, never to produce a reject on its own."""
    global _ENV_DISTS, _ENV_DIST_NAMES
    if _ENV_DISTS is not None:
        return
    mapping: dict[str, set[str]] = {}
    names: set[str] = set()
    try:
        dists = list(metadata.distributions())
    except Exception:  # noqa: BLE001 - a broken site-packages must not matter
        dists = []
    for dist in dists:
        try:
            dist_name = str(dist.metadata["Name"] or "")
        except Exception:  # noqa: BLE001
            continue
        if not dist_name:
            continue
        names.add(norm(dist_name))
        tops: set[str] = set()
        try:
            top_level = dist.read_text("top_level.txt")
        except Exception:  # noqa: BLE001
            top_level = None
        if top_level:
            tops = {ln.strip() for ln in top_level.splitlines() if ln.strip()}
        else:
            try:
                files = dist.files or []
            except Exception:  # noqa: BLE001
                files = []
            for f in files:
                parts = str(f).replace("\\", "/").split("/")
                head = parts[0]
                if (
                    not head
                    or head.endswith((".dist-info", ".egg-info"))
                    or head.startswith(("__pycache__", "..", "__editable__"))
                ):
                    continue
                if len(parts) == 1:
                    head = head.split(".")[0]
                if head.isidentifier():
                    tops.add(head)
        for top in tops:
            mapping.setdefault(top, set()).add(dist_name)
    _ENV_DISTS = {k: sorted(v) for k, v in mapping.items()}
    _ENV_DIST_NAMES = names


def _installed_dists(name: str) -> list[str]:
    """Distributions installed in *this* interpreter that provide import ``name``."""
    _load_env_metadata()
    return list((_ENV_DISTS or {}).get(name, []))


def _installed_dist_names() -> set[str]:
    _load_env_metadata()
    return set(_ENV_DIST_NAMES or set())


class ImportsLockfileOracle(BaseOracle):
    name = "imports_lockfile"
    kinds: tuple[str, ...] = ("import",)
    version = "4"

    _PROVIDED = (
        "lang TEXT NOT NULL, name TEXT NOT NULL, dist TEXT NOT NULL, "
        "source TEXT NOT NULL, core INTEGER NOT NULL"
    )
    # kind: "root" (importable from a source root), "nested" (a package dir deeper in the
    # tree, importable only with sys.path help), "alias" (tsconfig paths / baseUrl / dir)
    _LOCAL = "lang TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL"
    _SOURCES = "lang TEXT NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL"

    # --- index -----------------------------------------------------------------

    def build(self, ctx: Context) -> None:
        provided: list[tuple[str, str, str, str, int]] = []
        local: list[tuple[str, str, str, str]] = []
        sources: list[tuple[str, str, str]] = []
        files = ctx.files()
        roots: set[str] = {"", "src", "lib"}
        for rel in files:
            base = os.path.basename(rel)
            lang = _manifest_lang(base)
            if lang is None:
                if base in ("tsconfig.json", "jsconfig.json") or (
                    base.startswith("tsconfig.") and base.endswith(".json")
                ):
                    text = ctx.read_text(rel)
                    if text is not None:
                        for pattern in _tsconfig_aliases(text, ctx, rel):
                            local.append(("node", pattern, "alias", rel))
                continue
            text = ctx.read_text(rel)
            if text is None:
                continue
            dists, own = _parse_manifest(base, text, ctx, rel)
            core = _core_dists(base, text) if lang == "python" else set()
            sources.append((lang, rel, _source_kind(base, text)))
            provided.extend(
                (lang, norm(d) if lang == "python" else d, d, rel, 1 if d in core else 0)
                for d in dists
            )
            local.extend((lang, o, "root", rel) for o in own)
            if lang == "python":
                # Every Python manifest marks a project root (a monorepo's backend/, an
                # examples/* app): its directory and src/ become source roots too.
                project_dir = os.path.dirname(rel)
                roots.add(project_dir)
                roots.add(f"{project_dir}/src" if project_dir else "src")
                if base in ("pyproject.toml", "setup.cfg"):
                    declared = _python_roots(base, text)
                    roots |= {f"{project_dir}/{r}" if project_dir else r for r in declared}
        for name in _local_python_names(files, roots):
            local.append(("python", name, "root", "filesystem"))
        for name in _nested_python_packages(files, roots):
            local.append(("python", name, "nested", "filesystem"))
        for name in _top_level_dirs(files):
            local.append(("node", name, "dir", "filesystem"))
        ns = ctx.store.namespace(self.name)
        ns.rebuild("provided", self._PROVIDED, sorted(set(provided)), indexes=["lang, name"])
        ns.rebuild("local", self._LOCAL, sorted(set(local)), indexes=["lang, name"])
        ns.rebuild("sources", self._SOURCES, sorted(set(sources)), indexes=["lang"])

    def sync(self, ctx: Context, since: str | None) -> None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("provided"):
            self.build(ctx)
            return
        changed = ctx.store.sync_files(since)
        # Manifests are few; any manifest or top-level layout change means a cheap
        # full rebuild is the simplest correct answer.
        if any(
            _manifest_lang(os.path.basename(p))
            or p.count("/") <= 1
            or p.endswith(("__init__.py", "tsconfig.json", "jsconfig.json"))
            for p in changed
        ):
            self.build(ctx)

    def _index(self, ctx: Context, lang: str) -> _Index | None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("provided") or not ns.exists("sources"):
            return None
        rows = ns.query(
            "SELECT source, kind FROM {t:sources} WHERE lang=? ORDER BY source", (lang,)
        )
        sources = [str(r[0]) for r in rows]
        lockfiles = [str(r[0]) for r in rows if str(r[1]) == "lockfile"]
        provided: dict[str, list[tuple[str, str]]] = {}
        core: dict[str, set[str]] = {}
        for name, dist, source, is_core in ns.query(
            "SELECT name, dist, source, core FROM {t:provided} WHERE lang=? "
            "ORDER BY name, dist, source",
            (lang,),
        ):
            provided.setdefault(str(name), []).append((str(dist), str(source)))
            if int(is_core):
                core.setdefault(str(source), set()).add(str(name))
        local: set[str] = set()
        nested: set[str] = set()
        aliases: set[str] = set()
        dirs: set[str] = set()
        for name, kind in ns.query("SELECT name, kind FROM {t:local} WHERE lang=?", (lang,)):
            match str(kind):
                case "root":
                    local.add(str(name))
                case "nested":
                    nested.add(str(name))
                case "alias":
                    aliases.add(str(name))
                case "dir":
                    dirs.add(str(name))
        return _Index(lang, sources, provided, local, nested, aliases, dirs, lockfiles, core)

    # --- extract ---------------------------------------------------------------

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        claims: list[Claim] = []
        for region in change.added_regions():
            if region.file.endswith(_PY_SUFFIXES):
                claims.extend(soften_docs(_extract_python(region), region.file))
            elif region.file.endswith(_JS_SUFFIXES):
                claims.extend(soften_docs(_extract_js(region), region.file))
        return claims

    # --- check -----------------------------------------------------------------

    def check(self, claim: Claim, ctx: Context) -> Finding:
        lang = str(claim.attrs.get("lang") or _lang_of_subject(claim))
        index = self._index(ctx, lang)
        if index is None:
            return self.unverifiable(claim, "lockfile index not built")
        if claim.subject == "<dynamic>":
            return self.review(claim, "import with a non-literal module name; cannot resolve")
        top = str(claim.attrs.get("top") or _top_level(claim.subject, lang))
        optional = bool(claim.attrs.get("optional"))
        # The standard library and Node built-ins never need a lockfile.
        if lang == "python" and top in _STDLIB:
            return self.accept(claim, "standard library")
        if lang == "node" and (top in _NODE_BUILTINS or top.startswith("node:")):
            return self.accept(claim, "Node built-in module")
        if not index.sources:
            looked = _PY_MANIFESTS if lang == "python" else _NODE_MANIFESTS
            return self.unverifiable(
                claim, f"no {lang} lockfile or manifest found (looked for {', '.join(looked)})"
            )
        if lang == "node":
            return self._check_node(claim, top, index, ctx, optional)
        return self._check_python(claim, top, index, optional)

    def _check_python(self, claim: Claim, top: str, index: _Index, optional: bool) -> Finding:
        if top in _STDLIB:
            return self.accept(claim, "standard library")
        if top in index.local:
            return self.accept(claim, "the repo's own package")
        hit = index.provided.get(norm(top))
        if hit:
            return self.accept(claim, f"in {hit[0][1]} as {hit[0][0]}")
        for alias in _ALIASES.get(top, ()):
            hit = index.provided.get(alias)
            if hit:
                return self.accept(claim, f"in {hit[0][1]} as {hit[0][0]} (provides {top})")
        env_dists = _installed_dists(top)
        for dist in env_dists:
            hit = index.provided.get(norm(dist))
            if hit:
                return self.accept(
                    claim,
                    f"in {hit[0][1]} as {hit[0][0]} (installed metadata says it provides {top})",
                )
        if env_dists:
            return self.review(
                claim,
                f"import {top!r} is installed here (as {', '.join(env_dists)}) but is not in "
                f"any lockfile or manifest; add it so it works off this machine",
            )
        related = sorted(d for d in index.dist_names() if _probably_provides(d, top))
        if related:
            return self.review(
                claim,
                f"import {top!r} is not in the lockfile by that name; it may be provided "
                f"by {', '.join(related[:3])}",
                related[:3],
            )
        if optional:
            return self.review(
                claim,
                f"optional import {top!r} (guarded by try/except) is not in the lockfile",
                did_you_mean(top, index.dist_names() | index.local),
            )
        if top in index.nested:
            return self.review(
                claim,
                f"import {top!r} matches a package directory deeper in the repo; it is "
                f"importable only if that directory is on sys.path (declare the source "
                f"root in pyproject.toml to make this exact)",
            )
        sugg = did_you_mean(top, index.dist_names() | index.local)
        if not index.has_lockfile_for(claim.location.file):
            # A partially matching environment cannot prove the complete dependency tree.
            hint = f"; did you mean {sugg[0]}?" if sugg else ""
            return self.review(
                claim,
                f"import {top!r} is not a declared dependency in "
                f"{', '.join(index.sources)}; it may be transitive (add a lockfile "
                f"such as uv.lock or poetry.lock to make this exact){hint}",
                sugg,
            )
        where = ", ".join(index.lockfiles or index.sources)
        reason = f"import {top!r} is not in {where} or the standard library (slopsquat risk)"
        return self.reject(claim, reason, sugg)

    def _check_node(
        self, claim: Claim, top: str, index: _Index, ctx: Context, optional: bool
    ) -> Finding:
        if top in _NODE_BUILTINS or top.startswith("node:"):
            return self.accept(claim, "Node built-in module")
        hit = index.provided.get(top)
        if hit:
            return self.accept(claim, f"in {hit[0][1]}")
        if top in index.local:
            return self.accept(claim, "a workspace package of this repo")
        spec = claim.subject
        alias = _matching_alias(spec, index.aliases)
        if alias is not None:
            return self.accept(claim, f"resolved via tsconfig paths ({alias})")
        for enabler, prefixes in _FRAMEWORK_ALIASES.items():
            if enabler in index.provided and spec.startswith(prefixes):
                return self.accept(claim, f"a {enabler} framework alias")
        if _base_url_hit(spec, index.aliases, ctx):
            return self.accept(claim, "resolved via tsconfig baseUrl")
        if top.split("/")[0] in index.dirs and not top.startswith("@"):
            return self.review(
                claim,
                f"{spec!r} matches a directory in the repo; probably a bundler path alias "
                f"weftgate could not confirm (declare it in tsconfig paths to make it exact)",
            )
        if os.path.isfile(os.path.join(ctx.repo_root, "node_modules", top, "package.json")):
            return self.review(
                claim,
                f"package {top!r} is in node_modules but not in any lockfile or "
                f"package.json; add it so it works off this machine",
            )
        if optional:
            return self.review(
                claim,
                f"optional import {top!r} is not in the lockfile",
                did_you_mean(top, index.dist_names() | index.local),
            )
        sugg = did_you_mean(top, index.dist_names() | index.local)
        scope = top.split("/")[0] if top.startswith("@") and "/" in top else ""
        if scope and any(d.startswith(scope + "/") for d in index.dist_names()):
            return self.review(
                claim,
                f"package {top!r} is not in the lockfile, but other {scope}/* packages "
                f"are; probably a framework-resolved sub-path rather than a phantom",
                sugg,
            )
        if not index.has_lockfile_for(claim.location.file):
            hint = f"; did you mean {sugg[0]}?" if sugg else ""
            return self.review(
                claim,
                f"package {top!r} is not a declared dependency in "
                f"{', '.join(index.sources)}; it may be transitive (commit a lockfile "
                f"to make this exact){hint}",
                sugg,
            )
        where = ", ".join(index.lockfiles)
        reason = f"package {top!r} is not in {where} (slopsquat risk)"
        return self.reject(claim, reason, sugg)

    def suggest(self, claim: Claim, ctx: Context) -> list[str]:
        lang = str(claim.attrs.get("lang") or _lang_of_subject(claim))
        index = self._index(ctx, lang)
        if index is None:
            return []
        return did_you_mean(_top_level(claim.subject, lang), index.dist_names() | index.local)


class _Index:
    def __init__(
        self,
        lang: str,
        sources: list[str],
        provided: dict[str, list[tuple[str, str]]],
        local: set[str],
        nested: set[str] | None = None,
        aliases: set[str] | None = None,
        dirs: set[str] | None = None,
        lockfiles: list[str] | None = None,
        core: dict[str, set[str]] | None = None,
    ) -> None:
        self.lang = lang
        self.sources = sources
        self.provided = provided
        self.local = local
        self.nested = nested or set()
        self.aliases = aliases or set()  # tsconfig path patterns, plus "baseUrl:<dir>"
        self.dirs = dirs or set()
        self.lockfiles = lockfiles or []  # sources that enumerate the whole resolved tree
        self.core = core or {}  # manifest -> mandatory (non-optional, non-dev) dist names

    def has_lockfile_for(self, from_file: str) -> bool:
        """Only a lock in the importing file's nearest project proves absence.

        A nested app's lock cannot establish the root app's dependency tree.
        Workspace inheritance we cannot establish conservatively reviews.
        """
        parent = os.path.dirname(from_file)
        candidates = {
            os.path.dirname(source)
            for source in self.sources
            if not os.path.dirname(source)
            or parent == os.path.dirname(source)
            or parent.startswith(os.path.dirname(source) + "/")
        }
        if not candidates:
            return False
        nearest = max(candidates, key=len)
        return any(os.path.dirname(source) == nearest for source in self.lockfiles)

    def dist_names(self) -> set[str]:
        return {d for hits in self.provided.values() for d, _ in hits}


# --- extraction -----------------------------------------------------------------------------------


def _extract_python(region: Region) -> list[Claim]:
    text = region.text()
    lines = region.lines()
    line_map = {} if region.whole_file else {i + 1: ln for i, (ln, _) in enumerate(lines)}
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return _extract_python_regex(region)
    claims: list[Claim] = []
    optional_lines = _optional_import_lines(tree)
    for node in ast.walk(tree):
        names: list[tuple[str, int, int]] = []
        if isinstance(node, ast.Import):
            names = [(a.name, node.lineno, node.col_offset) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            names = [(node.module, node.lineno, node.col_offset)]
        elif isinstance(node, ast.Call):
            fn = _dotted(node.func)
            if fn in ("importlib.import_module", "__import__"):
                arg = node.args[0] if node.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names = [(arg.value, node.lineno, node.col_offset)]
                elif arg is not None:
                    claims.append(
                        Claim(
                            "import",
                            "<dynamic>",
                            Location(
                                region.file,
                                line_map.get(node.lineno, node.lineno),
                                node.col_offset + 1,
                            ),
                            {"lang": "python"},
                            hard=False,
                        )
                    )
                    continue
        for mod, lineno, col in names:
            if region.whole_file or lineno in line_map:
                claims.append(
                    Claim(
                        "import",
                        mod,
                        Location(region.file, line_map.get(lineno, lineno), col + 1),
                        {
                            "lang": "python",
                            "top": mod.split(".")[0],
                            **({"optional": True} if lineno in optional_lines else {}),
                        },
                    )
                )
    return _dedupe(claims)


def _optional_import_lines(tree: ast.AST) -> set[int]:
    """Lines of imports inside ``try:`` whose handlers catch ImportError."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        guarded = False
        for h in node.handlers:
            if h.type is None:
                guarded = True
            else:
                names = [h.type] if not isinstance(h.type, ast.Tuple) else list(h.type.elts)
                if any(
                    (_dotted(n) or "").split(".")[-1]
                    in ("ImportError", "ModuleNotFoundError", "Exception")
                    for n in names
                ):
                    guarded = True
        if not guarded:
            continue
        for stmt in node.body:
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Import | ast.ImportFrom):
                    out.add(sub.lineno)
    return out


def _extract_python_regex(region: Region) -> list[Claim]:
    claims: list[Claim] = []
    for lineno, text in region.lines():
        if _COMMENT.match(text):
            continue
        m = _PY_IMPORT_LINE.match(text)
        if m:
            mods = [x.strip().split(" as ")[0].strip() for x in (m.group(1) or "").split(",")]
            if m.group(2):
                mods = [m.group(2)]
            for mod in mods:
                if mod and not mod.startswith("."):
                    claims.append(
                        Claim(
                            "import",
                            mod,
                            Location(region.file, lineno, 1),
                            {"lang": "python", "top": mod.split(".")[0]},
                        )
                    )
        for lm in _PY_LITERAL_DYNAMIC.finditer(text):
            loc = Location(region.file, lineno, lm.start() + 1)
            claims.append(
                Claim(
                    "import", lm.group(1), loc, {"lang": "python", "top": lm.group(1).split(".")[0]}
                )
            )
        if _PY_DYNAMIC.search(text):
            claims.append(
                Claim(
                    "import",
                    "<dynamic>",
                    Location(region.file, lineno, 1),
                    {"lang": "python"},
                    hard=False,
                )
            )
    return _dedupe(claims)


def _extract_js(region: Region) -> list[Claim]:
    claims: list[Claim] = []
    for lineno, text in region.lines():
        if _COMMENT.match(text):
            continue
        specs: list[tuple[str, int]] = []
        for pat in (_JS_IMPORT, _JS_IMPORT_BARE, _JS_REQUIRE):
            specs.extend((m.group(1), m.start(1)) for m in pat.finditer(text))
        seen: set[str] = set()
        for spec, col in sorted(specs, key=lambda t: t[1]):
            if spec in seen:
                continue
            seen.add(spec)
            if spec.startswith(_LOCAL_PREFIXES) or (":" in spec and not spec.startswith("node:")):
                continue
            top = _top_level(spec, "node")
            claims.append(
                Claim(
                    "import",
                    spec,
                    Location(region.file, lineno, col + 1),
                    {"lang": "node", "top": top},
                )
            )
        if not specs and _JS_DYNAMIC.search(text):
            claims.append(
                Claim(
                    "import",
                    "<dynamic>",
                    Location(region.file, lineno, 1),
                    {"lang": "node"},
                    hard=False,
                )
            )
    return _dedupe(claims)


def _dedupe(claims: list[Claim]) -> list[Claim]:
    seen: set[tuple[str, int]] = set()
    out: list[Claim] = []
    for c in claims:
        key = (c.subject, c.location.line)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _top_level(spec: str, lang: str) -> str:
    if lang == "node":
        if spec.startswith("node:"):
            return spec
        parts = spec.split("/")
        return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]
    return spec.split(".")[0]


def _lang_of_subject(claim: Claim) -> str:
    f = claim.location.file
    if f.endswith(_JS_SUFFIXES) or claim.subject.startswith("@") or "/" in claim.subject:
        return "node"
    return "python"


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _probably_provides(dist: str, top: str) -> bool:
    """A locked distribution that plausibly provides import ``top`` under another
    name: ``python-dateutil`` -> dateutil, ``PyYAML`` -> yaml, ``foo-python`` -> foo.
    Deliberately tight so a typo of a real name never softens to review."""
    d, t = norm(dist), norm(top)
    if len(t) < 3 or d == t:
        return False
    tokens = [x for x in re.split(r"[_]+", d) if x]
    if t in tokens and len(tokens) > 1:
        return True
    return d in (f"py{t}", f"python_{t}", f"{t}_python", f"{t}_py", f"{t}3", f"{t}2")


# --- manifests ------------------------------------------------------------------------------------


def _nearest_project_dir(from_file: str, core: dict[str, set[str]]) -> str:
    """Directory of the manifest closest above ``from_file`` ('' for the repo root)."""
    dirs = {os.path.dirname(source) for source in core}
    parts = from_file.replace(os.sep, "/").split("/")[:-1]
    for depth in range(len(parts), -1, -1):
        rel = "/".join(parts[:depth])
        if rel in dirs:
            return rel
    return ""


def _core_dists(base: str, text: str) -> set[str]:
    """Mandatory dependencies only: what must be installed for the project to run."""
    try:
        match base:
            case "pyproject.toml":
                data = load_toml(text)
                out: set[str] = set()
                project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
                for req in project.get("dependencies", []) or []:
                    if isinstance(req, str) and (n := _req_name(req)):
                        out.add(n)
                tool = data.get("tool", {}) if isinstance(data.get("tool"), dict) else {}
                poetry = tool.get("poetry", {}) if isinstance(tool.get("poetry"), dict) else {}
                out |= {k for k in (poetry.get("dependencies", {}) or {}) if k != "python"}
                return out
            case "setup.cfg":
                cp = configparser.ConfigParser()
                cp.read_string(text)
                if cp.has_option("options", "install_requires"):
                    return {
                        n
                        for ln in cp.get("options", "install_requires").splitlines()
                        if (n := _req_name(ln))
                    }
                return set()
            case "Pipfile":
                return set(load_toml(text).get("packages", {}) or {})
            case _:
                if base.startswith("requirements") and base.endswith(".txt"):
                    return _parse_requirements(text)
    except (ValueError, TypeError, AttributeError, configparser.Error):
        return set()
    return set()


def _source_kind(base: str, text: str) -> str:
    """'lockfile' when the file enumerates the resolved tree (or pins every line),
    else 'manifest'."""
    if base in _LOCKFILES:
        return "lockfile"
    if base.startswith("requirements") and base.endswith(".txt"):
        lines = [
            ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "-"))
        ]
        if lines and all(_PINNED.match(ln) for ln in lines):
            return "lockfile"
    return "manifest"


def _manifest_lang(base: str) -> str | None:
    if base in _PY_MANIFESTS or (base.startswith("requirements") and base.endswith(".txt")):
        return "python"
    if base in _NODE_MANIFESTS:
        return "node"
    return None


def _parse_manifest(base: str, text: str, ctx: Context, rel: str) -> tuple[set[str], set[str]]:
    """(distributions provided, the project's own names) from one manifest."""
    try:
        match base:
            case "poetry.lock" | "uv.lock":
                return set(_LOCK_NAME.findall(text)), set()
            case "Pipfile.lock":
                data = json.loads(text)
                return set(data.get("default", {})) | set(data.get("develop", {})), set()
            case "Pipfile":
                data = load_toml(text)
                return set(data.get("packages", {})) | set(data.get("dev-packages", {})), set()
            case "pyproject.toml":
                return _parse_pyproject(load_toml(text))
            case "setup.cfg":
                return _parse_setup_cfg(text), set()
            case "environment.yml" | "environment.yaml":
                return {
                    m.group(1)
                    for line in text.splitlines()
                    if (m := _CONDA_DEP.match(line)) and m.group(1) not in ("pip", "python")
                }, set()
            case "package-lock.json" | "npm-shrinkwrap.json":
                return _parse_package_lock(json.loads(text))
            case "pnpm-lock.yaml":
                return _parse_pnpm(text), set()
            case "yarn.lock":
                return _parse_yarn(text), set()
            case "package.json":
                return _parse_package_json(json.loads(text), ctx, rel)
            case _:
                if base.startswith("requirements"):
                    return _parse_requirements(text), set()
    except (ValueError, TypeError, AttributeError, configparser.Error) as exc:
        raise ValueError(f"cannot parse dependency metadata {rel}: {exc}") from exc
    return set(), set()


def _req_name(line: str) -> str | None:
    egg = _EGG.search(line)
    line = line.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return egg.group(1) if egg else None
    if "://" in line and "@" not in line.split("://")[0]:
        return egg.group(1) if egg else None
    m = _REQ_NAME.match(line)
    return m.group(1) if m else None


def _parse_requirements(text: str) -> set[str]:
    out: set[str] = set()
    for raw in text.splitlines():
        name = _req_name(raw)
        if name:
            out.add(name)
    return out


def _parse_pyproject(data: dict[str, Any]) -> tuple[set[str], set[str]]:
    dists: set[str] = set()
    own: set[str] = set()
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    if isinstance(project.get("name"), str):
        own.add(norm(project["name"]))
    for req in project.get("dependencies", []) or []:
        if isinstance(req, str) and (n := _req_name(req)):
            dists.add(n)
    for reqs in (project.get("optional-dependencies", {}) or {}).values():
        for req in reqs or []:
            if isinstance(req, str) and (n := _req_name(req)):
                dists.add(n)
    for reqs in (data.get("dependency-groups", {}) or {}).values():
        for req in reqs or []:
            if isinstance(req, str) and (n := _req_name(req)):
                dists.add(n)
    tool = data.get("tool", {}) if isinstance(data.get("tool"), dict) else {}
    poetry = tool.get("poetry", {}) if isinstance(tool.get("poetry"), dict) else {}
    if isinstance(poetry.get("name"), str):
        own.add(norm(poetry["name"]))
    for section in ("dependencies", "dev-dependencies"):
        dists |= {k for k in (poetry.get(section, {}) or {}) if k != "python"}
    for group in (poetry.get("group", {}) or {}).values():
        if isinstance(group, dict):
            dists |= set(group.get("dependencies", {}) or {})
    uv = tool.get("uv", {}) if isinstance(tool.get("uv"), dict) else {}
    for req in uv.get("dev-dependencies", []) or []:
        if isinstance(req, str) and (n := _req_name(req)):
            dists.add(n)
    # hatch environments and pdm dev groups declare dependencies too
    hatch = tool.get("hatch", {}) if isinstance(tool.get("hatch"), dict) else {}
    for env in (hatch.get("envs", {}) or {}).values():
        if not isinstance(env, dict):
            continue
        for key in ("dependencies", "extra-dependencies"):
            for req in env.get(key, []) or []:
                if isinstance(req, str) and (n := _req_name(req)):
                    dists.add(n)
    pdm = tool.get("pdm", {}) if isinstance(tool.get("pdm"), dict) else {}
    for reqs in (pdm.get("dev-dependencies", {}) or {}).values():
        for req in reqs or []:
            if isinstance(req, str) and (n := _req_name(req)):
                dists.add(n)
    return dists, own


def _parse_setup_cfg(text: str) -> set[str]:
    cp = configparser.ConfigParser()
    cp.read_string(text)
    out: set[str] = set()
    if cp.has_option("options", "install_requires"):
        for line in cp.get("options", "install_requires").splitlines():
            if n := _req_name(line):
                out.add(n)
    if cp.has_section("options.extras_require"):
        for _, value in cp.items("options.extras_require"):
            for line in value.splitlines():
                if n := _req_name(line):
                    out.add(n)
    return out


def _parse_package_lock(data: dict[str, Any]) -> tuple[set[str], set[str]]:
    dists: set[str] = set()
    own: set[str] = set()
    if isinstance(data.get("name"), str):
        own.add(data["name"])
    for key, entry in (data.get("packages", {}) or {}).items():
        if key == "":
            if isinstance(entry, dict):
                for sect in ("dependencies", "devDependencies", "optionalDependencies"):
                    dists |= set(entry.get(sect, {}) or {})
            continue
        if "node_modules/" in key:
            dists.add(key.rsplit("node_modules/", 1)[1])
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            own.add(entry["name"])  # a workspace package

    def walk(deps: dict[str, Any]) -> None:
        for name, entry in deps.items():
            dists.add(name)
            if isinstance(entry, dict) and isinstance(entry.get("dependencies"), dict):
                walk(entry["dependencies"])

    walk(data.get("dependencies", {}) or {})
    return dists, own


def _parse_pnpm(text: str) -> set[str]:
    out: set[str] = set()
    for line in text.splitlines():
        m = _PNPM_PKG.match(line)
        if m:
            out.add(m.group(1))
            continue
        m = _PNPM_DEP.match(line)
        if m and (m.group(1).startswith("@") or "/" not in m.group(1)):
            out.add(m.group(1))
    for junk in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "packages",
        "snapshots",
        "importers",
        "specifiers",
        "resolution",
        "engines",
        "cpu",
        "os",
        "peerDependencies",
        "peerDependenciesMeta",
        "transitivePeerDependencies",
        "optional",
        "dev",
        "hasBin",
        "requiresBuild",
        "bin",
        "deprecated",
        "libc",
    ):
        out.discard(junk)
    return out


def _parse_yarn(text: str) -> set[str]:
    out: set[str] = set()
    for line in text.splitlines():
        if not line or line.startswith((" ", "#", "\t", "__metadata")):
            continue
        if not line.rstrip().endswith(":"):
            continue
        for spec in line.rstrip(":").split(","):
            spec = spec.strip().strip('"')
            m = _YARN_KEY.match(spec)
            if m:
                out.add(m.group(1))
    return out


def _parse_package_json(data: dict[str, Any], ctx: Context, rel: str) -> tuple[set[str], set[str]]:
    dists: set[str] = set()
    own: set[str] = set()
    if isinstance(data.get("name"), str):
        own.add(data["name"])
    for sect in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        dists |= set(data.get(sect, {}) or {})
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    base_dir = os.path.dirname(rel)
    for pattern in workspaces or []:
        if not isinstance(pattern, str):
            continue
        for cand in ctx.files(("package.json",)):
            cdir = os.path.dirname(cand)
            if cand == rel or not cdir.startswith(base_dir):
                continue
            body = ctx.read_text(cand)
            try:
                name = json.loads(body or "{}").get("name")
            except ValueError:
                continue
            if isinstance(name, str):
                own.add(name)
    return dists, own


def _local_python_names(files: Iterable[str], roots: Iterable[str]) -> set[str]:
    """Top-level importable names the repo itself provides under each source root."""
    out: set[str] = set()
    root_list = sorted({r.strip("/") for r in roots})
    for rel in files:
        if not rel.endswith(".py"):
            continue
        for root in root_list:
            prefix = f"{root}/" if root else ""
            if root and not rel.startswith(prefix):
                continue
            body = rel[len(prefix) :].split("/")
            if not body or not body[0]:
                continue
            head = body[0][:-3] if len(body) == 1 else body[0]
            if head.isidentifier():
                out.add(head)
    return out


def _nested_python_packages(files: Iterable[str], roots: Iterable[str]) -> set[str]:
    """Names of package directories (``__init__.py``) that are not under a source
    root: importable only with sys.path help (Django ``apps/``, ``packages/*``)."""
    root_names = _local_python_names(files, roots)
    out: set[str] = set()
    for rel in files:
        if not rel.endswith("/__init__.py"):
            continue
        parts = rel.split("/")
        if len(parts) < 3:
            continue
        name = parts[-2]
        if name.isidentifier() and name not in root_names:
            out.add(name)
    return out


def _top_level_dirs(files: Iterable[str]) -> set[str]:
    """First path segments that are directories (used to soften bare bundler aliases)."""
    out: set[str] = set()
    for rel in files:
        head, sep, _ = rel.partition("/")
        if sep and head and not head.startswith("."):
            out.add(head)
            if head in ("src", "app", "lib"):
                sub = rel.split("/")
                if len(sub) > 2:
                    out.add(sub[1])
    return out


def _python_roots(base: str, text: str) -> set[str]:
    """Extra source roots declared by the packaging config (setuptools, poetry,
    hatch, pytest pythonpath)."""
    roots: set[str] = set()
    try:
        if base == "setup.cfg":
            cp = configparser.ConfigParser()
            cp.read_string(text)
            if cp.has_option("options", "package_dir"):
                for line in cp.get("options", "package_dir").splitlines():
                    if "=" in line:
                        roots.add(line.split("=", 1)[1].strip())
            if cp.has_option("options.packages.find", "where"):
                roots.update(w.strip() for w in cp.get("options.packages.find", "where").split(","))
            return {r.strip("./") for r in roots if r.strip("./") != "."}
        data = load_toml(text)
    except (ValueError, TypeError, configparser.Error):
        return set()
    tool = data.get("tool", {}) if isinstance(data.get("tool"), dict) else {}
    setuptools = tool.get("setuptools", {}) if isinstance(tool.get("setuptools"), dict) else {}
    for value in (setuptools.get("package-dir", {}) or {}).values():
        if isinstance(value, str):
            roots.add(value)
    find = setuptools.get("packages", {})
    if isinstance(find, dict):
        for w in (find.get("find", {}) or {}).get("where", []) or []:
            if isinstance(w, str):
                roots.add(w)
    poetry = tool.get("poetry", {}) if isinstance(tool.get("poetry"), dict) else {}
    for pkg in poetry.get("packages", []) or []:
        if isinstance(pkg, dict) and isinstance(pkg.get("from"), str):
            roots.add(pkg["from"])
    hatch = tool.get("hatch", {}) if isinstance(tool.get("hatch"), dict) else {}
    wheel = ((hatch.get("build", {}) or {}).get("targets", {}) or {}).get("wheel", {}) or {}
    for pkg in wheel.get("packages", []) or []:
        if isinstance(pkg, str) and "/" in pkg:
            roots.add(pkg.rsplit("/", 1)[0])
    pytest_opts = (
        tool.get("pytest", {}).get("ini_options", {})
        if isinstance(tool.get("pytest"), dict)
        else {}
    )
    pp = pytest_opts.get("pythonpath", []) if isinstance(pytest_opts, dict) else []
    for entry in ([pp] if isinstance(pp, str) else pp) or []:
        if isinstance(entry, str):
            roots.add(entry)
    return {r.strip("./") for r in roots if r.strip("./") not in ("", ".")}


_JSONC_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_JSONC_TRAILING = re.compile(r",(\s*[}\]])")


def _load_jsonc(text: str) -> dict[str, Any]:
    cleaned = _JSONC_TRAILING.sub(r"\1", _JSONC_COMMENT.sub("", text))
    data = json.loads(cleaned)
    return data if isinstance(data, dict) else {}


def _tsconfig_aliases(text: str, ctx: Context, rel: str, depth: int = 0) -> set[str]:
    """``compilerOptions.paths`` patterns (``@app/*``) and ``baseUrl:<dir>`` markers,
    following one ``extends`` hop."""
    try:
        data = _load_jsonc(text)
    except ValueError:
        return set()
    out: set[str] = set()
    ext = data.get("extends")
    if isinstance(ext, str) and depth < 2 and ext.startswith("."):
        parent = os.path.normpath(os.path.join(os.path.dirname(rel), ext))
        if not parent.endswith(".json"):
            parent += ".json"
        parent_text = ctx.read_text(parent.replace(os.sep, "/"))
        if parent_text is not None:
            out |= _tsconfig_aliases(parent_text, ctx, parent, depth + 1)
    opts = data.get("compilerOptions", {}) if isinstance(data.get("compilerOptions"), dict) else {}
    for pattern in opts.get("paths", {}) or {}:
        if isinstance(pattern, str):
            out.add(pattern)
    base = opts.get("baseUrl")
    if isinstance(base, str):
        base_dir = os.path.normpath(os.path.join(os.path.dirname(rel), base)).replace(os.sep, "/")
        out.add(f"baseUrl:{base_dir.strip('./') or '.'}")
    return out


def _matching_alias(spec: str, aliases: set[str]) -> str | None:
    for pattern in sorted(aliases):
        if pattern.startswith("baseUrl:"):
            continue
        if pattern.endswith("/*"):
            if spec == pattern[:-2] or spec.startswith(pattern[:-1]):
                return pattern
        elif pattern.endswith("*"):
            if spec.startswith(pattern[:-1]):
                return pattern
        elif spec == pattern:
            return pattern
    return None


def _base_url_hit(spec: str, aliases: set[str], ctx: Context) -> bool:
    for pattern in aliases:
        if not pattern.startswith("baseUrl:"):
            continue
        base = pattern[len("baseUrl:") :]
        head = spec.split("/")[0]
        candidate = os.path.join(ctx.repo_root, "" if base == "." else base, head)
        if os.path.isdir(candidate):
            return True
        for ext in (
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".mts",
            ".cts",
            ".vue",
            ".svelte",
            ".json",
        ):
            if os.path.isfile(candidate + ext):
                return True
    return False


def register(api: OracleAPI) -> None:
    api.register_oracle(ImportsLockfileOracle())
