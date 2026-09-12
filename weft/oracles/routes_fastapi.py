"""routes_fastapi: every route resolves to a defined, registered handler. The
first true edge oracle and the template for Django/Flask/Express/Next/Rails.

Tier 0, standard library only. The route table is built *statically* from the
app's own registration code with ``ast`` (no import of the app, no FastAPI
needed): ``@app.get(...)`` decorators, ``add_api_route(path, endpoint)``,
``APIRoute``/``Route`` objects, ``APIRouter(prefix=...)`` and
``include_router(router, prefix=...)`` wiring.

Diff mode checks the edges a change creates:
  add_api_route("/p", handler)  handler not defined/imported anywhere  -> REJECT
  include_router(users.router)  module found, no ``router`` in it      -> REJECT
  @router.get("/p")             ``router`` never bound in that file    -> REJECT
  handler/router is a call, subscript, getattr, or star-import         -> REVIEW
  handler imported from a module outside the repo                      -> REVIEW
Claim mode checks a stated route ("POST /users", handler "users.create"):
  no such method+path in the resolved route table                      -> REJECT
  path exists only under a prefix weft could not resolve               -> REVIEW
  no FastAPI usage in the repo / index not built                       -> UNVERIFIABLE
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

from ..change import Change, Region
from ..oracle import BaseOracle, Context, OracleAPI, file_of_module, module_of_file
from ..suggest import did_you_mean
from ..types import Claim, Finding, Location

_METHODS = ("get", "post", "put", "delete", "patch", "options", "head", "trace")
_ADD_ROUTE = ("add_api_route", "add_route", "add_websocket_route", "add_api_websocket_route")
_ROUTE_CLASSES = ("APIRoute", "Route", "WebSocketRoute")
_ROUTER_CLASSES = ("APIRouter", "FastAPI", "Router", "Starlette")
_FASTAPI_RE = re.compile(r"\b(fastapi|starlette)\b")
_RX_ADD = re.compile(
    r"\b(\w+)\.(add_api_route|add_route|add_websocket_route)\(\s*['\"]([^'\"]*)['\"]"
    r"\s*,\s*([\w.]+|[^,)]+)"
)
_RX_INC = re.compile(r"\b(\w+)\.include_router\(\s*([\w.]+|[^,)]+)")
_RX_DEC = re.compile(r"^\s*@(\w+)\.(get|post|put|delete|patch|options|head|trace|websocket|"
                     r"api_route|route)\(\s*['\"]([^'\"]*)['\"]")


@dataclass
class _Scan:
    """Everything one Python file tells us."""

    symbols: dict[str, tuple[str, str]] = field(default_factory=dict)  # name -> (kind, target)
    routes: list[tuple[int, str, str, str, str, str, str]] = field(default_factory=list)
    routers: dict[str, tuple[str, str]] = field(default_factory=dict)  # var -> (kind, prefix)
    includes: list[tuple[int, str, str, str]] = field(default_factory=list)
    star_imports: list[str] = field(default_factory=list)
    uses_fastapi: bool = False


class RoutesFastAPIOracle(BaseOracle):
    name = "routes_fastapi"
    kinds: tuple[str, ...] = ("route_handler", "router_include")
    version = "2"

    _SYMBOLS = "file TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL"
    _ROUTES = ("file TEXT NOT NULL, line INTEGER NOT NULL, method TEXT NOT NULL, "
               "path TEXT NOT NULL, handler TEXT NOT NULL, handler_kind TEXT NOT NULL, "
               "style TEXT NOT NULL, router TEXT NOT NULL")
    _ROUTERS = "file TEXT NOT NULL, var TEXT NOT NULL, kind TEXT NOT NULL, prefix TEXT NOT NULL"
    _INCLUDES = ("file TEXT NOT NULL, line INTEGER NOT NULL, parent TEXT NOT NULL, "
                 "child TEXT NOT NULL, prefix TEXT NOT NULL")
    _FILES = "file TEXT NOT NULL, uses_fastapi INTEGER NOT NULL"

    # --- index -----------------------------------------------------------------

    def build(self, ctx: Context) -> None:
        rows: dict[str, list[tuple[Any, ...]]] = {
            "symbols": [], "routes": [], "routers": [], "includes": [], "files": []
        }
        for rel in ctx.files((".py",)):
            self._collect(ctx, rel, rows)
        ns = ctx.store.namespace(self.name)
        ns.rebuild("symbols", self._SYMBOLS, sorted(set(rows["symbols"])), indexes=["file"])
        ns.rebuild("routes", self._ROUTES, sorted(set(rows["routes"])), indexes=["file"])
        ns.rebuild("routers", self._ROUTERS, sorted(set(rows["routers"])), indexes=["file"])
        ns.rebuild("includes", self._INCLUDES, sorted(set(rows["includes"])), indexes=["file"])
        ns.rebuild("files", self._FILES, sorted(set(rows["files"])), indexes=["file"])

    def sync(self, ctx: Context, since: str | None) -> None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("routes"):
            self.build(ctx)
            return
        for rel in ctx.store.sync_files(since):
            if not rel.endswith(".py"):
                continue
            rows: dict[str, list[tuple[Any, ...]]] = {k: [] for k in
                                                       ("symbols", "routes", "routers",
                                                        "includes", "files")}
            self._collect(ctx, rel, rows)
            for table, table_rows in rows.items():
                ns.replace_file(table, rel, sorted(set(table_rows)))

    def _collect(self, ctx: Context, rel: str, rows: dict[str, list[Any]]) -> None:
        text = ctx.read_text(rel)
        if text is None:
            return
        scan = _scan_python(text)
        if scan is None:
            return
        rows["files"].append((rel, 1 if scan.uses_fastapi else 0))
        for name, (kind, target) in scan.symbols.items():
            rows["symbols"].append((rel, name, kind, target))
        for star in scan.star_imports:
            rows["symbols"].append((rel, "*", "star", star))
        for line, method, path, handler, hkind, style, router in scan.routes:
            rows["routes"].append((rel, line, method, path, handler, hkind, style, router))
        for var, (kind, prefix) in scan.routers.items():
            rows["routers"].append((rel, var, kind, prefix))
        for line, parent, child, prefix in scan.includes:
            rows["includes"].append((rel, line, parent, child, prefix))

    def _built(self, ctx: Context) -> bool:
        return ctx.store.namespace(self.name).exists("routes")

    def _uses_fastapi(self, ctx: Context) -> bool:
        ns = ctx.store.namespace(self.name)
        row = ns.query("SELECT COUNT(*) FROM {t:files} WHERE uses_fastapi=1")
        return bool(row and row[0][0])

    def _symbols(self, ctx: Context, rel: str) -> dict[str, tuple[str, str]] | None:
        """The file's bindings from the index (None if the file is not indexed)."""
        ns = ctx.store.namespace(self.name)
        rows = ns.query("SELECT name, kind, target FROM {t:symbols} WHERE file=?", (rel,))
        known = ns.query("SELECT 1 FROM {t:files} WHERE file=?", (rel,))
        if not known:
            return None
        return {str(n): (str(k), str(t)) for n, k, t in rows}

    # --- extract ---------------------------------------------------------------

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        claims: list[Claim] = []
        for region in change.added_regions():
            if region.file.endswith(".py"):
                claims.extend(self._extract_region(region, ctx))
        return claims

    def _extract_region(self, region: Region, ctx: Context) -> list[Claim]:
        added = {ln for ln, _ in region.lines()}
        scan: _Scan | None = None
        line_map: dict[int, int] = {}
        if region.whole_file:
            scan = _scan_python(region.text())
        if scan is None:
            text = ctx.read_text(region.file)
            if text is not None:
                scan = _scan_python(text)
        if scan is None:
            scan = _scan_python(region.text())
            if scan is not None:
                line_map = {i + 1: ln for i, (ln, _) in enumerate(region.lines())}
                added = set(line_map)
        if scan is None:
            return _extract_regex(region)
        symbols = _symbol_payload(scan)
        claims: list[Claim] = []
        for line, method, path, handler, hkind, style, router in scan.routes:
            if line not in added:
                continue
            claims.append(Claim(
                "route_handler", f"{method} {path}",
                Location(region.file, line_map.get(line, line)),
                {"handler": handler, "handler_kind": hkind, "style": style, "router": router,
                 "symbols": symbols}, hard=hkind != "dynamic",
            ))
        for line, parent, child, prefix in scan.includes:
            if line not in added:
                continue
            ckind = "dynamic" if not re.fullmatch(r"[\w.]+", child) else (
                "attribute" if "." in child else "name")
            claims.append(Claim(
                "router_include", child, Location(region.file, line_map.get(line, line)),
                {"parent": parent, "child_kind": ckind, "prefix": prefix, "symbols": symbols},
                hard=ckind != "dynamic",
            ))
        return claims

    # --- check -----------------------------------------------------------------

    def check(self, claim: Claim, ctx: Context) -> Finding:
        if not self._built(ctx):
            return self.unverifiable(claim, "route table not built")
        if claim.kind == "router_include":
            return self._check_include(claim, ctx)
        if claim.source != "code" and "symbols" not in claim.attrs:
            return self._check_route_claim(claim, ctx)
        return self._check_route_edge(claim, ctx)

    def _check_route_edge(self, claim: Claim, ctx: Context) -> Finding:
        attrs = claim.attrs
        symbols = _symbols_from(attrs, ctx, claim.location.file)
        style, hkind = str(attrs.get("style", "")), str(attrs.get("handler_kind", "name"))
        handler, router = str(attrs.get("handler", "")), str(attrs.get("router", ""))
        if symbols is None:
            return self.unverifiable(claim, f"{claim.location.file} is not indexed")
        if style == "decorator":
            if router and router not in symbols:
                if "*" in symbols:
                    return self.review(claim, f"router {router!r} may come from a star import")
                sugg = did_you_mean(router, _names_of_kind(symbols, ("assign", "import")))
                return self.reject(claim, f"decorator uses {router!r}, which is not defined or "
                                          f"imported in this file", sugg)
            return self.accept(claim, f"handler {handler!r} defined by the decorator")
        if hkind == "dynamic":
            return self.review(claim, f"handler for {claim.subject} is computed at runtime "
                                      f"({handler}); cannot resolve")
        return self._resolve(claim, ctx, handler, symbols, what="handler")

    def _check_include(self, claim: Claim, ctx: Context) -> Finding:
        attrs = claim.attrs
        symbols = _symbols_from(attrs, ctx, claim.location.file)
        if symbols is None:
            return self.unverifiable(claim, f"{claim.location.file} is not indexed")
        if attrs.get("child_kind") == "dynamic":
            return self.review(claim, f"included router is computed at runtime ({claim.subject})")
        return self._resolve(claim, ctx, claim.subject, symbols, what="router")

    def _resolve(
        self, claim: Claim, ctx: Context, ref: str, symbols: dict[str, tuple[str, str]], what: str
    ) -> Finding:
        """Resolve ``ref`` (a name or dotted attribute) against the file's bindings,
        following one hop of imports into the repo's own modules."""
        head, _, rest = ref.partition(".")
        binding = symbols.get(head)
        if binding is None:
            if "*" in symbols:
                return self.review(claim, f"{what} {ref!r} may come from a star import")
            sugg = did_you_mean(head, _names_of_kind(symbols, ("def", "class", "import",
                                                                "assign")))
            return self.reject(claim, f"{what} {ref!r} is not defined or imported in "
                                      f"{claim.location.file}", sugg)
        kind, target = binding
        if kind in ("def", "class", "assign") and not rest:
            return self.accept(claim, f"{what} {ref!r} is defined in this file")
        if kind in ("def", "class", "assign") and rest:
            return self.review(claim, f"{what} {ref!r} is an attribute of a local object; "
                                      f"cannot resolve statically")
        if kind == "star":
            return self.review(claim, f"{what} {ref!r} may come from a star import")
        # kind == "import": target is "module" (import x) or "module:attr" (from m import a)
        module, _, attr = target.partition(":")
        if attr:
            if rest:  # from m import a; a.b -> a submodule, or an attribute of an object
                sub = _join_module(module, attr)
                if _module_file(ctx, sub, claim.location.file) is not None:
                    return self._resolve_in_module(claim, ctx, sub, rest, what, ref,
                                                   claim.location.file)
                return self.review(claim, f"{what} {ref!r} is an attribute of an imported "
                                          f"object; cannot resolve statically")
            return self._resolve_in_module(claim, ctx, module, attr, what, ref,
                                           claim.location.file)
        if not rest:
            return self.review(claim, f"{what} {ref!r} is a module, not a callable")
        return self._resolve_in_module(claim, ctx, module, rest, what, ref, claim.location.file)

    def _resolve_in_module(
        self, claim: Claim, ctx: Context, module: str, attr: str, what: str, ref: str,
        from_file: str,
    ) -> Finding:
        target_file = _module_file(ctx, module, from_file)
        if target_file is None:
            return self.review(claim, f"{what} {ref!r} comes from {module!r}, which is outside "
                                      f"the repo; cannot verify")
        symbols = self._symbols(ctx, target_file)
        if symbols is None:
            text = ctx.read_text(target_file)
            scan = _scan_python(text) if text is not None else None
            symbols = _symbol_payload(scan) if scan is not None else None
        if symbols is None:
            return self.unverifiable(claim, f"{target_file} is not indexed")
        head, _, deeper = attr.partition(".")
        if head in symbols:
            if deeper:
                return self.review(claim, f"{what} {ref!r} nests below {module}.{head}; "
                                          f"cannot resolve statically")
            return self.accept(claim, f"{what} {ref!r} resolves to {target_file}")
        if "*" in symbols:
            return self.review(claim, f"{what} {ref!r}: {target_file} has a star import")
        sugg = did_you_mean(head, _names_of_kind(symbols, ("def", "class", "assign", "import")))
        return self.reject(claim, f"{what} {ref!r}: {target_file} defines no {head!r}", sugg)

    # --- claim mode ---------------------------------------------------------------

    def _check_route_claim(self, claim: Claim, ctx: Context) -> Finding:
        if not self._uses_fastapi(ctx):
            return self.unverifiable(claim, "no FastAPI/Starlette usage found in the repo")
        method, _, path = claim.subject.strip().partition(" ")
        if not path:
            method, path = "ANY", method
        method = method.upper()
        table = self._route_table(ctx)
        want = _norm_path(path)
        exact = [r for r in table if (method in ("ANY", "*") or r.method == method)
                 and r.full is not None and _norm_path(r.full) == want]
        if not exact:
            exact = [r for r in table if (method in ("ANY", "*") or r.method == method)
                     and r.full is not None and _params_match(_norm_path(r.full), want)]
        if exact:
            wanted_handler = claim.attrs.get("handler")
            if wanted_handler:
                names = {r.handler.split(".")[-1] for r in exact}
                if str(wanted_handler).split(".")[-1] not in names and all(
                        r.handler_kind != "dynamic" for r in exact):
                    return self.reject(
                        claim, f"{claim.subject} exists but is handled by "
                               f"{', '.join(sorted(names))}, not {wanted_handler!r}",
                        sorted(names))
            r = exact[0]
            return self.accept(claim, f"{r.method} {r.full} -> {r.handler} ({r.file}:{r.line})")
        loose = [r for r in table if (method in ("ANY", "*") or r.method == method)
                 and r.full is None and _norm_path(r.path) and want.endswith(_norm_path(r.path))]
        if loose:
            r = loose[0]
            return self.review(claim, f"{r.method} {r.path} exists in {r.file} under a prefix "
                                      f"weft could not resolve; cannot confirm {claim.subject}")
        same_method = sorted({f"{r.method} {r.full}" for r in table if r.full is not None
                              and (method in ("ANY", "*") or r.method == method)})
        others = sorted({f"{r.method} {r.full}" for r in table if r.full is not None})
        sugg = did_you_mean(f"{method} {path}", same_method) or did_you_mean(
            f"{method} {path}", others)
        return self.reject(claim, f"no route {claim.subject} is registered", sugg)

    def suggest(self, claim: Claim, ctx: Context) -> list[str]:
        if not self._built(ctx):
            return []
        table = self._route_table(ctx)
        return did_you_mean(claim.subject, {f"{r.method} {r.full}" for r in table if r.full})

    def _route_table(self, ctx: Context) -> list[_Route]:
        ns = ctx.store.namespace(self.name)
        routers: dict[tuple[str, str], tuple[str, str]] = {}
        for file, var, kind, prefix in ns.query("SELECT file, var, kind, prefix FROM {t:routers}"):
            routers[(str(file), str(var))] = (str(kind), str(prefix))
        includes: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        for file, _line, parent, child, prefix in ns.query(
            "SELECT file, line, parent, child, prefix FROM {t:includes}"
        ):
            file, child = str(file), str(child)
            head, _, attr = child.partition(".")
            key: tuple[str, str] | None = None
            if attr:
                mod_file = _module_file(ctx, head, file, symbols=self._symbols(ctx, file))
                if mod_file is not None:
                    key = (mod_file, attr)
            else:
                syms = self._symbols(ctx, file) or {}
                binding = syms.get(head)
                if binding and binding[0] == "import" and ":" in binding[1]:
                    module, _, name = binding[1].partition(":")
                    mod_file = _module_file(ctx, module, file)
                    if mod_file is not None:
                        key = (mod_file, name)
                elif binding:
                    key = (file, head)
                else:
                    key = None
            if key is not None:
                includes.setdefault(key, []).append((file, str(parent), str(prefix)))
        out: list[_Route] = []
        for file, line, method, path, handler, hkind, style, router in ns.query(
            "SELECT file, line, method, path, handler, handler_kind, style, router FROM {t:routes}"
        ):
            file, router, path = str(file), str(router), str(path)
            kind, prefix = routers.get((file, router), ("unknown", ""))
            fulls: set[str | None] = set()
            if kind == "app" or (kind == "unknown" and router in ("app", "application")):
                fulls.add(path)
            elif kind == "unknown":
                fulls.add(None)
            else:
                for pre in _prefix_chains(includes, routers, (file, router), depth=0):
                    fulls.add(None if pre is None else pre + prefix + path)
            for full in sorted(fulls, key=lambda x: (x is None, x or "")):
                out.append(_Route(file, int(line), str(method), path, str(handler), str(hkind),
                                  str(style), full))
        return sorted(out, key=lambda r: (r.method, r.full or "", r.path, r.file, r.line))


@dataclass(frozen=True)
class _Route:
    file: str
    line: int
    method: str
    path: str
    handler: str
    handler_kind: str
    style: str
    full: str | None  # resolved full path, None if a prefix could not be resolved


def _prefix_chains(
    includes: dict[tuple[str, str], list[tuple[str, str, str]]],
    routers: dict[tuple[str, str], tuple[str, str]],
    key: tuple[str, str],
    depth: int,
) -> list[str | None]:
    """Every prefix under which router ``key`` is reachable from an app."""
    kind, own_prefix = routers.get(key, ("unknown", ""))
    if kind == "app":
        return [""]
    parents = includes.get(key, [])
    if not parents:
        return [""] if kind in ("router", "unknown") and depth == 0 else [None]
    out: list[str | None] = []
    for file, parent_var, prefix in parents:
        if "?" in prefix:
            out.append(None)
            continue
        if depth >= 4:
            out.append(None)
            continue
        for chain in _prefix_chains(includes, routers, (file, parent_var), depth + 1):
            if chain is None:
                out.append(None)
            else:
                parent_prefix = routers.get((file, parent_var), ("", ""))[1]
                out.append(chain + (parent_prefix if routers.get((file, parent_var),
                                                                 ("", ""))[0] == "router"
                                    else "") + prefix)
    return out or [None]


def _norm_path(path: str) -> str:
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _params_match(a: str, b: str) -> bool:
    pa, pb = a.split("/"), b.split("/")
    if len(pa) != len(pb):
        return False
    return all(x == y or (x.startswith("{") and y.startswith("{")) for x, y in zip(pa, pb,
                                                                                   strict=True))


# --- symbols helpers ---------------------------------------------------------------------------


def _symbol_payload(scan: _Scan) -> dict[str, tuple[str, str]]:
    out = dict(scan.symbols)
    if scan.star_imports:
        out["*"] = ("star", ",".join(scan.star_imports))
    return out


def _symbols_from(
    attrs: dict[str, Any], ctx: Context, rel: str
) -> dict[str, tuple[str, str]] | None:
    raw = attrs.get("symbols")
    if isinstance(raw, dict):
        return {str(k): (str(v[0]), str(v[1])) for k, v in raw.items()}
    oracle = RoutesFastAPIOracle()
    return oracle._symbols(ctx, rel)


def _names_of_kind(symbols: dict[str, tuple[str, str]], kinds: tuple[str, ...]) -> set[str]:
    return {n for n, (k, _) in symbols.items() if k in kinds and n != "*"}


def _join_module(module: str, attr: str) -> str:
    """``from <module> import <attr>`` as one dotted module path (relative-safe)."""
    if module.endswith("."):
        return module + attr
    return f"{module}.{attr}"


def _module_file(
    ctx: Context, module: str, from_file: str, symbols: dict[str, tuple[str, str]] | None = None
) -> str | None:
    """Repo file for ``module`` as seen from ``from_file`` (handles relative imports
    and ``import x as y`` aliases when ``symbols`` are given)."""
    if symbols is not None:
        binding = symbols.get(module)
        if binding and binding[0] == "import":
            target = binding[1]
            if ":" in target:
                mod, _, attr = target.partition(":")
                return _module_file(ctx, _join_module(mod, attr), from_file)
            module = target
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        rest = module.lstrip(".")
        pkg = module_of_file(from_file) or ""
        parts = pkg.split(".") if pkg else []
        if not from_file.endswith("__init__.py"):
            parts = parts[:-1]
        parts = parts[: len(parts) - (dots - 1)] if dots > 1 else parts
        absolute = ".".join(p for p in [*parts, rest] if p)
        return file_of_module(ctx, absolute) if absolute else None
    return file_of_module(ctx, module)


# --- the scanner --------------------------------------------------------------------------


def _scan_python(text: str) -> _Scan | None:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    scan = _Scan()
    scan.uses_fastapi = bool(_FASTAPI_RE.search(text))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                scan.symbols[(a.asname or a.name).split(".")[0]] = ("import", a.name)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for a in node.names:
                if a.name == "*":
                    scan.star_imports.append(module)
                else:
                    scan.symbols[a.asname or a.name] = ("import", f"{module}:{a.name}")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            scan.symbols.setdefault(node.name, ("def", ""))
            for dec in node.decorator_list:
                _decorator_route(dec, node, scan)
        elif isinstance(node, ast.ClassDef):
            scan.symbols.setdefault(node.name, ("class", ""))
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            callee = _dotted(value.func) if isinstance(value, ast.Call) else ""
            for t in targets:
                if isinstance(t, ast.Name):
                    scan.symbols[t.id] = ("assign", callee or "")
                    if isinstance(value, ast.Call) and callee:
                        short = callee.split(".")[-1]
                        if short in ("APIRouter", "Router"):
                            scan.routers[t.id] = ("router", _kw_str(value, "prefix"))
                        elif short in ("FastAPI", "Starlette"):
                            scan.routers[t.id] = ("app", "")
        elif isinstance(node, ast.Call):
            _call_route(node, scan)
    return scan


def _decorator_route(dec: ast.expr, fn: ast.FunctionDef | ast.AsyncFunctionDef,
                     scan: _Scan) -> None:
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return
    router = _dotted(dec.func.value)
    if not router or "." in router:
        return
    method = dec.func.attr
    path = _path_arg(dec)
    if method in _METHODS:
        methods = [method.upper()]
    elif method == "websocket":
        methods = ["WEBSOCKET"]
    elif method in ("api_route", "route"):
        methods = _kw_methods(dec) or ["GET"]
    else:
        return
    for m in methods:
        scan.routes.append((dec.lineno, m, path, fn.name, "name", "decorator", router))


def _call_route(node: ast.Call, scan: _Scan) -> None:
    func = node.func
    if isinstance(func, ast.Attribute):
        router = _dotted(func.value)
        if not router or "." in router:
            return
        if func.attr in _ADD_ROUTE:
            path = _path_arg(node)
            endpoint = node.args[1] if len(node.args) > 1 else _kw(node, "endpoint") or _kw(
                node, "route")
            if endpoint is None:
                return
            handler, hkind = _endpoint(endpoint)
            methods = ["WEBSOCKET"] if "websocket" in func.attr else (_kw_methods(node) or ["GET"])
            for m in methods:
                scan.routes.append((node.lineno, m, path, handler, hkind, func.attr, router))
        elif func.attr == "include_router":
            child = node.args[0] if node.args else _kw(node, "router")
            if child is None:
                return
            text, ckind = _endpoint(child)
            prefix_node = _kw(node, "prefix")
            prefix = _kw_str(node, "prefix") if prefix_node is None or isinstance(
                prefix_node, ast.Constant) else "?"
            scan.includes.append((node.lineno, router, text if ckind != "dynamic" else
                                  f"<{text}>", prefix))
    elif isinstance(func, ast.Name) and func.id in _ROUTE_CLASSES:
        path = _path_arg(node)
        endpoint = node.args[1] if len(node.args) > 1 else _kw(node, "endpoint")
        if endpoint is None:
            return
        handler, hkind = _endpoint(endpoint)
        methods = ["WEBSOCKET"] if func.id == "WebSocketRoute" else (_kw_methods(node) or ["GET"])
        for m in methods:
            scan.routes.append((node.lineno, m, path, handler, hkind, func.id, ""))


def _endpoint(node: ast.expr) -> tuple[str, str]:
    dotted = _dotted(node)
    if dotted is not None:
        return dotted, ("attribute" if "." in dotted else "name")
    try:
        text = ast.unparse(node)
    except Exception:  # noqa: BLE001
        text = type(node).__name__
    return text, "dynamic"


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _path_arg(call: ast.Call) -> str:
    """The route path: first positional string or ``path=``; '?' when not a literal."""
    first = _first_str(call)
    if first is not None:
        return first
    node = _kw(call, "path")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return "?"


def _first_str(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(
            call.args[0].value, str):
        return call.args[0].value
    return None


def _kw(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _kw_str(call: ast.Call, name: str) -> str:
    node = _kw(call, name)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return "" if node is None else "?"


def _kw_methods(call: ast.Call) -> list[str]:
    node = _kw(call, "methods")
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        out = [e.value.upper() for e in node.elts if isinstance(e, ast.Constant)
               and isinstance(e.value, str)]
        return out or ["?"]
    return ["?"] if node is not None else []


def _extract_regex(region: Region) -> list[Claim]:
    """Fallback for diff fragments that do not parse on their own."""
    claims: list[Claim] = []
    for lineno, text in region.lines():
        m = _RX_ADD.search(text)
        if m:
            handler = m.group(4).strip()
            hkind = "dynamic" if not re.fullmatch(r"[\w.]+", handler) else (
                "attribute" if "." in handler else "name")
            claims.append(Claim("route_handler", f"GET {m.group(3)}",
                                Location(region.file, lineno),
                                {"handler": handler, "handler_kind": hkind, "style": m.group(2),
                                 "router": m.group(1)}, hard=hkind != "dynamic"))
            continue
        m = _RX_INC.search(text)
        if m:
            child = m.group(2).strip()
            ckind = "dynamic" if not re.fullmatch(r"[\w.]+", child) else (
                "attribute" if "." in child else "name")
            claims.append(Claim("router_include", child, Location(region.file, lineno),
                                {"parent": m.group(1), "child_kind": ckind, "prefix": ""},
                                hard=ckind != "dynamic"))
            continue
        m = _RX_DEC.match(text)
        if m:
            claims.append(Claim("route_handler", f"{m.group(2).upper()} {m.group(3)}",
                                Location(region.file, lineno),
                                {"handler": "?", "handler_kind": "name", "style": "decorator",
                                 "router": m.group(1)}))
    return claims


def describe_routes(ctx: Context) -> list[dict[str, Any]]:
    """Debug helper: the resolved route table (used by ``weft index``)."""
    oracle = RoutesFastAPIOracle()
    if not oracle._built(ctx):
        return []
    return [{"method": r.method, "path": r.full or f"?{r.path}", "handler": r.handler,
             "file": r.file, "line": r.line} for r in oracle._route_table(ctx)]


def register(api: OracleAPI) -> None:
    api.register_oracle(RoutesFastAPIOracle())

