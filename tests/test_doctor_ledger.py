"""weftgate doctor explains the setup; the ledger counts blocked changes; index --show dumps."""

import json
import os

from tests.conftest import write
from weftgate import doctor, ledger
from weftgate.cli import main as cli_main
from weftgate.eval.fixture import write_fixture
from weftgate.mcp_server import call_tool


def test_doctor_on_the_fixture_and_on_an_empty_dir(tmp_path, capsys):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    store = str(tmp_path / "i.sqlite")
    report = doctor.run(root, store_path=store)
    names = {c["name"]: c for c in report["checks"]}
    assert report["ok"] is True
    assert names["oracle env_vars"]["ok"] and names["env declarations"]["ok"]
    assert "requirements.txt" in names["dependency sources"]["detail"]
    assert names["dependency sources"]["hint"] == ""  # pinned requirements count as a lockfile
    assert "routes" in names["fastapi routes"]["detail"]
    assert "weftgate setup --hooks" in names["hooks"]["hint"]
    assert cli_main(["--repo", root, "--store", store, "doctor"]) == 0
    out = capsys.readouterr().out
    assert "weftgate doctor" in out and "everything the gate needs is in place" in out
    empty = str(tmp_path / "empty")
    os.makedirs(empty)
    write(empty, "weftgate.toml", '[weftgate]\noracles = ["env_vars", "imports_lockfile"]\n')
    report = doctor.run(empty, store_path=str(tmp_path / "e.sqlite"))
    names = {c["name"]: c for c in report["checks"]}
    assert (
        names["env declarations"]["ok"] is False
        and "review, not reject" in names["env declarations"]["hint"]
    )
    assert "lockfile" in names["dependency sources"]["hint"]
    assert cli_main(["--repo", empty, "--format", "json", "doctor"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    write(empty, "weftgate.toml", '[weftgate]\nblock_on = "maybe"\n')
    report = doctor.run(empty)
    assert report["checks"][0]["ok"] is False and report["ok"] is False


def test_ledger_records_only_blocking_verdicts(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root, broken=True)
    store = str(tmp_path / "i.sqlite")
    ledger.clear()
    assert ledger.summary()["blocks"] == 0
    assert cli_main(["--repo", root, "--store", store, "check", "app/config.py"]) == 0
    assert ledger.summary()["blocks"] == 0  # accept: nothing recorded
    assert cli_main(["--repo", root, "--store", store, "check", "app/broken.py"]) == 1
    call_tool("check_change", {"repo": root, "path": "app/broken.py"}, store_path=store)
    info = ledger.summary()
    assert info["blocks"] == 2 and info["broken_wires"] == 6
    assert info["by_surface"] == {"cli": 1, "mcp": 1}
    assert set(info["by_oracle"]) == {"env_vars", "imports_lockfile", "routes_fastapi"}
    assert info["estimated_tokens_saved"] == 2 * ledger.ROUND_TRIP_TOKENS
    capsys.readouterr()
    assert cli_main(["ledger"]) == 0
    out = capsys.readouterr().out
    assert "2 blocked change(s)" in out and "estimate" in out
    monkeypatch.setenv("WEFTGATE_LEDGER", "0")
    assert cli_main(["--repo", root, "--store", store, "check", "app/broken.py"]) == 1
    assert ledger.summary()["blocks"] == 2  # disabled: not recorded
    capsys.readouterr()
    assert cli_main(["ledger", "--clear"]) == 0
    assert ledger.summary()["blocks"] == 0


def test_index_show_dumps(tmp_path, capsys):
    root = str(tmp_path / "repo")
    os.makedirs(root)
    write_fixture(root)
    store = str(tmp_path / "i.sqlite")
    assert (
        cli_main(["--repo", root, "--store", store, "--format", "json", "index", "--show", "env"])
        == 0
    )
    env = json.loads(capsys.readouterr().out)
    assert env["DATABASE_URL"] == [".env.example"]
    assert cli_main(["--repo", root, "--store", store, "index", "--show", "routes"]) == 0
    out = capsys.readouterr().out
    assert "POST      /api/users" in out and "create_user" in out
    assert (
        cli_main(
            ["--repo", root, "--store", store, "--format", "json", "index", "--show", "imports"]
        )
        == 0
    )
    imports = json.loads(capsys.readouterr().out)
    assert imports["python"]["fastapi"] == ["requirements.txt"]
