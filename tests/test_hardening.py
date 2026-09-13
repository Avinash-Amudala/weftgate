"""False-reject hardening: the cases a real repo hits that a fixture does not."""

import json
import os
from pathlib import Path

from tests.conftest import write
from weftgate import cli, mcp_server
from weftgate.change import Change
from weftgate.config import Config
from weftgate.oracle import Context
from weftgate.oracles.env_vars import EnvVarOracle, mask_comments
from weftgate.oracles.imports_lockfile import ImportsLockfileOracle
from weftgate.store import Store
from weftgate.types import Level


def _ctx(root, oracle, config=None):
    store = Store(root, path=os.path.join(os.path.dirname(root), "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=config or Config())
    oracle.build(ctx)
    ctx.store.finish_sync(None)
    return ctx


def _run(root, oracle, name, code, ctx=None):
    ctx = ctx or _ctx(root, oracle)
    change = Change.from_file(write(root, name, code), repo_root=root)
    return {f.claim.subject: f for f in (oracle.check(c, ctx) for c in oracle.extract(change, ctx))}


# --- env_vars ---------------------------------------------------------------------------------


def test_no_declaration_source_reviews_instead_of_rejecting(tmp_path):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    res = _run(root, EnvVarOracle(), "m.py", "import os\nx = os.environ['ANYTHING']\n")
    f = res["ANYTHING"]
    assert f.level is Level.REVIEW and "no env declaration source" in f.reason
    # The moment one source exists, a proven absence is a reject again.
    write(root, ".env.example", "OTHER=\n")
    res = _run(root, EnvVarOracle(), "m.py", "import os\nx = os.environ['ANYTHING']\n")
    assert res["ANYTHING"].level is Level.REJECT


def test_comment_masking_keeps_strings_and_lines():
    text = (
        "const a = process.env.REAL; // process.env.IN_LINE_COMMENT\n"
        "/* process.env.IN_BLOCK\n   still */ const b = `${process.env.IN_TEMPLATE}`;\n"
        'const url = "http://x/y"; const c = process.env.AFTER_URL;\n'
        "const s = 'it\\'s // not a comment'; const d = process.env.AFTER_ESC;\n"
    )
    masked = mask_comments(text)
    assert masked.count("\n") == text.count("\n")
    assert "IN_LINE_COMMENT" not in masked and "IN_BLOCK" not in masked
    for keep in ("REAL", "IN_TEMPLATE", "AFTER_URL", "AFTER_ESC", "http://x/y"):
        assert keep in masked
    assert "# comment" not in mask_comments("x = 1 # comment\n", style="hash")
    assert "'#no'" in mask_comments("x = '#no' # yes\n", style="hash")


def test_js_reads_in_comments_are_not_claims(tmp_path):
    root = str(tmp_path / "repo")
    write(root, ".env.example", "REAL=\nIN_TEMPLATE=\n")
    res = _run(
        root,
        EnvVarOracle(),
        "app.ts",
        "const a = process.env.REAL; // process.env.GHOST_ONE\n"
        "/* process.env.GHOST_TWO */\nconst b = `${process.env.IN_TEMPLATE}`;\n",
    )
    assert set(res) == {"REAL", "IN_TEMPLATE"}
    assert all(f.level is Level.ACCEPT for f in res.values())


# --- imports_lockfile: TypeScript --------------------------------------------------------------


def test_tsconfig_paths_and_base_url_resolve(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "package.json", json.dumps({"dependencies": {"react": "18"}}))
    write(root, "package-lock.json", json.dumps({"packages": {"node_modules/react": {}}}))
    write(
        root,
        "tsconfig.base.json",
        '{\n  // comments and trailing commas are fine\n  "compilerOptions": {\n'
        '    "paths": { "@app/*": ["src/app/*"], "utils": ["src/utils/index.ts"], },\n  },\n}\n',
    )
    write(
        root,
        "tsconfig.json",
        '{"extends": "./tsconfig.base.json", "compilerOptions": '
        '{"baseUrl": "src", "paths": {"~/*": ["./*"]}}}',
    )
    write(root, "src/components/Button.tsx", "export const B = 1;\n")
    write(root, "src/helpers.ts", "export const h = 1;\n")
    res = _run(
        root,
        ImportsLockfileOracle(),
        "src/page.tsx",
        "import React from 'react';\nimport { x } from '@app/thing/deep';\n"
        "import u from 'utils';\nimport t from '~/lib/t';\n"
        "import { B } from 'components/Button';\nimport { h } from 'helpers';\n"
        "import ghost from 'ghost-pkg';\nimport deep from 'components/nope';\n",
    )
    for spec in ("react", "@app/thing/deep", "utils", "components/Button", "helpers"):
        assert res[spec].level is Level.ACCEPT, (spec, res[spec].reason)
    assert "~/lib/t" not in res  # '~/' is a local alias prefix: never a claim
    assert "tsconfig" in res["@app/thing/deep"].reason
    assert res["ghost-pkg"].level is Level.REJECT
    # 'components/nope' resolves through baseUrl (the directory exists) -> accept
    assert res["components/nope"].level is Level.ACCEPT


def test_bare_bundler_alias_matching_a_repo_dir_reviews(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "package.json", json.dumps({"dependencies": {"react": "18"}}))
    write(root, "package-lock.json", json.dumps({"packages": {"node_modules/react": {}}}))
    write(root, "src/components/x.ts", "")
    write(root, "lib/util.ts", "")
    res = _run(
        root,
        ImportsLockfileOracle(),
        "src/a.ts",
        "import x from 'components/x';\nimport u from 'lib/util';\nimport g from 'ghost';\n",
    )
    assert res["components/x"].level is Level.REVIEW and "alias" in res["components/x"].reason
    assert res["lib/util"].level is Level.REVIEW
    assert res["ghost"].level is Level.REJECT


# --- imports_lockfile: Python layouts ---------------------------------------------------------


def test_packaging_declared_roots_are_local(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "uv.lock", '[[package]]\nname = "requests"\nversion = "2.32.3"\n')
    write(
        root,
        "pyproject.toml",
        '[project]\nname = "thing"\ndependencies = ["requests"]\n'
        '[tool.setuptools.package-dir]\n"" = "python"\n'
        '[tool.poetry]\nname = "thing"\npackages = [{include = "svc", from = "services"}]\n'
        '[tool.pytest.ini_options]\npythonpath = ["tests/helpers"]\n',
    )
    write(root, "python/mypkg/__init__.py", "")
    write(root, "services/svc/__init__.py", "")
    write(root, "tests/helpers/fixtures_util.py", "")
    write(root, "apps/blog/__init__.py", "")
    write(root, "apps/blog/models.py", "")
    res = _run(
        root,
        ImportsLockfileOracle(),
        "python/mypkg/m.py",
        "import requests\nimport mypkg\nfrom svc import api\nimport fixtures_util\n"
        "from blog.models import Post\nimport ghostpkg\n",
    )
    for name in ("requests", "mypkg", "svc", "fixtures_util"):
        assert res[name].level is Level.ACCEPT, (name, res[name].reason)
    nested = res["blog.models"]
    assert nested.level is Level.REVIEW and "sys.path" in nested.reason
    assert res["ghostpkg"].level is Level.REJECT


def test_setup_cfg_package_dir_root(tmp_path):
    root = str(tmp_path / "repo")
    cfg = "[options]\npackage_dir =\n    = source\ninstall_requires =\n    six\n"
    write(root, "setup.cfg", cfg)
    write(root, "requirements.txt", "six==1.16.0\n")
    write(root, "source/core/__init__.py", "")
    res = _run(root, ImportsLockfileOracle(), "source/core/a.py", "import core\nimport six\n")
    assert res["core"].level is Level.ACCEPT and res["six"].level is Level.ACCEPT


# --- multi-target check -----------------------------------------------------------------------


def test_multi_target_check_cli_mcp_parity(tmp_path, capsys):
    root = str(tmp_path / "repo")
    write(root, ".env.example", "A=\n")
    write(root, "weftgate.toml", '[weftgate]\noracles = ["env_vars"]\n')
    a = write(root, "a.py", "import os\nx = os.environ['A']\n")
    b = write(root, "sub/b.py", "import os\ny = os.environ['B']\n")
    store = str(tmp_path / "i.sqlite")
    assert cli.main(["--repo", root, "--store", store, "--format", "json", "check", a, b]) == 1
    via_cli = json.loads(capsys.readouterr().out)
    assert via_cli["stats"]["files"] == ["a.py", "sub/b.py"]
    via_mcp = mcp_server.call_tool(
        "check_change", {"repo": root, "paths": ["a.py", "sub"]}, store_path=store
    )
    assert via_cli == via_mcp


# --- lockfile vs manifest -------------------------------------------------------------------------


def test_manifest_only_absence_reviews_lockfile_absence_rejects(tmp_path):
    root = str(tmp_path / "repo")
    # pyproject only: direct dependencies, no resolved tree. Most declared names are
    # deliberately not installed here, so the environment does not match the project.
    write(
        root,
        "pyproject.toml",
        '[project]\ndependencies = ["fastapi", "requests", '
        '"zz-notinstalled-one", "zz-notinstalled-two", '
        '"zz-notinstalled-three", "zz-notinstalled-four"]\n',
    )
    res = _run(root, ImportsLockfileOracle(), "m.py", "import requestz\nimport zz_transitive\n")
    soft = res["requestz"]
    assert soft.level is Level.REVIEW and "did you mean requests" in soft.reason
    assert soft.suggestions[0] == "requests"
    trans = res["zz_transitive"]
    assert trans.level is Level.REVIEW and "transitive" in trans.reason
    # A lockfile enumerates the tree: absence is proven.
    write(
        root,
        "uv.lock",
        '[[package]]\nname = "fastapi"\n[[package]]\nname = "requests"\n'
        '[[package]]\nname = "zz-transitive"\n',
    )
    res = _run(root, ImportsLockfileOracle(), "m.py", "import requestz\nimport zz_transitive\n")
    assert res["requestz"].level is Level.REJECT and "uv.lock" in res["requestz"].reason
    assert res["zz_transitive"].level is Level.ACCEPT
    # Unpinned requirements are a manifest; fully pinned ones count as a lockfile.
    root2 = str(tmp_path / "two")
    write(root2, "requirements.txt", "fastapi\nrequests>=2\n")
    assert (
        _run(root2, ImportsLockfileOracle(), "m.py", "import ghost\n")["ghost"].level
        is Level.REVIEW
    )
    write(root2, "requirements.txt", "fastapi==0.115.0\nrequests==2.32.3\n")
    assert (
        _run(root2, ImportsLockfileOracle(), "m.py", "import ghost\n")["ghost"].level
        is Level.REJECT
    )


def test_manifest_only_reviews_even_when_environment_matches_project(tmp_path):
    # Installed tools do not prove that all transitive dependencies are installed.
    root = str(tmp_path / "repo")
    write(root, "pyproject.toml", '[project]\ndependencies = ["pytest", "ruff", "mypy", "build"]\n')
    res = _run(root, ImportsLockfileOracle(), "m.py", "import pytest\nimport ghostpkg_zz\n")
    assert res["pytest"].level is Level.ACCEPT
    assert res["ghostpkg_zz"].level is Level.REVIEW
    assert "transitive" in res["ghostpkg_zz"].reason


def test_node_manifest_only_and_framework_aliases(tmp_path):
    root = str(tmp_path / "repo")
    write(
        root, "package.json", json.dumps({"dependencies": {"@docusaurus/core": "3", "react": "18"}})
    )
    res = _run(
        root,
        ImportsLockfileOracle(),
        "src/pages/index.js",
        "import Layout from '@theme/Layout';\nimport x from '@site/src/x';\n"
        "import Link from '@docusaurus/Link';\nimport g from 'ghost-pkg';\n"
        "import s from '@scope/nope';\n",
    )
    assert res["@theme/Layout"].level is Level.ACCEPT and "alias" in res["@theme/Layout"].reason
    assert res["@site/src/x"].level is Level.ACCEPT
    assert res["@docusaurus/Link"].level is Level.ACCEPT
    assert res["ghost-pkg"].level is Level.REVIEW and "transitive" in res["ghost-pkg"].reason
    assert res["@scope/nope"].level is Level.REVIEW
    write(
        root,
        "package-lock.json",
        json.dumps(
            {
                "packages": {
                    "node_modules/@docusaurus/core": {},
                    "node_modules/react": {},
                    "node_modules/@scope/real": {},
                }
            }
        ),
    )
    res = _run(
        root,
        ImportsLockfileOracle(),
        "src/pages/index.js",
        "import g from 'ghost-pkg';\nimport s from '@scope/nope';\n",
    )
    assert res["ghost-pkg"].level is Level.REJECT
    scoped = res["@scope/nope"]
    assert scoped.level is Level.REVIEW and "@scope/* packages" in scoped.reason


# --- nested project roots and parameter bindings (routes) -----------------------------------------


def test_nested_project_root_resolves_cross_module_handlers(tmp_path):
    from weftgate.oracles.routes_fastapi import RoutesFastAPIOracle

    root = str(tmp_path / "repo")
    write(root, "backend/pyproject.toml", '[project]\ndependencies = ["fastapi"]\n')
    write(root, "backend/app/__init__.py", "")
    write(root, "backend/app/api/__init__.py", "")
    write(root, "backend/app/api/routes/__init__.py", "")
    write(
        root,
        "backend/app/api/routes/login.py",
        "from fastapi import APIRouter\nrouter = APIRouter()\n",
    )
    write(
        root,
        "backend/app/api/main.py",
        "from fastapi import APIRouter\nfrom app.api.routes import login\n"
        "from .routes import login as login2\n"
        "api_router = APIRouter()\napi_router.include_router(login.router)\n"
        "api_router.include_router(login2.router)\napi_router.include_router(login.nope)\n",
    )
    write(root, "backend/tests/__init__.py", "")
    write(root, "backend/tests/utils.py", "")
    ctx = _ctx(root, RoutesFastAPIOracle())
    res = _run(
        root,
        RoutesFastAPIOracle(),
        "backend/app/api/main.py",
        Path(os.path.join(root, "backend/app/api/main.py")).read_text(encoding="utf-8"),
        ctx=ctx,
    )
    assert res["login.router"].level is Level.ACCEPT, res["login.router"].reason
    assert res["login2.router"].level is Level.ACCEPT, res["login2.router"].reason
    assert res["login.nope"].level is Level.REJECT
    # A route decorator on a fixture parameter is a binding, not a missing router.
    res = _run(
        root,
        RoutesFastAPIOracle(),
        "backend/tests/test_x.py",
        "from fastapi import FastAPI\n\n\nasync def test_it(app: FastAPI):\n"
        "    @app.get('/x')\n    def route_for_test():\n        pass\n\n"
        "    for rt in [app]:\n        @rt.get('/y')\n        def y():\n            pass\n",
        ctx=ctx,
    )
    assert res["GET /x"].level is Level.ACCEPT and res["GET /y"].level is Level.ACCEPT
    ctx.store.close()
    # The nested root also makes `tests` a local import for the imports oracle.
    write(root, "backend/uv.lock", '[[package]]\nname = "fastapi"\n')
    res = _run(
        root,
        ImportsLockfileOracle(),
        "backend/tests/test_y.py",
        "from tests.utils import helper\nfrom app.api.main import api_router\n"
        "import fastapi\nimport ghostpkg\n",
    )
    assert res["tests.utils"].level is Level.ACCEPT and res["app.api.main"].level is Level.ACCEPT
    assert res["fastapi"].level is Level.ACCEPT and res["ghostpkg"].level is Level.REJECT


def test_harness_handles_multi_line_calls_and_node_candidates(tmp_path):
    from weftgate.eval import mutate

    root = str(tmp_path / "repo")
    write(root, "requirements.txt", "fastapi==0.115.0\n")
    write(root, "app/__init__.py", "")
    write(root, "app/users.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")
    write(
        root,
        "app/main.py",
        "from fastapi import FastAPI\nfrom app.users import router\n"
        "app = FastAPI()\napp.include_router(\n    router,\n"
        "    prefix='/api',\n)\n",
    )
    write(root, "package.json", json.dumps({"dependencies": {"express": "4", "lodash": "4"}}))
    write(
        root,
        "package-lock.json",
        json.dumps({"packages": {"node_modules/express": {}, "node_modules/lodash": {}}}),
    )
    write(root, "server.js", "const express = require('express');\nconst _ = require('lodash');\n")
    report = mutate.run(root, seed=5)
    by_oracle = report.per_oracle
    routes, imports = by_oracle["routes_fastapi"], by_oracle["imports_lockfile"]
    assert routes["total"] == 1 and routes["misses"] == 0
    assert imports["total"] >= 3 and imports["misses"] == 0
    assert any(m["file"] == "server.js" for m in report.mutations)


def test_optional_groups_do_not_establish_dependency_completeness(tmp_path):
    # Neither mandatory nor optional installed dependencies establish a complete tree.
    root = str(tmp_path / "repo")
    write(
        root,
        "pyproject.toml",
        '[project]\ndependencies = ["pytest", "ruff", "mypy"]\n'
        '[project.optional-dependencies]\nextra = ["zz-not-installed-a", "zz-not-installed-b"]\n'
        '[dependency-groups]\ndev = ["zz-not-installed-c", "zz-not-installed-d", '
        '"zz-not-installed-e"]\n'
        '[tool.hatch.envs.default]\ndependencies = ["zz-not-installed-f"]\n',
    )
    # A nested example app with its own (unmet) requirements must not dilute the root.
    write(root, "examples/demo/requirements.txt", "zz-not-installed-g\nzz-not-installed-h\n")
    res = _run(root, ImportsLockfileOracle(), "pkg/m.py", "import ghostpkg_zz\nimport pytest\n")
    assert res["pytest"].level is Level.ACCEPT
    assert res["ghostpkg_zz"].level is Level.REVIEW, res["ghostpkg_zz"].reason
    # Inside the example app the nearest manifest is the unmet one: not proven there.
    res = _run(root, ImportsLockfileOracle(), "examples/demo/app.py", "import ghostpkg_zz\n")
    assert res["ghostpkg_zz"].level is Level.REVIEW


def test_optional_import_reviews_with_a_suggestion(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "uv.lock", '[[package]]\nname = "httpx-oauth"\n')
    res = _run(
        root,
        ImportsLockfileOracle(),
        "m.py",
        "try:\n    from htttpx_oauth.oauth2 import X\nexcept ImportError:\n    X = None\n",
    )
    f = res["htttpx_oauth.oauth2"]
    assert f.level is Level.REVIEW and "optional" in f.reason
    assert f.suggestions == ("httpx-oauth",)


def test_documentation_snippets_are_soft(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "uv.lock", '[[package]]\nname = "fastapi"\n')
    write(root, ".env.example", "A=\n")
    code = "import os\nimport ghostpkg\nx = os.environ['GHOST']\n"
    res = _run(root, ImportsLockfileOracle(), "docs/src/snippet.py", code)
    assert res["ghostpkg"].level is Level.REVIEW and res["ghostpkg"].claim.attrs["docs"] is True
    res = _run(root, EnvVarOracle(), "docs/src/snippet.py", code)
    assert res["GHOST"].level is Level.REVIEW
    res = _run(root, ImportsLockfileOracle(), "src/real.py", code)
    assert res["ghostpkg"].level is Level.REJECT
