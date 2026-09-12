"""The three required tests for every oracle (true positive, true negative, soft),
plus the reference oracle's wider behaviour: sources, defaults, ambient names,
incremental sync, and the unverifiable path."""

import os

from tests.conftest import write
from weft.change import Change
from weft.config import Config
from weft.oracle import Context
from weft.oracles.env_vars import EnvVarOracle
from weft.store import Store
from weft.types import Level


def _ctx(root, config=None):
    store = Store(root, path=os.path.join(os.path.dirname(root), "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=config or Config())
    EnvVarOracle().build(ctx)
    ctx.store.finish_sync(None)  # what the gate does after a successful build
    return ctx


def _check(root, code, config=None, ctx=None, name="m.py"):
    ctx = ctx or _ctx(root, config)
    oracle = EnvVarOracle()
    p = write(root, name, code)
    change = Change.from_file(p)
    return {f.claim.subject: f for f in (oracle.check(c, ctx) for c in oracle.extract(change, ctx))}


def _repo(tmp_path, dotenv="DATABASE_URL=\n"):
    root = str(tmp_path / "repo")
    os.makedirs(root, exist_ok=True)
    write(root, ".env.example", dotenv)
    return root


# --- the three required tests --------------------------------------------------------------


def test_true_negative_declared_var_accepts(tmp_path):
    root = _repo(tmp_path)
    res = _check(root, "import os\nx = os.getenv('DATABASE_URL')\n")
    assert res["DATABASE_URL"].level is Level.ACCEPT
    assert ".env.example" in res["DATABASE_URL"].reason


def test_true_positive_undeclared_var_rejects(tmp_path):
    root = _repo(tmp_path)
    res = _check(root, "import os\nx = os.getenv('STRIPE_SECRET')\n")
    f = res["STRIPE_SECRET"]
    assert f.level is Level.REJECT
    assert f.claim.hard and f.oracle == "env_vars"
    assert ".env.example" in f.reason


def test_soft_dynamic_key_reviews_not_rejects(tmp_path):
    root = _repo(tmp_path)
    res = _check(root, "import os\nk = 'X'\nx = os.environ[k]\ny = os.getenv(f'PREFIX_{k}')\n")
    assert res["<dynamic>"].level is Level.REVIEW
    assert not res["<dynamic>"].claim.hard


# --- wider behaviour --------------------------------------------------------------------------


def test_suggestion_names_the_closest_declared_var(tmp_path):
    root = _repo(tmp_path, "DATABASE_URL=\nSTRIPE_SECRET_KEY=\nAPI_TOKEN=\n")
    res = _check(root, "import os\nx = os.environ['DATABSE_URL']\ny = os.getenv('STRIPE_SECRET')\n")
    assert res["DATABSE_URL"].suggestions[0] == "DATABASE_URL"
    assert res["STRIPE_SECRET"].suggestions[0] == "STRIPE_SECRET_KEY"


def test_unverifiable_when_index_absent(tmp_path):
    root = _repo(tmp_path)
    store = Store(root, path=str(tmp_path / "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=Config())  # no build()
    oracle = EnvVarOracle()
    change = Change.from_file(write(root, "m.py", "import os\nx = os.getenv('NOPE')\n"))
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    assert findings[0].level is Level.UNVERIFIABLE


def test_inline_default_and_ambient_accept(tmp_path):
    root = _repo(tmp_path)
    res = _check(
        root,
        "import os\n"
        "a = os.getenv('LOG_LEVEL', 'info')\n"
        "b = os.environ.get('WORKERS', 4)\n"
        "c = os.environ.get('NO_DEFAULT', None)\n"
        "d = os.environ['PATH']\n"
        "e = os.getenv('GITHUB_SHA')\n",
    )
    assert res["LOG_LEVEL"].level is Level.ACCEPT and "default" in res["LOG_LEVEL"].reason
    assert res["WORKERS"].level is Level.ACCEPT
    assert res["NO_DEFAULT"].level is Level.REJECT  # a None default is no default
    assert res["PATH"].level is Level.ACCEPT
    assert res["GITHUB_SHA"].level is Level.ACCEPT


def test_multi_language_reads(tmp_path):
    root = _repo(tmp_path, "DATABASE_URL=\nAPI_KEY=\n")
    ctx = _ctx(root)
    js = _check(
        root,
        "const a = process.env.DATABASE_URL;\nconst b = process.env['MISSING_ONE'];\n"
        "const c = process.env.PORT || 3000;\nconst d = process.env.OPT ?? 'x';\n"
        "// process.env.IN_COMMENT\nconst e = process.env[name];\n",
        ctx=ctx,
        name="app.js",
    )
    assert js["DATABASE_URL"].level is Level.ACCEPT
    assert js["MISSING_ONE"].level is Level.REJECT
    assert js["PORT"].level is Level.ACCEPT and js["OPT"].level is Level.ACCEPT
    assert "IN_COMMENT" not in js and js["<dynamic>"].level is Level.REVIEW
    rb = _check(root, "x = ENV['API_KEY']\ny = ENV.fetch('NOPE_RB')\n", ctx=ctx, name="a.rb")
    assert rb["API_KEY"].level is Level.ACCEPT and rb["NOPE_RB"].level is Level.REJECT
    go = _check(root, 'v := os.Getenv("NOPE_GO")\n', ctx=ctx, name="a.go")
    assert go["NOPE_GO"].level is Level.REJECT
    rs = _check(root, 'let v = std::env::var("API_KEY");\n', ctx=ctx, name="a.rs")
    assert rs["API_KEY"].level is Level.ACCEPT
    ctx.store.close()


def test_declaration_sources_in_code_and_containers(tmp_path):
    root = _repo(tmp_path, "DATABASE_URL=\n")
    write(
        root,
        "settings.py",
        "import os\nfrom pydantic_settings import BaseSettings\n\n"
        "os.environ.setdefault('SET_DEFAULT', '1')\n"
        "os.environ['ASSIGNED'] = 'x'\n"
        "timeout = os.getenv('TIMEOUT', '30')\n\n"
        "class Settings(BaseSettings):\n    redis_url: str = 'redis://'\n    debug: bool = False\n"
        "    model_config = {'env_prefix': 'APP_'}\n",
    )
    write(
        root,
        "docker-compose.yml",
        "services:\n  web:\n    environment:\n      - COMPOSE_A=1\n"
        "      COMPOSE_B: 2\n    ports:\n      - '80:80'\n",
    )
    write(root, "Dockerfile", "FROM python:3\nENV DOCK_A=1 DOCK_B=2\nARG DOCK_C\n")
    write(root, "web.js", "process.env.JS_DEFAULT = process.env.JS_DEFAULT || 'x';\n")
    res = _check(
        root,
        "import os\n"
        + "\n".join(
            f"v{i} = os.environ['{n}']"
            for i, n in enumerate(
                [
                    "SET_DEFAULT",
                    "ASSIGNED",
                    "TIMEOUT",
                    "APP_REDIS_URL",
                    "APP_DEBUG",
                    "COMPOSE_A",
                    "COMPOSE_B",
                    "DOCK_A",
                    "DOCK_B",
                    "DOCK_C",
                    "JS_DEFAULT",
                    "REDIS_URL",
                ]
            )
        )
        + "\n",
    )
    for name in (
        "SET_DEFAULT",
        "ASSIGNED",
        "TIMEOUT",
        "APP_REDIS_URL",
        "APP_DEBUG",
        "COMPOSE_A",
        "COMPOSE_B",
        "DOCK_A",
        "DOCK_B",
        "DOCK_C",
        "JS_DEFAULT",
    ):
        assert res[name].level is Level.ACCEPT, name
    assert res["REDIS_URL"].level is Level.REJECT
    assert "APP_REDIS_URL" in res["REDIS_URL"].suggestions


def test_env_declared_in_treats_reads_as_the_contract(tmp_path):
    root = _repo(tmp_path, "DATABASE_URL=\n")
    write(root, "config/settings.py", "import os\nSECRET = os.environ['SECRET_KEY']\n")
    write(root, ".env", "LOCAL_ONLY=1\n")
    cfg = Config(env_declared_in=["config/settings.py", ".env"])
    res = _check(
        root, "import os\nx = os.environ['SECRET_KEY']\ny = os.environ['LOCAL_ONLY']\n", config=cfg
    )
    assert res["SECRET_KEY"].level is Level.ACCEPT
    assert res["LOCAL_ONLY"].level is Level.ACCEPT
    # Without the config, a read in an ordinary module declares nothing.
    res = _check(root, "import os\nx = os.environ['SECRET_KEY']\n")
    assert res["SECRET_KEY"].level is Level.REJECT


def test_incremental_sync_tracks_declaration_changes(tmp_path):
    root = _repo(tmp_path, "DATABASE_URL=\n")
    ctx = _ctx(root)
    oracle = EnvVarOracle()
    code = "import os\nx = os.getenv('NEW_VAR')\n"
    assert _check(root, code, ctx=ctx)["NEW_VAR"].level is Level.REJECT
    write(root, ".env.example", "DATABASE_URL=\nNEW_VAR=\n")
    oracle.sync(ctx, None)
    ctx.store.finish_sync(None)
    assert _check(root, code, ctx=ctx)["NEW_VAR"].level is Level.ACCEPT
    write(root, ".env.example", "DATABASE_URL=\n")  # NEW_VAR removed, a source remains
    oracle.sync(ctx, None)
    ctx.store.finish_sync(None)
    assert _check(root, code, ctx=ctx)["NEW_VAR"].level is Level.REJECT
    os.remove(os.path.join(root, ".env.example"))  # no source at all: review, not reject
    oracle.sync(ctx, None)
    ctx.store.finish_sync(None)
    assert _check(root, code, ctx=ctx)["NEW_VAR"].level is Level.REVIEW
    ctx.store.close()


def test_deterministic_order_and_no_duplicates_per_line(tmp_path):
    root = _repo(tmp_path, "A=\nB=\n")
    ctx = _ctx(root)
    oracle = EnvVarOracle()
    code = "import os\nx = os.getenv('A') or os.getenv('A')\ny = os.environ['B']\n"
    change = Change.from_file(write(root, "m.py", code))
    claims = oracle.extract(change, ctx)
    assert [(c.subject, c.location.line) for c in claims] == [("A", 2), ("B", 3)]
    assert oracle.extract(change, ctx) == claims
    ctx.store.close()
