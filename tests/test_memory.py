"""Verified memory's half of the graph: the changed-node ledger, anchors, re-checks,
and weftgate's oracles offered through mnemo's plugin protocol."""

import json
import os
from pathlib import Path

from tests.conftest import write
from weftgate import cli, mcp_server, memory
from weftgate.eval.fixture import write_fixture
from weftgate.gate import Session


def _repo(tmp_path):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    return root, str(tmp_path / "i.sqlite")


def test_sync_records_changed_nodes(tmp_path):
    root, store = _repo(tmp_path)
    with Session(root, store_path=store) as s:
        s.sync()
        assert s.last_changes == [] and s.store.head_seq() == 0  # first build: no "before"
        s.sync()
        assert s.last_changes == []  # no-op sync records nothing
        write(root, ".env.example", "DATABASE_URL=\nAPI_KEY=\nREDIS_URL=\nSMTP_HOST=\nNEW_ONE=\n")
        write(
            root,
            "app/orders.py",
            Path(os.path.join(root, "app/orders.py"))
            .read_text(encoding="utf-8")
            .replace(
                "@router.get('/orders/{order_id}')\nasync def get_order",
                "@router.get('/order/{id}')\nasync def fetch_order",
            ),
        )
        write(root, "requirements.txt", "fastapi==0.115.0\nrequests==2.32.3\n")
        s.sync()
        ops = dict(s.last_changes)
        assert ops["env:NEW_ONE"] == "added"
        assert ops["file:.env.example"] == "changed" and ops["file:app/orders.py"] == "changed"
        assert ops["route:GET /api/orders/{order_id}"] == "removed"
        assert ops["route:GET /api/order/{id}"] == "added"
        assert ops["symbol:app/orders.py:get_order"] == "removed"
        assert ops["symbol:app/orders.py:fetch_order"] == "added"
        assert ops["dist:python:PyYAML"] == "removed"
        seq = s.store.head_seq()
        assert seq == len(s.last_changes) > 0
        since = memory.changes(s, since=0, sync=False)
        assert since["seq"] == seq and {c["node"] for c in since["changes"]} == set(ops)
        assert memory.changes(s, since=seq, sync=False)["changes"] == []


def test_anchor_and_check_lifecycle(tmp_path):
    root, store = _repo(tmp_path)
    with Session(root, store_path=store) as s:
        text = (
            "The API reads DATABASE_URL and REDIS_URL from the environment. POST /api/users "
            "creates a user, see app/users.py; it uses `sqlalchemy` and import requests. "
            "NOT_A_VAR is not declared anywhere and GET /nope does not exist."
        )
        a = memory.anchor(s, text, {"symbols": ["app/handlers.py:health"]})
        nodes = {x["node"]: x for x in a["anchors"]}
        # Declared claims always anchor; prose only anchors what resolves now.
        assert nodes["symbol:app/handlers.py:health"]["state"] == "valid"
        assert (
            nodes["env:DATABASE_URL"]["state"] == "valid"
            and nodes["env:DATABASE_URL"]["declared"] is False
        )
        assert nodes["route:POST /api/users"]["state"] == "valid"
        assert nodes["file:app/users.py"]["state"] == "valid"
        assert nodes["dist:python:sqlalchemy"]["state"] == "valid"
        assert nodes["dist:python:requests"]["state"] == "valid"
        assert "env:NOT_A_VAR" not in nodes and "route:GET /nope" not in nodes
        assert all(
            x.get("content_hash") for x in a["anchors"] if x["kind"] in ("file", "env", "symbol")
        )
        # Declared but false: the anchor exists and is invalid, with a suggestion.
        bad = memory.anchor(s, "", {"env": ["DATABSE_URL"], "routes": ["GET /nope"]})
        states = {x["node"]: x for x in bad["anchors"]}
        assert states["env:DATABSE_URL"]["state"] == "invalid"
        assert states["env:DATABSE_URL"]["did_you_mean"] == ["DATABASE_URL"]
        assert states["route:GET /nope"]["state"] == "invalid"

        # Nothing changed: every anchor still valid.
        chk = memory.check(s, a["anchors"])
        assert chk["summary"] == "valid" and all(x["state"] == "valid" for x in chk["anchors"])
        # The handler's body changes: its span hash differs -> stale, not invalid.
        write(
            root,
            "app/handlers.py",
            Path(os.path.join(root, "app/handlers.py"))
            .read_text(encoding="utf-8")
            .replace("return {'ok': True}", "return {'ok': True, 'v': 2}"),
        )
        chk = memory.check(s, a["anchors"])
        by = {x["node"]: x for x in chk["anchors"]}
        assert by["symbol:app/handlers.py:health"]["state"] == "stale"
        assert chk["summary"] == "stale"
        # The declaration disappears: invalid.
        write(root, ".env.example", "REDIS_URL=\nAPI_KEY=\nSMTP_HOST=\n")
        chk = memory.check(s, a["anchors"])
        by = {x["node"]: x for x in chk["anchors"]}
        assert by["env:DATABASE_URL"]["state"] == "invalid" and chk["summary"] == "invalid"
        assert by["env:REDIS_URL"]["state"] == "valid"
        malformed = memory.check(s, [{"kind": "nope", "locator": "x"}], sync=False)
        assert malformed["anchors"][0]["state"] == "unverifiable"


class _FakeApi:
    def __init__(self):
        self.oracles = {}

    def register_oracle(self, kind, extract, check):
        self.oracles[kind] = (extract, check)


def test_mnemo_plugin_protocol(tmp_path, monkeypatch):
    root, store = _repo(tmp_path)
    monkeypatch.setenv("WEFTGATE_CACHE", str(tmp_path / "cache"))
    api = _FakeApi()
    memory.register(api)
    assert set(api.oracles) == {"env", "routes", "imports"}
    extract, check = api.oracles["env"]
    assert extract("we read DATABASE_URL and also SMTP_HOST; not lowercase_thing") == [
        "DATABASE_URL",
        "SMTP_HOST",
    ]
    # A declared false claim rejects, with did_you_mean; the same claim read from
    # prose only reviews (a guess never hard-rejects).
    entry = check("DATABSE_URL", True, root)
    assert entry["status"] == "reject" and entry["did_you_mean"] == ["DATABASE_URL"]
    assert check("DATABSE_URL", False, root)["status"] == "review"
    assert check("DATABASE_URL", True, root)["status"] == "accept"
    extract_r, check_r = api.oracles["routes"]
    assert extract_r("call POST /api/users then GET /health") == ["GET /health", "POST /api/users"]
    assert check_r("POST /api/users", True, root)["status"] == "accept"
    assert check_r("POST /api/user", True, root)["status"] == "reject"
    extract_i, check_i = api.oracles["imports"]
    assert "requests" in extract_i("import requests\nfrom fastapi import X\nuse `yaml` here")
    assert check_i("requestz", True, root)["status"] == "reject"
    assert check_i("os", True, root)["status"] == "accept"
    # A repo weftgate cannot index never rejects.
    assert check("ANYTHING", True, str(tmp_path / "nowhere"))["status"] in (
        "review",
        "unverifiable",
    )
    memory.close_sessions()
    assert memory._SESSIONS == {}


def test_memory_surfaces_agree(tmp_path, capsys):
    root, store = _repo(tmp_path)
    payload = {"text": "reads DATABASE_URL; POST /api/users", "claims": {"files": ["app/main.py"]}}
    assert (
        cli.main(["--repo", root, "--store", store, "memory", "anchor", json.dumps(payload)]) == 0
    )
    via_cli = json.loads(capsys.readouterr().out)
    via_mcp = mcp_server.call_tool("memory_anchor", {"repo": root, **payload}, store_path=store)
    assert via_cli == via_mcp and len(via_cli["anchors"]) == 3
    check_payload = {"anchors": via_cli["anchors"]}
    assert (
        cli.main(["--repo", root, "--store", store, "memory", "check", json.dumps(check_payload)])
        == 0
    )
    via_cli = json.loads(capsys.readouterr().out)
    via_mcp = mcp_server.call_tool(
        "memory_check", {"repo": root, **check_payload}, store_path=store
    )
    assert via_cli["summary"] == via_mcp["summary"] == "valid"
    assert cli.main(["--repo", root, "--store", store, "memory", "changes", "--since", "0"]) == 0
    via_cli = json.loads(capsys.readouterr().out)
    via_mcp = mcp_server.call_tool("memory_changes", {"repo": root, "since": 0}, store_path=store)
    assert via_cli == via_mcp
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "memory_check", "arguments": {"repo": root}},
        }
    )
    assert resp is not None and resp["result"]["isError"] is True
