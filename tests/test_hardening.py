"""False-reject hardening: the cases a real repo hits that a fixture does not."""

import json
import os

from tests.conftest import write
from weft import cli, mcp_server
from weft.change import Change
from weft.config import Config
from weft.oracle import Context
from weft.oracles.env_vars import EnvVarOracle, mask_comments
from weft.oracles.imports_lockfile import ImportsLockfileOracle
from weft.store import Store
from weft.types import Level


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
    text = ('const a = process.env.REAL; // process.env.IN_LINE_COMMENT\n'
            '/* process.env.IN_BLOCK\n   still */ const b = `${process.env.IN_TEMPLATE}`;\n'
            'const url = "http://x/y"; const c = process.env.AFTER_URL;\n'
            "const s = 'it\\'s // not a comment'; const d = process.env.AFTER_ESC;\n")
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
    res = _run(root, EnvVarOracle(), "app.ts",
               "const a = process.env.REAL; // process.env.GHOST_ONE\n"
               "/* process.env.GHOST_TWO */\nconst b = `${process.env.IN_TEMPLATE}`;\n")
    assert set(res) == {"REAL", "IN_TEMPLATE"}
    assert all(f.level is Level.ACCEPT for f in res.values())


# --- imports_lockfile: TypeScript --------------------------------------------------------------


def test_tsconfig_paths_and_base_url_resolve(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "package.json", json.dumps({"dependencies": {"react": "18"}}))
    write(root, "tsconfig.base.json",
          '{\n  // comments and trailing commas are fine\n  "compilerOptions": {\n'
          '    "paths": { "@app/*": ["src/app/*"], "utils": ["src/utils/index.ts"], },\n  },\n}\n')
    write(root, "tsconfig.json", '{"extends": "./tsconfig.base.json", "compilerOptions": '
                                 '{"baseUrl": "src", "paths": {"~/*": ["./*"]}}}')
    write(root, "src/components/Button.tsx", "export const B = 1;\n")
    write(root, "src/helpers.ts", "export const h = 1;\n")
    res = _run(root, ImportsLockfileOracle(), "src/page.tsx",
               "import React from 'react';\nimport { x } from '@app/thing/deep';\n"
               "import u from 'utils';\nimport t from '~/lib/t';\n"
               "import { B } from 'components/Button';\nimport { h } from 'helpers';\n"
               "import ghost from 'ghost-pkg';\nimport deep from 'components/nope';\n")
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
    write(root, "src/components/x.ts", "")
    write(root, "lib/util.ts", "")
    res = _run(root, ImportsLockfileOracle(), "src/a.ts",
               "import x from 'components/x';\nimport u from 'lib/util';\nimport g from 'ghost';\n")
    assert res["components/x"].level is Level.REVIEW and "alias" in res["components/x"].reason
    assert res["lib/util"].level is Level.REVIEW
    assert res["ghost"].level is Level.REJECT


# --- imports_lockfile: Python layouts ---------------------------------------------------------


def test_packaging_declared_roots_are_local(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "pyproject.toml",
          '[project]\nname = "thing"\ndependencies = ["requests"]\n'
          '[tool.setuptools.package-dir]\n"" = "python"\n'
          '[tool.poetry]\nname = "thing"\npackages = [{include = "svc", from = "services"}]\n'
          '[tool.pytest.ini_options]\npythonpath = ["tests/helpers"]\n')
    write(root, "python/mypkg/__init__.py", "")
    write(root, "services/svc/__init__.py", "")
    write(root, "tests/helpers/fixtures_util.py", "")
    write(root, "apps/blog/__init__.py", "")
    write(root, "apps/blog/models.py", "")
    res = _run(root, ImportsLockfileOracle(), "python/mypkg/m.py",
               "import requests\nimport mypkg\nfrom svc import api\nimport fixtures_util\n"
               "from blog.models import Post\nimport ghostpkg\n")
    for name in ("requests", "mypkg", "svc", "fixtures_util"):
        assert res[name].level is Level.ACCEPT, (name, res[name].reason)
    nested = res["blog.models"]
    assert nested.level is Level.REVIEW and "sys.path" in nested.reason
    assert res["ghostpkg"].level is Level.REJECT


def test_setup_cfg_package_dir_root(tmp_path):
    root = str(tmp_path / "repo")
    cfg = "[options]\npackage_dir =\n    = source\ninstall_requires =\n    six\n"
    write(root, "setup.cfg", cfg)
    write(root, "source/core/__init__.py", "")
    res = _run(root, ImportsLockfileOracle(), "source/core/a.py", "import core\nimport six\n")
    assert res["core"].level is Level.ACCEPT and res["six"].level is Level.ACCEPT


# --- multi-target check -----------------------------------------------------------------------


def test_multi_target_check_cli_mcp_parity(tmp_path, capsys):
    root = str(tmp_path / "repo")
    write(root, ".env.example", "A=\n")
    write(root, "weft.toml", '[weft]\noracles = ["env_vars"]\n')
    a = write(root, "a.py", "import os\nx = os.environ['A']\n")
    b = write(root, "sub/b.py", "import os\ny = os.environ['B']\n")
    store = str(tmp_path / "i.sqlite")
    assert cli.main(["--repo", root, "--store", store, "--format", "json", "check", a, b]) == 1
    via_cli = json.loads(capsys.readouterr().out)
    assert via_cli["stats"]["files"] == ["a.py", "sub/b.py"]
    via_mcp = mcp_server.call_tool("check_change", {"repo": root, "paths": ["a.py", "sub"]},
                                   store_path=store)
    assert via_cli == via_mcp
