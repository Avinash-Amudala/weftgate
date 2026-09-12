"""imports_lockfile: the three required tests plus lockfile parsers and the
verdict ladder (stdlib, local, alias, installed-but-unlocked, no lockfile)."""

import json
import os

from tests.conftest import write
from weft.change import Change
from weft.config import Config
from weft.oracle import Context
from weft.oracles.imports_lockfile import ImportsLockfileOracle, _parse_manifest, norm
from weft.store import Store
from weft.types import Level


def _ctx(root, config=None):
    store = Store(root, path=os.path.join(os.path.dirname(root), "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=config or Config())
    ImportsLockfileOracle().build(ctx)
    ctx.store.finish_sync(None)
    return ctx


def _check(root, code, name="m.py", ctx=None):
    ctx = ctx or _ctx(root)
    oracle = ImportsLockfileOracle()
    change = Change.from_file(write(root, name, code), repo_root=root)
    return {f.claim.subject: f for f in (oracle.check(c, ctx) for c in oracle.extract(change, ctx))}


def _repo(tmp_path, lock="requirements.txt",
          body="requests==2.32.0\nPyYAML==6.0.2\nflask==3.0.3\n"):
    root = str(tmp_path / "repo")
    os.makedirs(root, exist_ok=True)
    write(root, lock, body)
    return root


# --- the three required tests -------------------------------------------------------------


def test_true_positive_phantom_package_rejects(tmp_path):
    root = _repo(tmp_path)
    res = _check(root, "import requestz\nfrom flsk import Flask\n")
    assert res["requestz"].level is Level.REJECT
    assert res["requestz"].suggestions[0] == "requests"
    assert "slopsquat" in res["requestz"].reason
    assert res["flsk"].level is Level.REJECT and res["flsk"].suggestions[0] == "flask"


def test_true_negative_locked_stdlib_and_local_accept(tmp_path):
    root = _repo(tmp_path)
    write(root, "app/__init__.py", "")
    write(root, "app/models.py", "")
    write(root, "helpers.py", "")
    res = _check(
        root,
        "import os\nimport sys, json\nfrom collections import abc\n"
        "import requests\nfrom flask.views import View\nimport yaml\n"
        "from app.models import Thing\nimport helpers\nfrom . import sibling\n",
    )
    for name in ("os", "sys", "json", "collections", "requests", "flask.views", "yaml",
                 "app.models", "helpers"):
        assert res[name].level is Level.ACCEPT, (name, res[name].reason)
    assert "PyYAML" in res["yaml"].reason  # alias table: import yaml <- PyYAML
    assert "sibling" not in res  # relative imports are never claims


def test_soft_dynamic_and_optional_imports_review(tmp_path):
    root = _repo(tmp_path)
    res = _check(
        root,
        "import importlib\nname = 'x'\nmod = importlib.import_module(name)\n"
        "try:\n    import notarealpkg_xyz\nexcept ImportError:\n    notarealpkg_xyz = None\n",
    )
    assert res["<dynamic>"].level is Level.REVIEW and not res["<dynamic>"].claim.hard
    opt = res["notarealpkg_xyz"]
    assert opt.level is Level.REVIEW and "optional" in opt.reason


# --- wider behaviour -------------------------------------------------------------------------


def test_unverifiable_without_index_or_lockfile(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "m.py", "import requests\n")
    store = Store(root, path=str(tmp_path / "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=Config())
    oracle = ImportsLockfileOracle()
    change = Change.from_file(os.path.join(root, "m.py"), repo_root=root)
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    assert findings[0].level is Level.UNVERIFIABLE and "not built" in findings[0].reason
    oracle.build(ctx)
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    assert findings[0].level is Level.UNVERIFIABLE and "no python lockfile" in findings[0].reason
    store.close()


def test_installed_but_unlocked_reviews_and_locked_dist_resolves_import_name(tmp_path):
    # pytest is installed in the test environment but not in this lockfile.
    root = _repo(tmp_path, body="requests==2.32.0\n")
    res = _check(root, "import pytest\n")
    assert res["pytest"].level is Level.REVIEW and "installed here" in res["pytest"].reason
    # Locked under its distribution name; the installed metadata maps the import name.
    root2 = _repo(tmp_path / "two", body="pytest==8.0\n")
    res = _check(root2, "import pytest\nimport _pytest\n")
    assert res["pytest"].level is Level.ACCEPT
    assert res["_pytest"].level is Level.ACCEPT and "installed metadata" in res["_pytest"].reason


def test_substring_relation_reviews_not_rejects(tmp_path):
    root = _repo(tmp_path, body="python-someproj==1.0\n")  # pinned: lockfile-class
    res = _check(root, "import someproj\n")
    assert res["someproj"].level is Level.REVIEW and "python-someproj" in res["someproj"].reason


def test_node_imports(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "package.json", json.dumps({
        "name": "site", "dependencies": {"lodash": "4", "@scope/pkg": "1", "react": "18"},
        "devDependencies": {"vitest": "1"}, "workspaces": ["packages/*"]}))
    write(root, "package-lock.json", json.dumps({"name": "site", "packages": {
        "node_modules/lodash": {}, "node_modules/@scope/pkg": {}, "node_modules/react": {},
        "node_modules/vitest": {}}}))
    write(root, "packages/ui/package.json", json.dumps({"name": "@site/ui"}))
    write(root, "node_modules/leftpad/package.json", "{}")
    res = _check(
        root,
        "import _ from 'lodash';\nimport { x } from \"@scope/pkg/sub\";\n"
        "import fs from 'node:fs';\nimport path from 'path';\nimport './local.css';\n"
        "import cfg from '@/config';\nimport ui from '@site/ui';\n"
        "const r = require('reakt');\nconst d = await import('lodsh');\n"
        "import lp from 'leftpad';\nconst dyn = require(name);\n// import junk from 'nope';\n",
        name="app.ts",
    )
    assert res["lodash"].level is Level.ACCEPT and res["@scope/pkg/sub"].level is Level.ACCEPT
    assert res["node:fs"].level is Level.ACCEPT and res["path"].level is Level.ACCEPT
    assert "./local.css" not in res and "@/config" not in res and "nope" not in res
    assert res["@site/ui"].level is Level.ACCEPT
    assert res["reakt"].level is Level.REJECT and res["reakt"].suggestions[0] == "react"
    assert res["lodsh"].level is Level.REJECT and res["lodsh"].suggestions[0] == "lodash"
    assert res["leftpad"].level is Level.REVIEW and "node_modules" in res["leftpad"].reason
    assert res["<dynamic>"].level is Level.REVIEW


def test_lockfile_parsers(tmp_path):
    ctx = _ctx(_repo(tmp_path))
    poetry = '[[package]]\nname = "Django"\nversion = "5.0"\n\n[[package]]\nname = "celery"\n'
    assert _parse_manifest("poetry.lock", poetry, ctx, "poetry.lock")[0] == {"Django", "celery"}
    assert _parse_manifest("uv.lock", poetry, ctx, "uv.lock")[0] == {"Django", "celery"}
    pipfile_lock = json.dumps({"default": {"numpy": {}}, "develop": {"black": {}}})
    assert _parse_manifest("Pipfile.lock", pipfile_lock, ctx, "x")[0] == {"numpy", "black"}
    pipfile = '[packages]\nnumpy = "*"\n\n[dev-packages]\nblack = "*"\n'
    assert _parse_manifest("Pipfile", pipfile, ctx, "Pipfile")[0] == {"numpy", "black"}
    req = ("# comment\nrequests[security]==2.0 ; python_version>'3'\n-r other.txt\n"
           "-e git+https://x/y.git#egg=mypkg\nhttpx @ https://example/httpx.whl\n"
           "--index-url https://pypi.org/simple\nfoo-bar_baz\n")
    assert _parse_manifest("requirements-dev.txt", req, ctx, "r")[0] == {
        "requests", "mypkg", "httpx", "foo-bar_baz"}
    pyproject = ('[project]\nname = "my-proj"\n'
                 'dependencies = ["fastapi>=0.1", "uvicorn[standard]"]\n'
                 '[project.optional-dependencies]\ndev = ["pytest"]\n'
                 '[tool.poetry.dependencies]\npython = "^3.10"\nrich = "*"\n'
                 '[tool.poetry.group.dev.dependencies]\nmypy = "*"\n'
                 '[dependency-groups]\nlint = ["ruff"]\n')
    dists, own = _parse_manifest("pyproject.toml", pyproject, ctx, "pyproject.toml")
    assert dists == {"fastapi", "uvicorn", "pytest", "rich", "mypy", "ruff"} and own == {"my_proj"}
    cfg = "[options]\ninstall_requires =\n    attrs>=20\n    six\n[options.extras_require]\n" \
          "test =\n    pytest\n"
    assert _parse_manifest("setup.cfg", cfg, ctx, "setup.cfg")[0] == {"attrs", "six", "pytest"}
    conda = "dependencies:\n  - python=3.11\n  - numpy=1.26\n  - pip\n  - pip:\n    - torch\n"
    assert _parse_manifest("environment.yml", conda, ctx, "e")[0] == {"numpy", "torch"}
    lock = json.dumps({"name": "site", "packages": {
        "": {"dependencies": {"react": "18"}},
        "node_modules/react": {}, "node_modules/react/node_modules/loose-envify": {},
        "node_modules/@scope/x": {}, "packages/ui": {"name": "@site/ui"}},
        "dependencies": {"legacy": {"dependencies": {"nested": {}}}}})
    dists, own = _parse_manifest("package-lock.json", lock, ctx, "package-lock.json")
    assert dists == {"react", "loose-envify", "@scope/x", "legacy", "nested"}
    assert own == {"site", "@site/ui"}
    pnpm = ("lockfileVersion: '9.0'\nimporters:\n  .:\n    dependencies:\n      lodash:\n"
            "        specifier: ^4\n        version: 4.17.21\npackages:\n  /lodash@4.17.21:\n"
            "    resolution: {integrity: sha}\n  '@scope/pkg@1.0.0':\n    resolution: {}\n"
            "  vite@5.0.0:\n    engines: {node: '>=18'}\n")
    assert _parse_manifest("pnpm-lock.yaml", pnpm, ctx, "p")[0] == {"lodash", "@scope/pkg", "vite"}
    yarn = ('# yarn lockfile v1\n\n"@babel/core@^7.0.0", "@babel/core@^7.2.0":\n  version "7.2"\n\n'
            'lodash@^4.17.21:\n  version "4.17.21"\n\n"react@npm:^18.0.0":\n  version "18"\n')
    assert _parse_manifest("yarn.lock", yarn, ctx, "y")[0] == {"@babel/core", "lodash", "react"}
    assert _parse_manifest("package.json", "{not json", ctx, "package.json") == (set(), set())
    assert norm("Foo-Bar.baz") == "foo_bar_baz"
    ctx.store.close()


def test_regex_fallback_for_diff_fragments(tmp_path):
    root = _repo(tmp_path)
    ctx = _ctx(root)
    oracle = ImportsLockfileOracle()
    diff = ("--- a/m.py\n+++ b/m.py\n@@ -5,0 +6,3 @@\n+    import requestz\n"
            "+    from flask import Flask  # ok\n+    mod = importlib.import_module('yaml')\n")
    change = Change.from_unified_diff(diff)
    res = {f.claim.subject: f for f in (oracle.check(c, ctx) for c in oracle.extract(change, ctx))}
    assert res["requestz"].level is Level.REJECT and res["requestz"].claim.location.line == 6
    assert res["flask"].level is Level.ACCEPT and res["yaml"].level is Level.ACCEPT
    ctx.store.close()


def test_sync_rebuilds_on_manifest_change(tmp_path):
    root = _repo(tmp_path, body="requests==2.32.0\n")
    ctx = _ctx(root)
    oracle = ImportsLockfileOracle()
    assert _check(root, "import httpx\n", ctx=ctx)["httpx"].level is Level.REJECT
    write(root, "requirements.txt", "requests==2.32.0\nhttpx==0.27.0\n")
    oracle.sync(ctx, None)
    ctx.store.finish_sync(None)
    assert _check(root, "import httpx\n", ctx=ctx)["httpx"].level is Level.ACCEPT
    ctx.store.close()
