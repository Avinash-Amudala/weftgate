"""The CLI and the MCP server must never diverge: same input, same findings.

Three layers: the pure tool function vs the CLI renderer, a real subprocess
speaking JSON-RPC over stdio, and (when the optional `mcp` extra is installed)
the official MCP client driving the server end to end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests.conftest import write
from weft import cli, mcp_server

BAD = "import os\nk = os.environ['DATABSE_URL']\nimport requestz\n"


def _repo(tmp_path):
    root = str(tmp_path / "repo")
    write(root, ".env.example", "DATABASE_URL=\nAPI_KEY=\n")
    write(root, "requirements.txt", "requests==2.32.0\n")
    write(root, "weft.toml", '[weft]\noracles = ["env_vars"]\n')
    write(root, "bad.py", BAD)
    return root


def _cli_json(argv: list[str], capsys) -> dict:
    code = cli.main(argv)
    out = capsys.readouterr().out
    return json.loads(out), code


def test_direct_parity_check_change(tmp_path, capsys):
    root = _repo(tmp_path)
    bad = os.path.join(root, "bad.py")
    via_cli, code = _cli_json(["--repo", root, "--format", "json", "check", bad], capsys)
    assert code == 1 and via_cli["verdict"] == "reject"
    via_mcp = mcp_server.call_tool("check_change", {"repo": root, "path": "bad.py"})
    assert via_cli == via_mcp
    # New content that is not on disk: same path through both surfaces.
    content_file = write(str(tmp_path), "content.txt", BAD)
    via_cli2, _ = _cli_json(
        [
            "--repo",
            root,
            "--format",
            "json",
            "check",
            "--path",
            "bad.py",
            "--content",
            content_file,
        ],
        capsys,
    )
    via_mcp2 = mcp_server.call_tool(
        "check_change", {"repo": root, "path": "bad.py", "content": BAD}
    )
    assert via_cli2 == via_mcp2 == via_cli


def test_direct_parity_claims_suggest_status(tmp_path, capsys):
    root = _repo(tmp_path)
    claims = [
        {"kind": "env_var", "subject": "DATABSE_URL"},
        {"kind": "tests_pass", "command": "pytest -q"},
    ]
    via_cli, code = _cli_json(
        ["--repo", root, "--format", "json", "claim", json.dumps(claims)], capsys
    )
    via_mcp = mcp_server.call_tool("check_claim", {"repo": root, "claims": claims})
    assert via_cli == via_mcp and code == 1
    via_cli, _ = _cli_json(
        ["--repo", root, "--format", "json", "suggest", "env_var", "DATABSE_URL"], capsys
    )
    via_mcp = mcp_server.call_tool(
        "suggest", {"repo": root, "kind": "env_var", "subject": "DATABSE_URL"}
    )
    assert (
        via_cli
        == via_mcp
        == {"kind": "env_var", "subject": "DATABSE_URL", "suggestions": ["DATABASE_URL"]}
    )
    via_cli, _ = _cli_json(["--repo", root, "--format", "json", "index", "--status"], capsys)
    via_mcp = mcp_server.call_tool("index_status", {"repo": root})
    assert via_cli == via_mcp


def test_text_and_github_formats_and_exit_codes(tmp_path, capsys):
    root = _repo(tmp_path)
    bad = os.path.join(root, "bad.py")
    assert cli.main(["--repo", root, "check", bad]) == 1
    out = capsys.readouterr().out
    assert "REJECT" in out and "did you mean DATABASE_URL" in out and "verdict: reject" in out
    assert cli.main(["--repo", root, "--format", "github", "check", bad]) == 1
    out = capsys.readouterr().out
    assert out.startswith("::error file=bad.py,line=2,title=weft env_vars::")
    good = write(root, "good.py", "import os\nk = os.environ['API_KEY']\n")
    assert cli.main(["--repo", root, "check", good]) == 0
    assert "ok, no broken wires found" in capsys.readouterr().out
    assert cli.main(["--repo", root, "claim", "not json"]) == 2
    assert "invalid claims" in capsys.readouterr().err
    assert cli.main([]) == 0


def test_stdin_diff_and_directory(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    diff = "--- a/n.py\n+++ b/n.py\n@@ -0,0 +1,2 @@\n+import os\n+z = os.getenv('NOPE_AT_ALL')\n"
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO(diff))
    assert cli.main(["--repo", root, "--format", "json", "check", "-"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["findings"][0]["file"] == "n.py" and data["findings"][0]["line"] == 2
    assert data == mcp_server.call_tool("check_change", {"repo": root, "diff": diff})
    assert cli.main(["--repo", root, "--format", "json", "check", root]) == 1
    data = json.loads(capsys.readouterr().out)
    assert "bad.py" in data["stats"]["files"]


def test_mcp_tool_errors_are_reported_not_raised(tmp_path):
    root = _repo(tmp_path)
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "check_change", "arguments": {"repo": root}},
        }
    )
    assert resp is not None and resp["result"]["isError"] is True
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "nope"})
    assert resp is not None and resp["error"]["code"] == -32601
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert mcp_server.handle_message(note) is None
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "check_change", "arguments": {"repo": root, "path": "missing.py"}},
        }
    )
    assert resp is not None and "no such file" in resp["result"]["content"][0]["text"]


def _rpc_lines(msgs: list[dict]) -> str:
    return "".join(json.dumps(m) + "\n" for m in msgs)


def test_stdio_server_subprocess_matches_cli(tmp_path, capsys):
    root = _repo(tmp_path)
    via_cli, _ = _cli_json(
        ["--repo", root, "--format", "json", "check", os.path.join(root, "bad.py")], capsys
    )
    msgs = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "check_change", "arguments": {"path": "bad.py"}},
        },
        "this is not json",
    ]
    stdin = _rpc_lines([m for m in msgs if isinstance(m, dict)]) + "this is not json\n"
    proc = subprocess.run(
        [sys.executable, "-m", "weft.mcp_server"],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    by_id = {r.get("id"): r for r in responses}
    assert by_id[1]["result"]["serverInfo"]["name"] == "weft"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} >= {
        "check_change",
        "check_claim",
        "audit",
        "suggest",
        "index_status",
    }
    call = by_id[3]["result"]
    assert call["isError"] is False
    assert call["structuredContent"] == via_cli
    assert json.loads(call["content"][0]["text"]) == via_cli
    assert by_id[None]["error"]["code"] == -32700


def test_official_mcp_client_drives_the_server(tmp_path, capsys):
    mcp = pytest.importorskip("mcp")
    import asyncio

    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = _repo(tmp_path)
    via_cli, _ = _cli_json(
        ["--repo", root, "--format", "json", "check", os.path.join(root, "bad.py")], capsys
    )

    errlog = open(os.path.join(str(tmp_path), "server-stderr.log"), "w")  # noqa: SIM115

    async def drive() -> tuple[list[str], dict]:
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "weft.mcp_server"], cwd=root, env=dict(os.environ)
        )
        async with stdio_client(params, errlog=errlog) as (read, write_):
            async with mcp.ClientSession(read, write_) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool("check_change", {"path": "bad.py"})
                return [t.name for t in tools.tools], json.loads(result.content[0].text)

    try:
        names, payload = asyncio.run(asyncio.wait_for(drive(), timeout=120))
    finally:
        errlog.close()
    assert "check_change" in names
    assert payload == via_cli


def test_global_options_work_after_the_subcommand(tmp_path, capsys):
    """The pre-commit hook runs `weft check --staged --format=github`; README examples put
    --format after the command too. Both positions must parse and agree."""
    root = _repo(tmp_path)
    bad = os.path.join(root, "bad.py")
    assert cli.main(["--repo", root, "--format", "json", "check", bad]) == 1
    before = json.loads(capsys.readouterr().out)
    assert cli.main(["check", bad, "--repo", root, "--format=json"]) == 1
    after = json.loads(capsys.readouterr().out)
    assert before == after
    assert cli.main(["audit", "--repo", root, "--format=github"]) == 1
    assert capsys.readouterr().out.startswith("::error ")
    assert cli.main(["eval", "mutate", "--fixture", "--seed", "13", "--format=json"]) == 0
    assert json.loads(capsys.readouterr().out)["misses"] == 0
    assert cli.main(["index", "--status", "--repo", root, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["oracles"]["env_vars"]["built"] is True
