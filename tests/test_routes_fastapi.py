"""routes_fastapi: the three required tests plus include_router edges, prefix
resolution, claim mode, star imports, and the unverifiable paths."""

import os

from tests.conftest import write
from weft.change import Change
from weft.config import Config
from weft.gate import claims_from_json
from weft.oracle import Context
from weft.oracles.routes_fastapi import RoutesFastAPIOracle, describe_routes
from weft.store import Store
from weft.types import Claim, Level, Location

MAIN = """\
from fastapi import FastAPI
from app.users import router as users_router
from app import orders
from app.handlers import health, metrics

app = FastAPI()
app.include_router(users_router, prefix="/api")
app.include_router(orders.router, prefix="/api")


@app.get("/")
async def index():
    return {"ok": True}


app.add_api_route("/health", health)
app.add_api_route("/metrics", metrics, methods=["GET", "HEAD"])
"""

USERS = """\
from fastapi import APIRouter

router = APIRouter(prefix="/users")


@router.get("/{user_id}")
async def get_user(user_id: int):
    return {}


@router.post("")
async def create_user():
    return {}
"""

ORDERS = """\
from fastapi import APIRouter

router = APIRouter()


@router.post("/orders")
def create_order():
    return {}


def helper():
    pass
"""

HANDLERS = "async def health():\n    return 'ok'\n\n\nasync def metrics():\n    return {}\n"


def _repo(tmp_path):
    root = str(tmp_path / "repo")
    write(root, "app/__init__.py", "")
    write(root, "app/main.py", MAIN)
    write(root, "app/users.py", USERS)
    write(root, "app/orders.py", ORDERS)
    write(root, "app/handlers.py", HANDLERS)
    return root


def _ctx(root, config=None):
    store = Store(root, path=os.path.join(os.path.dirname(root), "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=config or Config())
    RoutesFastAPIOracle().build(ctx)
    ctx.store.finish_sync(None)
    return ctx


def _check(root, code, name="app/extra.py", ctx=None):
    ctx = ctx or _ctx(root)
    oracle = RoutesFastAPIOracle()
    change = Change.from_file(write(root, name, code), repo_root=root)
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    return {(f.claim.kind, f.claim.subject): f for f in findings}


# --- the three required tests -------------------------------------------------------------


def test_true_positive_dangling_handler_rejects(tmp_path):
    root = _repo(tmp_path)
    res = _check(
        root,
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        "def create_users():\n    pass\n\n"
        "app.add_api_route('/users', create_user, methods=['POST'])\n",
    )
    f = res[("route_handler", "POST /users")]
    assert f.level is Level.REJECT and f.claim.hard
    assert "create_user" in f.reason and f.suggestions == ("create_users",)


def test_true_negative_defined_handlers_accept(tmp_path):
    root = _repo(tmp_path)
    ctx = _ctx(root)
    res = _check(root, MAIN, name="app/main.py", ctx=ctx)
    assert res[("route_handler", "GET /")].level is Level.ACCEPT
    assert res[("route_handler", "GET /health")].level is Level.ACCEPT
    assert "app/handlers.py" in res[("route_handler", "GET /health")].reason
    assert res[("route_handler", "HEAD /metrics")].level is Level.ACCEPT
    assert res[("router_include", "users_router")].level is Level.ACCEPT
    assert res[("router_include", "orders.router")].level is Level.ACCEPT
    ctx.store.close()


def test_soft_dynamic_handler_reviews_not_rejects(tmp_path):
    root = _repo(tmp_path)
    res = _check(
        root,
        "from fastapi import FastAPI\nimport handlers\napp = FastAPI()\n"
        "name = 'x'\napp.add_api_route('/dyn', getattr(handlers, name))\n"
        "app.include_router(make_router())\n"
        "app.add_api_route('/lam', lambda: 1)\n",
    )
    f = res[("route_handler", "GET /dyn")]
    assert f.level is Level.REVIEW and not f.claim.hard
    assert res[("router_include", "<make_router()>")].level is Level.REVIEW
    assert res[("route_handler", "GET /lam")].level is Level.REVIEW


# --- wider behaviour -------------------------------------------------------------------------


def test_include_router_edges(tmp_path):
    root = _repo(tmp_path)
    ctx = _ctx(root)
    res = _check(
        root,
        "from fastapi import FastAPI\nfrom app import orders, users\nfrom app.users import nope\n"
        "import fastapi_users\nfrom app.orders import *\n"
        "app = FastAPI()\n"
        "app.include_router(orders.helper_router)\n"  # module exists, attribute does not
        "app.include_router(users.router)\n"
        "app.include_router(ghost_router)\n"  # never bound anywhere
        "app.include_router(fastapi_users.router)\n"  # outside the repo
        "app.include_router(nope)\n"  # imported name the module does not define
        "app.include_router(starry)\n",  # could come from the star import
        ctx=ctx,
    )
    bad = res[("router_include", "orders.helper_router")]
    assert bad.level is Level.REJECT and "app/orders.py defines no 'helper_router'" in bad.reason
    assert "router" in bad.suggestions
    assert res[("router_include", "users.router")].level is Level.ACCEPT
    assert res[("router_include", "ghost_router")].level is Level.REVIEW  # star import present
    assert res[("router_include", "fastapi_users.router")].level is Level.REVIEW
    assert res[("router_include", "nope")].level is Level.REJECT
    assert res[("router_include", "starry")].level is Level.REVIEW
    # Without the star import, an unbound name is a proven absence.
    res = _check(
        root,
        "from fastapi import FastAPI\napp = FastAPI()\napp.include_router(ghost_router)\n",
        ctx=ctx,
    )
    assert res[("router_include", "ghost_router")].level is Level.REJECT
    ctx.store.close()


def test_decorator_on_unbound_router_rejects(tmp_path):
    root = _repo(tmp_path)
    res = _check(
        root,
        "from fastapi import APIRouter\nrouter = APIRouter()\n\n"
        "@rooter.get('/x')\ndef x():\n    pass\n",
    )
    f = res[("route_handler", "GET /x")]
    assert f.level is Level.REJECT and f.suggestions == ("router",)


def test_claim_mode_route_table_with_prefixes(tmp_path):
    root = _repo(tmp_path)
    ctx = _ctx(root)
    oracle = RoutesFastAPIOracle()
    table = {(r["method"], r["path"]): r["handler"] for r in describe_routes(ctx)}
    assert table[("GET", "/api/users/{user_id}")] == "get_user"
    assert table[("POST", "/api/users")] == "create_user"
    assert table[("POST", "/api/orders")] == "create_order"
    assert table[("GET", "/")] == "index" and table[("HEAD", "/metrics")] == "metrics"

    def claim(subject, **attrs):
        return oracle.check(
            Claim("route_handler", subject, Location(""), attrs, source="assertion"), ctx
        )

    assert claim("POST /api/users").level is Level.ACCEPT
    assert claim("GET /api/users/{id}").level is Level.ACCEPT  # param names may differ
    assert claim("get /api/users/{id}/").level is Level.ACCEPT
    assert claim("POST /api/users", handler="app.users.create_user").level is Level.ACCEPT
    mismatch = claim("POST /api/users", handler="users.create")
    assert mismatch.level is Level.REJECT and "create_user" in mismatch.reason
    missing = claim("POST /api/user")
    assert missing.level is Level.REJECT and missing.suggestions[0] == "POST /api/users"
    assert claim("DELETE /api/users/{id}").level is Level.REJECT
    assert claim("ANY /health").level is Level.ACCEPT
    parsed = claims_from_json(
        [{"kind": "route", "method": "post", "path": "/api/orders", "handler": "create_order"}]
    )
    assert oracle.check(parsed[0], ctx).level is Level.ACCEPT
    ctx.store.close()


def test_claim_mode_unresolved_prefix_reviews(tmp_path):
    root = str(tmp_path / "repo")
    write(
        root,
        "main.py",
        "from fastapi import FastAPI\nfrom items import router\n"
        "PREFIX = '/v1'\napp = FastAPI()\n"
        "app.include_router(router, prefix=PREFIX)\n",
    )
    write(
        root,
        "items.py",
        "from fastapi import APIRouter\nrouter = APIRouter()\n\n"
        "@router.get('/items')\ndef items():\n    return []\n",
    )
    ctx = _ctx(root)
    oracle = RoutesFastAPIOracle()
    f = oracle.check(Claim("route_handler", "GET /v1/items", Location(""), source="assertion"), ctx)
    assert f.level is Level.REVIEW and "prefix" in f.reason
    ctx.store.close()


def test_unverifiable_paths(tmp_path):
    root = _repo(tmp_path)
    store = Store(root, path=str(tmp_path / "i.sqlite"))
    ctx = Context(repo_root=root, store=store, config=Config())
    oracle = RoutesFastAPIOracle()
    change = Change.from_file(os.path.join(root, "app/main.py"), repo_root=root)
    findings = [oracle.check(c, ctx) for c in oracle.extract(change, ctx)]
    assert findings and all(f.level is Level.UNVERIFIABLE for f in findings)
    plain = str(tmp_path / "plain")
    write(plain, "x.py", "print('no web framework here')\n")
    ctx2 = _ctx(plain)
    f = oracle.check(Claim("route_handler", "GET /x", Location(""), source="assertion"), ctx2)
    assert f.level is Level.UNVERIFIABLE and "no FastAPI" in f.reason
    plain_change = Change.from_file(os.path.join(plain, "x.py"), repo_root=plain)
    assert oracle.extract(plain_change, ctx2) == []
    store.close()
    ctx2.store.close()


def test_diff_fragment_uses_the_file_on_disk(tmp_path):
    root = _repo(tmp_path)
    ctx = _ctx(root)
    oracle = RoutesFastAPIOracle()
    write(root, "app/main.py", MAIN + "app.add_api_route('/late', helth)\n")
    diff = (
        "--- a/app/main.py\n+++ b/app/main.py\n@@ -17,0 +18 @@\n"
        "+app.add_api_route('/late', helth)\n"
    )
    change = Change.from_unified_diff(diff)
    res = {f.claim.subject: f for f in (oracle.check(c, ctx) for c in oracle.extract(change, ctx))}
    assert list(res) == ["GET /late"]
    assert res["GET /late"].level is Level.REJECT and res["GET /late"].suggestions[0] == "health"
    ctx.store.close()


def test_sync_tracks_handler_renames(tmp_path):
    root = _repo(tmp_path)
    ctx = _ctx(root)
    oracle = RoutesFastAPIOracle()
    main = Change.from_file(os.path.join(root, "app/main.py"), repo_root=root)

    def health():
        findings = [oracle.check(c, ctx) for c in oracle.extract(main, ctx)]
        return {f.claim.subject: f for f in findings}["GET /health"]

    assert health().level is Level.ACCEPT
    write(root, "app/handlers.py", HANDLERS.replace("def health", "def healthz"))
    oracle.sync(ctx, None)
    ctx.store.finish_sync(None)
    f = health()
    assert f.level is Level.REJECT and f.suggestions[0] == "healthz"
    ctx.store.close()
