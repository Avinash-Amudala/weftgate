"""The gate: sync-before-check, verdicts, crash isolation, claim intake."""

import os

import pytest

from tests.conftest import git_commit_all, git_init, have_git, write
from tests.plugins.dummy_oracle import DummyOracle
from weft.change import Change
from weft.config import Config
from weft.gate import Session, blocks, check_change, claims_from_json, index, status, suggest
from weft.oracle import BaseOracle
from weft.types import Claim, Level, Location


def _repo(tmp_path):
    root = str(tmp_path / "repo")
    write(root, ".env.example", "DATABASE_URL=\nAPI_KEY=\n")
    write(root, "app.py", "import os\ndb = os.getenv('DATABASE_URL')\n")
    return root


def _session(root, **kw):
    cfg = kw.pop("config", Config(oracles=["env_vars"]))
    store_path = os.path.join(os.path.dirname(root), "i.sqlite")
    return Session(root, config=cfg, store_path=store_path, **kw)


def test_diff_mode_end_to_end(tmp_path):
    root = _repo(tmp_path)
    with _session(root) as s:
        bad = write(root, "bad.py", "import os\nk = os.environ['DATABSE_URL']\n")
        res = s.check_change(Change.from_file(bad))
        assert res.verdict is Level.REJECT and res.stats["blocking"] is True
        f = res.findings[0]
        assert f.claim.location.file == "bad.py" and f.suggestions == ("DATABASE_URL",)
        assert res.stats["files"] == ["bad.py"] and res.stats["mode"] == "diff"
        good = write(root, "good.py", "import os\nk = os.environ['API_KEY']\n")
        assert s.check_change(Change.from_file(good)).verdict is Level.ACCEPT
        # Same input, same output, in the same order.
        again = s.check_change(Change.from_file(bad))
        assert again.to_dict() == res.to_dict()


def test_index_is_built_once_then_synced(tmp_path):
    root = _repo(tmp_path)
    with _session(root) as s:
        report = s.sync()
        assert report["env_vars"]["action"] == "build" and report["env_vars"]["built"]
        report = s.sync()
        assert report["env_vars"]["action"] == "sync"
        assert s.sync(force_rebuild=True)["env_vars"]["action"] == "build"
        st = s.status()
        assert st["oracles"]["env_vars"]["built"] and st["oracles"]["env_vars"]["tables"] == {
            "decl": 2
        }
    # A bumped oracle version forces a rebuild on the next session.
    with _session(root) as s:
        s.store.set_meta("oracle:env_vars:version", "0")
        assert s.sync()["env_vars"]["action"] == "build"


def test_sync_sees_new_declarations(tmp_path):
    root = _repo(tmp_path)
    code = write(root, "n.py", "import os\nk = os.environ['NEW_ONE']\n")
    with _session(root) as s:
        assert s.check_change(Change.from_file(code)).verdict is Level.REJECT
    write(root, ".env.example", "DATABASE_URL=\nAPI_KEY=\nNEW_ONE=\n")
    with _session(root) as s:
        assert s.check_change(Change.from_file(code)).verdict is Level.ACCEPT


@pytest.mark.skipif(not have_git(), reason="git not installed")
def test_sync_in_git_repo_records_commit(tmp_path):
    root = _repo(tmp_path)
    git_init(root)
    c1 = git_commit_all(root)
    with _session(root) as s:
        s.sync()
        assert s.store.get_meta("build_commit") == c1
        assert s.store.oracle_commit("env_vars") == c1
    write(root, ".env.example", "DATABASE_URL=\nAPI_KEY=\nLATER=\n")
    code = write(root, "n.py", "import os\nk = os.environ['LATER']\n")
    with _session(root) as s:
        assert s.check_change(Change.from_file(code)).verdict is Level.ACCEPT


class _Crasher(BaseOracle):
    name = "crasher"
    kinds: tuple[str, ...] = ("boom",)

    def build(self, ctx):
        raise RuntimeError("index exploded")

    def extract(self, change, ctx):
        raise ValueError("extract exploded")

    def check(self, claim, ctx):
        raise ValueError("check exploded")


def test_oracle_crashes_never_block(tmp_path):
    root = _repo(tmp_path)
    with _session(root, oracles={"crasher": _Crasher(), "env_vars": None}) as s:
        # Replace the None placeholder with a real oracle to keep config order.
        from weft.oracles.env_vars import EnvVarOracle

        s.oracles["env_vars"] = EnvVarOracle()
        report = s.sync()
        assert report["crasher"]["action"] == "failed" and "exploded" in s.sync_errors["crasher"]
        res = s.check_change(Change.from_file(os.path.join(root, "app.py")))
        assert res.verdict is Level.ACCEPT
        kinds = {f.claim.kind: f.level for f in res.findings}
        assert kinds["crasher:extract"] is Level.UNVERIFIABLE
        assert "sync_errors" in res.stats
        res = s.check_claims([Claim("boom", "x", Location("f"))])
        assert res.findings[0].level is Level.UNVERIFIABLE and res.verdict is Level.ACCEPT


def test_claim_mode_and_unknown_kinds(tmp_path):
    root = _repo(tmp_path)
    with _session(root) as s:
        claims = claims_from_json(
            {
                "claims": [
                    {"kind": "env_var", "subject": "DATABASE_URL"},
                    {"kind": "env", "subject": "NOPE", "file": "x.py", "line": 3},
                    {"kind": "mystery", "subject": "q"},
                    {"kind": "env_var", "subject": "NOPE2", "source": "prose"},
                ]
            }
        )
        res = s.check_claims(claims)
        by = {f.claim.subject: f for f in res.findings}
        assert by["DATABASE_URL"].level is Level.ACCEPT
        assert by["NOPE"].level is Level.REJECT and by["NOPE"].claim.source == "assertion"
        assert by["q"].level is Level.UNVERIFIABLE and by["q"].oracle == "gate"
        assert by["NOPE2"].level is Level.REVIEW  # prose-derived: never a reject
        assert res.verdict is Level.REJECT and res.stats["mode"] == "claim"


def test_claims_from_json_shapes_and_errors():
    claims = claims_from_json(
        [{"kind": "route", "method": "post", "path": "/users", "handler": "users.create"}]
    )
    assert claims[0].kind == "route_handler" and claims[0].subject == "POST /users"
    assert claims[0].attrs["handler"] == "users.create"
    with pytest.raises(ValueError):
        claims_from_json({"claims": "not a list"})
    with pytest.raises(ValueError):
        claims_from_json([{"subject": "x"}])
    with pytest.raises(ValueError):
        claims_from_json([{"kind": "env_var"}])
    with pytest.raises(ValueError):
        claims_from_json([{"kind": "route"}])
    with pytest.raises(ValueError):
        claims_from_json(["nope"])


def test_outcome_claims_route_to_honesty(tmp_path):
    root = _repo(tmp_path)
    with _session(root) as s:
        res = s.check_claims(claims_from_json([{"kind": "tests_pass", "command": "pytest -q"}]))
        f = res.findings[0]
        assert f.oracle == "honesty" and f.level is Level.REVIEW
        assert f.claim.attrs["honesty"] == "not_observed" and "to settle it" in f.reason


def test_blocks_respects_block_on(tmp_path):
    root = _repo(tmp_path)
    bad = write(root, "bad.py", "import os\nk = os.environ['ZZZ']\n")
    with _session(root, config=Config(oracles=["env_vars"], block_on="never")) as s:
        res = s.check_change(Change.from_file(bad))
        assert res.verdict is Level.REJECT and res.stats["blocking"] is False
    with _session(root, config=Config(oracles=["env_vars"], block_on="review")) as s:
        soft = write(root, "soft.py", "import os\nk = os.environ[name]\n")
        res = s.check_change(Change.from_file(soft))
        assert res.verdict is Level.REVIEW and blocks(res, s.config) is True


def test_dedupe_and_plugin_oracle(tmp_path):
    root = _repo(tmp_path)
    cfg = Config(oracles=["tests.plugins.dummy_oracle"])
    with _session(root, config=cfg) as s:
        assert isinstance(s.oracles["dummy"], DummyOracle)
        change = Change.from_text("f.txt", "DUMMY: nope\n")
        change.regions.append(Change.from_text("f.txt", "DUMMY: nope\n").regions[0])
        res = s.check_change(change)
        assert len(res.findings) == 1 and res.findings[0].suggestions == ("ok",)
        assert s.suggest("dummy_ref", "anything") == []


def test_module_level_wrappers(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    write(root, "weft.toml", '[weft]\noracles = ["env_vars"]\n')
    bad = write(root, "bad.py", "import os\nk = os.environ['DATABSE_URL']\n")
    assert check_change(root, Change.from_file(bad)).verdict is Level.REJECT
    assert index(root, rebuild=True)["oracles"]["env_vars"]["action"] == "build"
    assert status(root)["oracles"]["env_vars"]["built"] is True
    assert suggest(root, "env_var", "DATABSE_URL") == ["DATABASE_URL"]
