"""env_vars: every environment variable the code reads must be declared somewhere.

This is the fully worked reference oracle. It is Tier 0 (standard library only)
and it demonstrates the whole spine: build a per-file index of declared names,
sync only the files that changed, extract used names from a change, check each
use against the index, and reject a use that is declared nowhere, with a
did-you-mean suggestion.

A used variable declared nowhere      -> REJECT (with the closest declared name)
A dynamic key (os.environ[some_var])  -> REVIEW (cannot resolve the name)
A read with an inline default         -> ACCEPT (nothing is broken)
A well-known ambient variable (PATH)  -> ACCEPT (provided by the OS/runtime/CI)
No index yet                          -> UNVERIFIABLE

Declaration sources, in the order DESIGN.md lists them: dotenv-style example
files, settings schemas (pydantic ``BaseSettings`` fields), defaults in code
(``os.getenv("X", default)``, ``os.environ.setdefault``), plus Dockerfile ``ENV``
and docker-compose ``environment:`` entries, plus anything the user lists in
``env_declared_in`` (where every literal read also counts as a declaration,
because that file *is* the project's declared env contract).
"""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterable
from typing import Any

from ..change import Change, Region
from ..oracle import BaseOracle, Context, OracleAPI
from ..suggest import did_you_mean
from ..types import Claim, Finding, Location

_NAME = r"([A-Za-z_][A-Za-z0-9_]*)"
_Q = r"['\"]"

# (pattern, default_group_index or None). Group 1 is always the literal name.
# A "default group" that matched means the read supplies its own fallback.
_READS: list[tuple[re.Pattern[str], int | None]] = [
    # Python
    (re.compile(rf"\bos\.environ\[\s*{_Q}{_NAME}{_Q}\s*\]"), None),
    (re.compile(rf"\bos\.environ\.get\(\s*{_Q}{_NAME}{_Q}\s*(?:,\s*([^)]*))?\)"), 2),
    (re.compile(rf"\bos\.getenv\(\s*{_Q}{_NAME}{_Q}\s*(?:,\s*([^)]*))?\)"), 2),
    (re.compile(rf"(?<![\w.])environ\[\s*{_Q}{_NAME}{_Q}\s*\]"), None),
    (re.compile(rf"(?<![\w.])environ\.get\(\s*{_Q}{_NAME}{_Q}\s*(?:,\s*([^)]*))?\)"), 2),
    (re.compile(rf"(?<![\w.])getenv\(\s*{_Q}{_NAME}{_Q}\s*(?:,\s*([^)]*))?\)"), 2),
    # Node / Deno / Bun / Vite
    (re.compile(rf"\bprocess\.env\.{_NAME}\s*(\|\||\?\?)?"), 2),
    (re.compile(rf"\bprocess\.env\[\s*{_Q}{_NAME}{_Q}\s*\]\s*(\|\||\?\?)?"), 2),
    (re.compile(rf"\bDeno\.env\.get\(\s*{_Q}{_NAME}{_Q}\s*\)\s*(\|\||\?\?)?"), 2),
    (re.compile(rf"\bBun\.env\.{_NAME}\s*(\|\||\?\?)?"), 2),
    (re.compile(rf"\bimport\.meta\.env\.{_NAME}\s*(\|\||\?\?)?"), 2),
    # Ruby
    (re.compile(rf"\bENV\[\s*{_Q}{_NAME}{_Q}\s*\]\s*(\|\|)?"), 2),
    (re.compile(rf"\bENV\.fetch\(\s*{_Q}{_NAME}{_Q}\s*(,[^)]+)?\)\s*(\{{)?"), 2),
    # Go, Rust, Java/Kotlin, C#, PHP
    (re.compile(rf"\bos\.(?:Getenv|LookupEnv)\(\s*\"{_NAME}\"\s*\)"), None),
    (re.compile(rf"\benv::var(?:_os)?\(\s*\"{_NAME}\"\s*\)"), None),
    (re.compile(rf"\b(?:option_)?env!\(\s*\"{_NAME}\"\s*\)"), None),
    (re.compile(rf"\bSystem\.getenv\(\s*\"{_NAME}\"\s*\)"), None),
    (re.compile(rf"\bEnvironment\.GetEnvironmentVariable\(\s*\"{_NAME}\"\s*\)"), None),
    (re.compile(rf"\$_ENV\[\s*{_Q}{_NAME}{_Q}\s*\]"), None),
]

# A read whose key is not a string literal: we can see it happens, not the name.
_DYNAMIC = re.compile(
    r"(?:\bos\.environ\[|\bos\.environ\.get\(|\bos\.getenv\(|(?<![\w.])environ\[|"
    r"(?<![\w.])getenv\(|\bprocess\.env\[|\bENV\[|\bENV\.fetch\(|\bos\.Getenv\(|"
    r"\bos\.LookupEnv\(|\benv::var\(|\bSystem\.getenv\(|\bDeno\.env\.get\()\s*(?![\"'])\S"
)
_COMMENT = re.compile(r"^\s*(#|//|\*|/\*|--)")

# Files whose contents declare env var names, matched by basename anywhere.
_DOTENV_NAMES = (
    ".env.example", ".env.sample", ".env.template", ".env.defaults", ".env.dist",
    ".env.example.local", ".env.local.example", "env.example", "example.env",
)
_DOTENV_LINE = re.compile(rf"^\s*(?:export\s+)?{_NAME}\s*[=:]")
_COMPOSE_NAME = re.compile(r"^(docker-)?compose(\..+)?\.ya?ml$")
_COMPOSE_ENV_ITEM = re.compile(rf"^\s*-\s*{_Q}?{_NAME}{_Q}?\s*(?:[=:]|$)")
_COMPOSE_ENV_KEY = re.compile(rf"^\s*{_Q}?{_NAME}{_Q}?\s*:")
_DOCKERFILE_ENV = re.compile(rf"^\s*(?:ENV|ARG)\s+{_NAME}")
_DOCKERFILE_ENV_MULTI = re.compile(rf"(?:^|\s){_NAME}=")
_JS_DECL = re.compile(rf"\bprocess\.env\.{_NAME}\s*(=[^=]|\|\||\?\?)")
_PY_SUFFIXES = (".py",)
_JS_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".mts", ".cts")
_CLIKE_SUFFIXES = (".go", ".rs", ".java", ".kt", ".cs", ".php", ".vue", ".svelte", *_JS_SUFFIXES)
_CODE_SUFFIXES = (".py", ".rb", *_CLIKE_SUFFIXES)

# Variables the OS, the runtime, or CI provide. Reading one is never a broken wire.
_AMBIENT = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "OLDPWD", "TMPDIR", "TMP", "TEMP",
        "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "HOSTNAME", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "SYSTEMROOT", "COMSPEC", "OS", "PROGRAMFILES", "PROGRAMDATA",
        "NODE_ENV", "NODE_OPTIONS", "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
        "VIRTUAL_ENV", "CONDA_PREFIX", "RUST_LOG", "RUST_BACKTRACE", "GOPATH", "GOROOT",
        "JAVA_HOME", "CI", "GITLAB_CI", "CI_COMMIT_SHA", "BUILDKITE", "CIRCLECI", "TRAVIS",
        "JENKINS_URL", "PORT", "DEBUG", "MODE", "DEV", "PROD", "SSR", "BASE_URL",
        "npm_package_version", "npm_package_name", "npm_lifecycle_event",
    }
)
_AMBIENT_PREFIXES = ("XDG_", "GITHUB_", "RUNNER_", "VERCEL_", "RAILWAY_", "RENDER_", "FLY_",
                     "HEROKU_", "AWS_LAMBDA_", "AWS_REGION", "AWS_DEFAULT_REGION", "KUBERNETES_",
                     "DYNO", "WEBSITE_", "FUNCTIONS_", "CF_PAGES", "NETLIFY", "CODESPACE")


def _is_ambient(name: str, extra: Iterable[str]) -> bool:
    return name in _AMBIENT or name in set(extra) or name.startswith(_AMBIENT_PREFIXES)


class EnvVarOracle(BaseOracle):
    name = "env_vars"
    kinds: tuple[str, ...] = ("env_var",)
    version = "3"

    _COLUMNS = "file TEXT NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL"

    # --- index -----------------------------------------------------------------

    def build(self, ctx: Context) -> None:
        rows: list[tuple[str, str, str]] = []
        for rel in self._candidate_files(ctx, ctx.files()):
            rows.extend(self._scan_file(ctx, rel))
        ctx.store.namespace(self.name).rebuild(
            "decl", self._COLUMNS, sorted(set(rows)), indexes=["file", "name"]
        )

    def sync(self, ctx: Context, since: str | None) -> None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("decl"):
            self.build(ctx)
            return
        changed = ctx.store.sync_files(since)
        for rel in self._candidate_files(ctx, changed):
            ns.replace_file("decl", rel, sorted(set(self._scan_file(ctx, rel))))

    def _configured_files(self, ctx: Context) -> list[str]:
        return [p.replace(os.sep, "/") for p in ctx.config.env_declared_in]

    def _candidate_files(self, ctx: Context, files: Iterable[str]) -> list[str]:
        configured = set(self._configured_files(ctx))
        out: set[str] = set()
        for rel in files:
            base = os.path.basename(rel)
            if (
                rel in configured
                or base in _DOTENV_NAMES
                or _COMPOSE_NAME.match(base)
                or base.startswith("Dockerfile")
                or base.endswith(".Dockerfile")
                or rel.endswith(_PY_SUFFIXES)
                or rel.endswith(_JS_SUFFIXES)
            ):
                out.add(rel)
        # Configured files count even when gitignored (e.g. a real .env).
        for rel in configured:
            if os.path.isfile(ctx.path(rel)):
                out.add(rel)
        return sorted(out)

    def _scan_file(self, ctx: Context, rel: str) -> list[tuple[str, str, str]]:
        text = ctx.read_text(rel)
        if text is None:
            return []
        base = os.path.basename(rel)
        configured = rel in set(self._configured_files(ctx))
        names: list[tuple[str, str]] = []
        if base in _DOTENV_NAMES or (configured and not rel.endswith(_CODE_SUFFIXES)
                                     and not _COMPOSE_NAME.match(base)):
            names += [(n, "dotenv") for n in _scan_dotenv(text)]
        elif _COMPOSE_NAME.match(base):
            names += [(n, "compose") for n in _scan_compose(text)]
        elif base.startswith("Dockerfile") or base.endswith(".Dockerfile"):
            names += [(n, "dockerfile") for n in _scan_dockerfile(text)]
        elif rel.endswith(_PY_SUFFIXES):
            names += _scan_python(text, reads_declare=configured)
        elif rel.endswith(_JS_SUFFIXES):
            names += [(n, "code_default") for n in _scan_js(text)]
            if configured:
                names += [(c.subject, "configured") for c in self._extract_region_text(rel, text)
                          if c.hard]
        return [(rel, n, s) for n, s in names]

    def _declared(self, ctx: Context) -> dict[str, list[str]] | None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("decl"):
            return None
        out: dict[str, list[str]] = {}
        for name, file in ns.query("SELECT name, file FROM {t:decl} ORDER BY name, file"):
            out.setdefault(str(name), []).append(str(file))
        return out

    # --- extract + check -------------------------------------------------------

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        claims: list[Claim] = []
        for region in change.added_regions():
            claims.extend(self._extract_region(region))
        return claims

    def _extract_region_text(self, file: str, text: str) -> list[Claim]:
        region = Region(file=file)
        for i, line in enumerate(text.splitlines(), 1):
            region.add(i, line)
        return self._extract_region(region)

    def _extract_region(self, region: Region) -> list[Claim]:
        if region.whole_file and region.file.endswith(_PY_SUFFIXES):
            precise = _extract_python_ast(region)
            if precise is not None:
                return precise
        if region.whole_file and region.file.endswith(_CLIKE_SUFFIXES + (".rb",)):
            style = "hash" if region.file.endswith(".rb") else "clike"
            masked = mask_comments(region.text(), style).split("\n")
            lines = [(ln, masked[ln - 1] if ln - 1 < len(masked) else text)
                     for ln, text in region.lines()]
            return self._extract_lines(region.file, lines)
        return self._extract_lines(region.file, region.lines())

    def _extract_lines(self, file: str, lines: list[tuple[int, str]]) -> list[Claim]:
        claims: list[Claim] = []
        for lineno, text in lines:
            if _COMMENT.match(text):
                continue
            seen_here: set[str] = set()
            for pat, default_group in _READS:
                for m in pat.finditer(text):
                    name = m.group(1)
                    if name in seen_here:
                        continue
                    seen_here.add(name)
                    default_text = (m.group(default_group) or "") if default_group else ""
                    has_default = default_text.strip() not in ("", "None")
                    claims.append(
                        Claim(
                            kind="env_var",
                            subject=name,
                            location=Location(file, lineno, m.start() + 1),
                            attrs={"default": has_default} if has_default else {},
                        )
                    )
            dyn = None if seen_here else _DYNAMIC.search(text)
            if dyn is not None:
                claims.append(
                    Claim(
                        kind="env_var",
                        subject="<dynamic>",
                        location=Location(file, lineno, dyn.start() + 1),
                        hard=False,
                    )
                )
        return claims

    def check(self, claim: Claim, ctx: Context) -> Finding:
        declared = self._declared(ctx)
        if declared is None:
            return self.unverifiable(claim, "env index not built")
        if claim.subject == "<dynamic>":
            return self.review(claim, "env read with a non-literal key; cannot resolve the name")
        extra_ambient = ctx.oracle_config(self.name).get("ambient", [])
        if claim.subject in declared:
            where = declared[claim.subject][0]
            return self.accept(claim, f"declared in {where}")
        if _is_ambient(claim.subject, extra_ambient):
            return self.accept(claim, "well-known variable provided by the OS, runtime, or CI")
        if claim.attrs.get("default"):
            return self.accept(claim, "read with an inline default; not declared in any env source")
        if not declared:
            return self.review(
                claim,
                f"env var {claim.subject!r} is read, and this repo has no env declaration source "
                f"at all (no .env.example, settings schema, Dockerfile ENV, or code default); "
                f"add one, or list your .env under env_declared_in in weft.toml",
            )
        sugg = self.suggest(claim, ctx)
        target = self._where_to_declare(ctx)
        reason = f"env var {claim.subject!r} is read but declared nowhere (add it to {target})"
        return self.reject(claim, reason, sugg)

    def suggest(self, claim: Claim, ctx: Context) -> list[str]:
        declared = self._declared(ctx) or {}
        return did_you_mean(claim.subject, declared.keys())

    def _where_to_declare(self, ctx: Context) -> str:
        for rel in self._configured_files(ctx) + list(_DOTENV_NAMES):
            if os.path.isfile(ctx.path(rel)):
                return rel
        return ".env.example"


# --- comment masking for regex-scanned languages ----------------------------------------------


def mask_comments(text: str, style: str = "clike") -> str:
    """Blank out comments (``//``, ``/* */``, or ``#``) while keeping every line and
    every string literal intact, so a read quoted in a comment is not a claim but a
    read inside a template string still is. Escapes and the three JS quote kinds are
    honoured; regex literals are not (a rare ``//`` inside one may end the scan early,
    which only ever *hides* a read, never invents one)."""
    out: list[str] = []
    i, n = 0, len(text)
    quote: str | None = None
    block = False
    line = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if line:
            if ch == "\n":
                line = False
                out.append(ch)
            else:
                out.append(" ")
        elif block:
            if ch == "*" and nxt == "/":
                block = False
                out.append("  ")
                i += 1
            else:
                out.append(ch if ch == "\n" else " ")
        elif quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 1
            elif ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
        elif style == "clike" and ch == "/" and nxt == "/":
            line = True
            out.append("  ")
            i += 1
        elif style == "clike" and ch == "/" and nxt == "*":
            block = True
            out.append("  ")
            i += 1
        elif style == "hash" and ch == "#":
            line = True
            out.append(" ")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


# --- precise extraction for whole Python files -------------------------------------------

_PY_READ_CALLS = ("os.environ.get", "os.getenv", "environ.get", "getenv")
_PY_READ_SUBSCRIPTS = ("os.environ", "environ")


def _extract_python_ast(region: Region) -> list[Claim] | None:
    """Env reads as the parser sees them, so a read quoted inside a string literal
    (test fixtures, docs) is not mistaken for code. None on a syntax error."""
    try:
        tree = ast.parse(region.text())
    except (SyntaxError, ValueError):
        return None
    found: list[tuple[int, int, str, bool, bool]] = []  # line, col, name, default, dynamic
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _dotted(node.value) in _PY_READ_SUBSCRIPTS:
            if isinstance(node.ctx, ast.Store | ast.Del):
                continue  # os.environ["X"] = ... declares; it does not read
            name = _str(node.slice)
            found.append((node.lineno, node.col_offset, name or "", False, name is None))
        elif isinstance(node, ast.Call) and _dotted(node.func) in _PY_READ_CALLS and node.args:
            name = _str(node.args[0])
            default = len(node.args) > 1 and not (
                isinstance(node.args[1], ast.Constant) and node.args[1].value is None
            )
            default = default or any(
                k.arg == "default" and not (isinstance(k.value, ast.Constant)
                                            and k.value.value is None) for k in node.keywords)
            found.append((node.lineno, node.col_offset, name or "", default, name is None))
    claims: list[Claim] = []
    seen: set[tuple[int, str]] = set()
    for line, col, name, default, dynamic in sorted(found):
        key = (line, name if not dynamic else "<dynamic>")
        if key in seen:
            continue
        seen.add(key)
        if dynamic:
            claims.append(Claim("env_var", "<dynamic>", Location(region.file, line, col + 1),
                                hard=False))
        else:
            claims.append(Claim("env_var", name, Location(region.file, line, col + 1),
                                {"default": True} if default else {}))
    return claims


# --- declaration scanners -----------------------------------------------------------------


def _scan_dotenv(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _DOTENV_LINE.match(line)
        if m and not line.lstrip().startswith("#"):
            out.append(m.group(1))
    return out


def _scan_compose(text: str) -> list[str]:
    """``environment:`` entries in list form (``- X=1``) or map form (``X: 1``)."""
    out: list[str] = []
    in_env = False
    env_indent = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(r"^environment\s*:\s*$", stripped):
            in_env, env_indent = True, indent
            continue
        if in_env:
            if indent <= env_indent:
                in_env = False
            else:
                m = _COMPOSE_ENV_ITEM.match(line) or _COMPOSE_ENV_KEY.match(line)
                if m:
                    out.append(m.group(1))
                continue
    return out


def _scan_dockerfile(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        m = _DOCKERFILE_ENV.match(line)
        if not m:
            continue
        body = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
        multi = _DOCKERFILE_ENV_MULTI.findall(body)
        out.extend(multi or [m.group(1)])
    return out


def _scan_js(text: str) -> list[str]:
    return [m.group(1) for m in _JS_DECL.finditer(text)]


def _scan_python(text: str, reads_declare: bool = False) -> list[tuple[str, str]]:
    """Declarations in Python source via ``ast``: ``os.environ.setdefault("X", ...)``,
    ``os.environ["X"] = ...``, ``os.getenv("X", default)``, and fields of any class
    whose bases mention ``BaseSettings``/``Settings``. Falls back to nothing on a
    syntax error (never a false declaration, never a crash)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = _dotted(node.func)
            args = node.args
            if fn in ("os.environ.setdefault", "environ.setdefault") and args:
                name = _str(args[0])
                if name:
                    out.append((name, "code_default"))
            elif fn in ("os.getenv", "os.environ.get", "getenv", "environ.get") and args:
                name = _str(args[0])
                if not name:
                    continue
                has_default = len(args) > 1 and not (
                    isinstance(args[1], ast.Constant) and args[1].value is None
                )
                has_default = has_default or any(k.arg == "default" for k in node.keywords)
                if has_default:
                    out.append((name, "code_default"))
                elif reads_declare:
                    out.append((name, "configured"))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _dotted(target.value) in (
                    "os.environ", "environ"
                ):
                    name = _str(target.slice)
                    if name:
                        out.append((name, "code_assign"))
        elif isinstance(node, ast.Subscript) and reads_declare:
            if _dotted(node.value) in ("os.environ", "environ"):
                name = _str(node.slice)
                if name:
                    out.append((name, "configured"))
        elif isinstance(node, ast.ClassDef):
            bases = {_dotted(b) or "" for b in node.bases}
            if any(b.endswith("BaseSettings") or b.endswith("Settings") for b in bases):
                prefix = _settings_prefix(node)
                for stmt in node.body:
                    field: ast.expr | None = None
                    if isinstance(stmt, ast.AnnAssign):
                        field = stmt.target
                    elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                        field = stmt.targets[0]
                    if isinstance(field, ast.Name) and not field.id.startswith("_"):
                        if field.id in ("model_config", "Config"):
                            continue
                        out.append(((prefix + field.id).upper(), "settings_class"))
                        out.append((prefix + field.id, "settings_class"))
    return out


def _settings_prefix(cls: ast.ClassDef) -> str:
    """``env_prefix`` from a pydantic ``model_config``/inner ``Config``; '' if none."""
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign | ast.AnnAssign):
            target: ast.expr = stmt.targets[0] if isinstance(stmt, ast.Assign) else stmt.target
            value = stmt.value
            if isinstance(target, ast.Name) and target.id == "model_config" and value is not None:
                for kw in getattr(value, "keywords", []):
                    if kw.arg == "env_prefix":
                        return _str(kw.value) or ""
                if isinstance(value, ast.Dict):
                    for k, v in zip(value.keys, value.values, strict=False):
                        if k is not None and _str(k) == "env_prefix":
                            return _str(v) or ""
        if isinstance(stmt, ast.ClassDef) and stmt.name == "Config":
            for inner in stmt.body:
                if isinstance(inner, ast.Assign) and len(inner.targets) == 1:
                    t = inner.targets[0]
                    if isinstance(t, ast.Name) and t.id == "env_prefix":
                        return _str(inner.value) or ""
    return ""


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def describe_declarations(ctx: Context) -> dict[str, Any]:
    """Debug helper: where every declared name comes from (used by ``weft index``)."""
    oracle = EnvVarOracle()
    declared = oracle._declared(ctx) or {}
    return {name: files for name, files in sorted(declared.items())}


def register(api: OracleAPI) -> None:
    api.register_oracle(EnvVarOracle())
