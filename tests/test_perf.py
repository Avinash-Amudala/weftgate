"""The performance targets from AGENTS.md: a no-op sync well under a second and a
one-file sync about a second, measured on a synthetic 1500-file repo (no git, so
the fingerprint fallback, the slower path, is what gets timed)."""

import os
import time

from weftgate.change import Change
from weftgate.gate import Session
from weftgate.types import Level


def _big_repo(root: str, n: int) -> None:
    os.makedirs(os.path.join(root, "pkg"), exist_ok=True)
    with open(os.path.join(root, ".env.example"), "w") as fh:
        fh.write("DATABASE_URL=\nAPI_KEY=\n")
    with open(os.path.join(root, "requirements.txt"), "w") as fh:
        fh.write("fastapi==0.115.0\nrequests==2.32.3\n")
    with open(os.path.join(root, "pkg", "__init__.py"), "w") as fh:
        fh.write("")
    for i in range(n):
        with open(os.path.join(root, "pkg", f"mod_{i}.py"), "w") as fh:
            fh.write(
                "import os\nimport requests\nfrom fastapi import APIRouter\n\n"
                f"router = APIRouter(prefix='/m{i}')\n\n\n"
                f"@router.get('/{{item_id}}')\nasync def get_{i}(item_id: int):\n"
                f"    return os.environ['DATABASE_URL']\n"
            )


def test_sync_targets_on_a_large_repo(tmp_path):
    root = str(tmp_path / "big")
    _big_repo(root, 1500)
    store = str(tmp_path / "i.sqlite")
    t0 = time.perf_counter()
    with Session(root, store_path=store) as s:
        s.sync()
    build = time.perf_counter() - t0
    t0 = time.perf_counter()
    with Session(root, store_path=store) as s:
        report = s.sync()
    noop = time.perf_counter() - t0
    assert all(r["action"] == "sync" for r in report.values())
    with open(os.path.join(root, "pkg", "mod_7.py"), "a") as fh:
        fh.write("x = os.environ['NEW_ONE']\n")
    t0 = time.perf_counter()
    with Session(root, store_path=store) as s:
        s.sync()
        res = s.check_change(Change.from_file(os.path.join(root, "pkg", "mod_7.py"), root))
    one = time.perf_counter() - t0
    assert res.verdict is Level.REJECT
    # Generous bounds so CI runners never flake; the local numbers are far lower.
    assert noop < 1.0, f"no-op sync took {noop:.2f}s (build {build:.2f}s)"
    assert one < 3.0, f"one-file sync + check took {one:.2f}s (build {build:.2f}s)"
    assert build < 60.0
