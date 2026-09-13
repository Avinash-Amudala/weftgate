"""Grounded repository slices over the gate's current contracts and a Python AST cache.

    resolve: exact nodes with provenance
    neighbors: bounded observed relationships, never speculative runtime calls
    card: a three-hop contract slice for a route, symbol, file or environment name

File bodies and environment values never enter responses. Parsing is cached by
content hash; every read verifies freshness, including uncommitted edits.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from .change import Change
from .gate import Session
from .payload import bounded, encode
from .types import Level

MAX_SOURCE_BYTES = 512_000
SOURCE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


def safe_path(root: str, relative: str) -> str | None:
    """Reject escaping paths and symlinks, including symlinked parent directories."""
    if not relative or os.path.isabs(relative):
        return None
    base = os.path.realpath(root)
    path = os.path.abspath(os.path.join(base, relative))
    try:
        if os.path.commonpath([base, path]) != base or os.path.realpath(path) != path:
            return None
    except ValueError:
        return None
    return path


def source(root: str, relative: str) -> str | None:
    path = safe_path(root, relative)
    if path is None:
        return None
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES or b"\0" in data:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeError):
        return None


@dataclass
class Graph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)

    def node(self, kind: str, name: str, file: str = "", line: int = 0) -> str:
        ident = f"{kind}:{name}"
        value = self.nodes.setdefault(ident, {"id": ident, "kind": kind, "name": name})
        if file:
            where = {"file": file, "line": line}
            locations = value.setdefault("locations", [])
            if where not in locations:
                locations.append(where)
        return ident

    def edge(self, origin: str, target: str, kind: str, file: str, line: int = 0) -> None:
        edge = {"from": origin, "to": target, "relation": kind, "file": file, "line": line}
        if edge not in self.edges:
            self.edges.append(edge)


def _symbols(text: str, file: str) -> list[dict[str, Any]]:
    if not file.endswith(".py"):
        return []
    tree = ast.parse(text, filename=file)
    out: list[dict[str, Any]] = []

    def visit(node: ast.AST, parents: list[str]) -> None:
        scope = parents
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = [*parents, node.name]
            out.append(
                {
                    "name": ".".join(scope),
                    "line": node.lineno,
                    "end": node.end_lineno or node.lineno,
                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                }
            )
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, [])
    return out


def _cached_symbols(session: Session, file: str, text: str) -> list[dict[str, Any]]:
    ns = session.store.namespace("context")
    if not ns.exists("parsed"):
        ns.rebuild("parsed", "file TEXT PRIMARY KEY, digest TEXT, payload TEXT", [])
    digest = hashlib.sha256(text.encode()).hexdigest()
    rows = ns.query("SELECT digest, payload FROM {t:parsed} WHERE file=?", (file,))
    if rows and rows[0][0] == digest:
        result: list[dict[str, Any]] = json.loads(rows[0][1])
        return result
    result = _symbols(text, file)
    with session.store.transaction():
        ns.replace_file("parsed", file, [(file, digest, encode(result))])
    return result


def build(session: Session) -> Graph:
    session.sync()
    graph = Graph()
    files = session.store.all_files()
    symbols: dict[str, list[dict[str, Any]]] = {}
    texts: dict[str, str] = {}
    for file in files:
        if safe_path(session.repo_root, file) is None:
            graph.notes.append({"file": file, "reason": "symlink or outside repository; skipped"})
            continue
        # Never inventory hidden credentials, databases, or arbitrary binary assets.
        if not file.endswith(SOURCE_SUFFIXES):
            continue
        text = source(session.repo_root, file)
        if text is None:
            graph.notes.append({"file": file, "reason": "unreadable, binary or oversized source"})
            continue
        texts[file] = text
        origin = graph.node("file", file, file)
        try:
            symbols[file] = _cached_symbols(session, file, text)
        except (SyntaxError, RecursionError):
            graph.notes.append({"file": file, "reason": "Python syntax could not be parsed"})
            symbols[file] = []
        for symbol in symbols[file]:
            target = graph.node("symbol", f"{file}:{symbol['name']}", file, symbol["line"])
            graph.nodes[target]["symbol_type"] = symbol["type"]
            graph.edge(origin, target, "declares", file, symbol["line"])

    env = session.store.namespace("env_vars")
    if "env_vars" in session.oracles and session.store.is_built("env_vars") and env.exists("decl"):
        for name, file in env.query("SELECT name, file FROM {t:decl} ORDER BY name,file"):
            if safe_path(session.repo_root, str(file)):
                target = graph.node("env", str(name), str(file))
                graph.edge(graph.node("file", str(file), str(file)), target, "declares", str(file))

    imports = session.store.namespace("imports_lockfile")
    if (
        "imports_lockfile" in session.oracles
        and session.store.is_built("imports_lockfile")
        and imports.exists("provided")
    ):
        for lang, name, dist, file in imports.query(
            "SELECT lang,name,dist,source FROM {t:provided} WHERE core=0 "
            "ORDER BY lang,name,dist,source"
        ):
            if safe_path(session.repo_root, str(file)):
                target = graph.node("import", f"{lang}:{name}", str(file))
                graph.nodes[target]["distribution"] = str(dist)
                graph.edge(
                    graph.node("file", str(file), str(file)),
                    target,
                    "declares_dependency",
                    str(file),
                )

    for file, text in texts.items():
        result = session.check_change(Change.from_text(file, text), sync=False)
        for finding in result.findings:
            claim = finding.claim
            if finding.level is not Level.ACCEPT:
                graph.notes.append(
                    {
                        "file": file,
                        "line": claim.location.line,
                        "level": finding.level.value,
                        "kind": claim.kind,
                        "reason": finding.reason[:300],
                    }
                )
                continue
            target = ""
            if claim.kind == "env_var":
                target = f"env:{claim.subject}"
            elif claim.kind == "import":
                lang = str(claim.attrs.get("lang") or ("python" if file.endswith(".py") else "js"))
                target = f"import:{lang}:{claim.subject.split('.')[0]}"
            if target not in graph.nodes:
                continue
            line = claim.location.line
            owners = [s for s in symbols[file] if s["line"] <= line <= s["end"]]
            owner = min(owners, key=lambda s: (s["end"] - s["line"], s["name"])) if owners else None
            origin = f"symbol:{file}:{owner['name']}" if owner else f"file:{file}"
            graph.edge(
                origin, target, "reads_env" if claim.kind == "env_var" else "imports", file, line
            )

    if "routes_fastapi" in session.oracles and session.store.is_built("routes_fastapi"):
        from .oracles.routes_fastapi import describe_routes

        for route in describe_routes(session.ctx):
            file = route["file"]
            if route["path"].startswith("?") or file not in texts:
                continue
            origin = graph.node("route", f"{route['method']} {route['path']}", file, route["line"])
            graph.nodes[origin]["declared_handler"] = route["handler"]
            graph.edge(f"file:{file}", origin, "registers_route", file, route["line"])
            # Only direct, unique local definitions. Imported/dynamic handlers are
            # left unresolved here; the gate still verifies their supported contracts.
            candidates = [s for s in symbols[file] if s["name"] == route["handler"]]
            if len(candidates) == 1:
                graph.edge(
                    origin,
                    f"symbol:{file}:{candidates[0]['name']}",
                    "declared_handler",
                    file,
                    route["line"],
                )
    graph.edges.sort(key=encode)
    graph.notes.sort(key=encode)
    return graph


def query(
    session: Session,
    operation: str,
    reference: str,
    *,
    hops: int = 1,
    kinds: list[str] | None = None,
    budget: int | None = None,
) -> dict[str, Any]:
    if operation not in ("resolve", "neighbors", "card"):
        raise ValueError("context operation must be resolve, neighbors or card")
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 256:
        raise ValueError("reference must contain 1 to 256 characters")
    if isinstance(hops, bool) or not isinstance(hops, int) or not 1 <= hops <= 3:
        raise ValueError("hops must be an integer from 1 to 3")
    if kinds is not None and (
        not isinstance(kinds, list)
        or any(k not in {"file", "symbol", "env", "import", "route"} for k in kinds)
    ):
        raise ValueError("kinds must contain file, symbol, env, import or route")
    graph = build(session)
    ref = reference.strip()
    roots = sorted(
        k for k, n in graph.nodes.items() if ref in (k, n["name"], n["name"].rsplit(":", 1)[-1])
    )
    roots = [k for k in roots if not kinds or graph.nodes[k]["kind"] in kinds]
    items: list[dict[str, Any]] = [{"node": graph.nodes[k], "distance": 0} for k in roots]
    visited = set(roots)
    selected_edges: list[dict[str, Any]] = []
    depth = 0 if operation == "resolve" else (3 if operation == "card" else hops)
    frontier = set(roots)
    for distance in range(1, depth + 1):
        following: set[str] = set()
        for edge in graph.edges:
            if edge["from"] not in frontier and edge["to"] not in frontier:
                continue
            if edge not in selected_edges:
                selected_edges.append(edge)
            following.update((edge["from"], edge["to"]))
        following -= visited
        for key in sorted(following):
            if not kinds or graph.nodes[key]["kind"] in kinds:
                items.append({"node": graph.nodes[key], "distance": distance})
        visited.update(following)
        frontier = following
    # Each edge carries complete locators; references remain meaningful if a node
    # card is omitted to fit the budget.
    items.extend({"edge": edge} for edge in selected_edges)
    relevant_files = {loc["file"] for k in visited for loc in graph.nodes[k].get("locations", [])}
    notes = [n for n in graph.notes if n.get("file") in relevant_files]
    items.extend({"note": note} for note in notes)
    return bounded(
        items,
        {
            "operation": operation,
            "reference": ref,
            "status": "resolved" if len(roots) == 1 else ("ambiguous" if roots else "not_found"),
            "matches": len(roots),
            "commit": session.ctx.git_commit,
            "suggestions": []
            if roots
            else difflib.get_close_matches(ref, sorted(graph.nodes), n=3),
            "coverage": "Python definitions; declared env, dependencies and FastAPI routes. "
            "Static relationships, not runtime call dispatch or prose validation.",
            "index_notes": len(graph.notes),
        },
        budget,
    )
