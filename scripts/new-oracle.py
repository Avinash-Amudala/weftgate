#!/usr/bin/env python3
"""Scaffold a new oracle and its three required tests.

    python scripts/new-oracle.py config_keys --kind config_key
    python scripts/new-oracle.py config_keys --kind config_key --package yourpkg   # out of tree

Writes <package>/oracles/<name>.py and tests/test_<name>.py, and for in-tree oracles
registers the name in weftgate/oracles/__init__.py and pyproject.toml.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ORACLE = '''"""{name}: <one sentence: what relationship this oracle verifies>.

<Which artifacts it reads, what a proven absence looks like, and what stays soft.>

A <reference> that resolves           -> ACCEPT
A <reference> declared nowhere        -> REJECT (with a did-you-mean suggestion)
A dynamic / computed <reference>      -> REVIEW (cannot resolve the name)
No index yet                          -> UNVERIFIABLE
"""

from __future__ import annotations

import re

from {base}.change import Change
from {base}.oracle import BaseOracle, Context, OracleAPI
from {base}.suggest import did_you_mean
from {base}.types import Claim, Finding, Location

# TODO: the references your oracle can name (group 1 is the literal name).
_READ = re.compile(r"TODO_PATTERN\\(\\s*['\\"]([A-Za-z_][A-Za-z0-9_]*)['\\"]")
# TODO: a reference you can see but cannot name.
_DYNAMIC = re.compile(r"TODO_PATTERN\\(\\s*(?![\\"'])\\S")
_SUFFIXES = (".py",)


class {cls}(BaseOracle):
    name = "{name}"
    kinds: tuple[str, ...] = ("{kind}",)
    version = "1"

    _COLUMNS = "file TEXT NOT NULL, name TEXT NOT NULL"

    # --- index -----------------------------------------------------------------

    def build(self, ctx: Context) -> None:
        rows = [(rel, name) for rel in ctx.files(_SUFFIXES) for name in self._declared_in(ctx, rel)]
        ctx.store.namespace(self.name).rebuild("decl", self._COLUMNS, sorted(set(rows)),
                                               indexes=["file", "name"])

    def sync(self, ctx: Context, since: str | None) -> None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("decl"):
            self.build(ctx)
            return
        for rel in ctx.store.sync_files(since):
            if rel.endswith(_SUFFIXES):
                rows = [(rel, name) for name in self._declared_in(ctx, rel)]
                ns.replace_file("decl", rel, sorted(set(rows)))

    def _declared_in(self, ctx: Context, rel: str) -> set[str]:
        text = ctx.read_text(rel)
        if text is None:
            return set()
        return set()  # TODO: the names this file declares

    def _declared(self, ctx: Context) -> set[str] | None:
        ns = ctx.store.namespace(self.name)
        if not ns.exists("decl"):
            return None
        return {{str(r[0]) for r in ns.query("SELECT DISTINCT name FROM {{t:decl}}")}}

    # --- extract + check -------------------------------------------------------

    def extract(self, change: Change, ctx: Context) -> list[Claim]:
        claims: list[Claim] = []
        for region in change.added_regions():
            if not region.file.endswith(_SUFFIXES):
                continue
            for lineno, text in region.lines():
                found = False
                for m in _READ.finditer(text):
                    found = True
                    claims.append(Claim("{kind}", m.group(1),
                                        Location(region.file, lineno, m.start() + 1)))
                if not found and _DYNAMIC.search(text):
                    claims.append(Claim("{kind}", "<dynamic>", Location(region.file, lineno),
                                        hard=False))
        return claims

    def check(self, claim: Claim, ctx: Context) -> Finding:
        declared = self._declared(ctx)
        if declared is None:
            return self.unverifiable(claim, "{name} index not built")
        if claim.subject == "<dynamic>":
            return self.review(claim, "reference computed at runtime; cannot resolve the name")
        if claim.subject in declared:
            return self.accept(claim, "declared")
        if not declared:
            return self.review(claim, "no declaration source found in the repo")
        return self.reject(claim, f"{{claim.subject!r}} is referenced but declared nowhere",
                           did_you_mean(claim.subject, declared))

    def suggest(self, claim: Claim, ctx: Context) -> list[str]:
        return did_you_mean(claim.subject, self._declared(ctx) or set())


def register(api: OracleAPI) -> None:
    api.register_oracle({cls}())
'''

TEST = '''"""The three required tests for {name}: true positive, true negative, soft case."""

import os

from tests.conftest import write
from {base}.change import Change
from {base}.config import Config
from {base}.oracle import Context
from {base}.store import Store
from {base}.types import Level
from {module} import {cls}


def _ctx(root):
    store = Store(root, path=os.path.join(os.path.dirname(root), "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=Config())
    {cls}().build(ctx)
    ctx.store.finish_sync(None)
    return ctx


def _check(root, code, name="m.py"):
    ctx = _ctx(root)
    oracle = {cls}()
    change = Change.from_file(write(root, name, code), repo_root=root)
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    return {{f.claim.subject: f for f in findings}}


def test_true_negative_declared_reference_accepts(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "TODO_declaration_file", "TODO")
    res = _check(root, "TODO code that references a declared name\\n")
    assert res["TODO_NAME"].level is Level.ACCEPT


def test_true_positive_undeclared_reference_rejects(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "TODO_declaration_file", "TODO")
    res = _check(root, "TODO code that references a missing name\\n")
    assert res["TODO_MISSING"].level is Level.REJECT
    assert res["TODO_MISSING"].suggestions  # a reject is a fix, not just a complaint


def test_soft_dynamic_reference_reviews_not_rejects(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "TODO_declaration_file", "TODO")
    res = _check(root, "TODO code with a computed reference\\n")
    assert res["<dynamic>"].level is Level.REVIEW


def test_unverifiable_without_index(tmp_path):
    root = str(tmp_path / "repo")
    store = Store(root, path=str(tmp_path / "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=Config())
    oracle = {cls}()
    change = Change.from_file(write(root, "m.py", "TODO code with a reference\\n"), repo_root=root)
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    assert all(f.level is Level.UNVERIFIABLE for f in findings)
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("name", help="oracle name, e.g. config_keys")
    ap.add_argument("--kind", required=True, help="claim kind, e.g. config_key")
    ap.add_argument(
        "--package", default="weftgate", help="package to write into (default: weftgate, in-tree)"
    )
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.name):
        print("name must be lowercase identifier-like (a-z, 0-9, _)", file=sys.stderr)
        return 2
    cls = "".join(p.capitalize() for p in args.name.split("_")) + "Oracle"
    in_tree = args.package == "weftgate"
    base = "weftgate"
    pkg_dir = os.path.join(args.root, args.package, "oracles" if in_tree else "")
    os.makedirs(pkg_dir, exist_ok=True)
    module = f"weftgate.oracles.{args.name}" if in_tree else f"{args.package}.{args.name}"
    oracle_path = os.path.join(pkg_dir, f"{args.name}.py")
    test_path = os.path.join(args.root, "tests", f"test_{args.name}.py")
    for path in (oracle_path, test_path):
        if os.path.exists(path):
            print(f"refusing to overwrite {path}", file=sys.stderr)
            return 2
    with open(oracle_path, "w", encoding="utf-8") as fh:
        fh.write(ORACLE.format(name=args.name, cls=cls, kind=args.kind, base=base))
    os.makedirs(os.path.dirname(test_path), exist_ok=True)
    with open(test_path, "w", encoding="utf-8") as fh:
        fh.write(TEST.format(name=args.name, cls=cls, base=base, module=module))
    print(f"wrote {os.path.relpath(oracle_path, args.root)}")
    print(f"wrote {os.path.relpath(test_path, args.root)}")
    if in_tree:
        _register_in_tree(args.root, args.name)
    else:
        print(
            f'register it: entry point [project.entry-points."weftgate.oracles"] '
            f'{args.name} = "{module}:register", or list "{module}" in weftgate.toml'
        )
    print("next: replace every TODO, then run the four checks")
    return 0


def _register_in_tree(root: str, name: str) -> None:
    init = os.path.join(root, "weftgate", "oracles", "__init__.py")
    with open(init, encoding="utf-8") as fh:
        text = fh.read()
    line = f'    "{name}": "weftgate.oracles.{name}:register",\n'
    if line not in text:
        text = text.replace("}\n", line + "}\n", 1) if text.rstrip().endswith("}") else text + line
        with open(init, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("registered in weftgate/oracles/__init__.py")
    pyproject = os.path.join(root, "pyproject.toml")
    with open(pyproject, encoding="utf-8") as fh:
        text = fh.read()
    ep = f'{name} = "weftgate.oracles.{name}:register"\n'
    marker = '[project.entry-points."weftgate.oracles"]\n'
    if ep not in text and marker in text:
        text = text.replace(marker, marker + ep, 1)
        with open(pyproject, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("registered entry point in pyproject.toml (re-run pip install -e . to expose it)")


if __name__ == "__main__":
    raise SystemExit(main())
