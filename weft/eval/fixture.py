"""A tiny, realistic fixture repo: a FastAPI app with routers, env reads, and a
lockfile. Used by the self-test, the mutation harness (``--fixture``), and the
tests. Deterministic: the same files every time.

Numbers measured on this fixture are upper bounds (the oracles were tuned on
it); the field number is what ``weft audit`` reports on a user's own repo.
"""

from __future__ import annotations

import os

FILES: dict[str, str] = {
    ".env.example": "DATABASE_URL=postgres://localhost/app\nAPI_KEY=\nREDIS_URL=\nSMTP_HOST=\n",
    "requirements.txt": "fastapi==0.115.0\nuvicorn[standard]\nrequests>=2.31\nPyYAML>=6\n"
                        "sqlalchemy>=2\n",
    "weft.toml": '[weft]\noracles = ["env_vars", "imports_lockfile", "routes_fastapi"]\n'
                 'block_on = "reject"\n\n[weft.routes_fastapi]\napp = "app.main:app"\n',
    "app/__init__.py": "",
    "app/config.py": (
        "import os\n\nimport yaml\n\n"
        "DATABASE_URL = os.environ['DATABASE_URL']\n"
        "API_KEY = os.getenv('API_KEY')\n"
        "REDIS_URL = os.environ.get('REDIS_URL')\n"
        "LOG_LEVEL = os.getenv('LOG_LEVEL', 'info')\n\n\n"
        "def load(path):\n    with open(path) as fh:\n        return yaml.safe_load(fh)\n"
    ),
    "app/handlers.py": (
        "import requests\n\n\n"
        "async def health():\n    return {'ok': True}\n\n\n"
        "async def metrics():\n    return {'requests': requests.__version__}\n"
    ),
    "app/users.py": (
        "from fastapi import APIRouter\n\n"
        "router = APIRouter(prefix='/users')\n\n\n"
        "@router.get('/{user_id}')\nasync def get_user(user_id: int):\n    return {}\n\n\n"
        "@router.post('')\nasync def create_user():\n    return {}\n"
    ),
    "app/orders.py": (
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n\n"
        "@router.post('/orders')\nasync def create_order():\n    return {}\n\n\n"
        "@router.get('/orders/{order_id}')\nasync def get_order(order_id: int):\n    return {}\n"
    ),
    "app/main.py": (
        "from fastapi import FastAPI\n\n"
        "from app import orders\n"
        "from app.handlers import health, metrics\n"
        "from app.users import router as users_router\n\n"
        "app = FastAPI()\n"
        "app.include_router(users_router, prefix='/api')\n"
        "app.include_router(orders.router, prefix='/api')\n\n\n"
        "@app.get('/')\nasync def index():\n    return {'service': 'fixture'}\n\n\n"
        "app.add_api_route('/health', health)\n"
        "app.add_api_route('/metrics', metrics, methods=['GET', 'HEAD'])\n"
    ),
    "app/tasks.py": (
        "import os\n\nimport sqlalchemy\n\n"
        "SMTP_HOST = os.environ['SMTP_HOST']\n\n\n"
        "def engine():\n    return sqlalchemy.create_engine(os.environ['DATABASE_URL'])\n"
    ),
}

# The broken counterpart used by the self-test: one wire broken per oracle.
BROKEN: dict[str, str] = {
    "app/broken.py": (
        "import os\n\nimport requestz\n\n"
        "from app.handlers import health\n"
        "from app.main import app\n\n"
        "SECRET = os.environ['DATABSE_URL']\n\n"
        "app.add_api_route('/late', helth)\n"
    ),
}


def write_fixture(root: str, broken: bool = False) -> None:
    files = dict(FILES)
    if broken:
        files.update(BROKEN)
    for rel, text in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
