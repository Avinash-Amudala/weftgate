"""Invariants that are easy to break silently: the core imports nothing outside
the standard library, and the Python 3.10 backport of StrEnum behaves."""

from __future__ import annotations

import subprocess
import sys
import sysconfig

CORE = (
    "types",
    "config",
    "registry",
    "oracle",
    "store",
    "gate",
    "change",
    "suggest",
    "honesty",
    "cli",
    "mcp_server",
    "selftest",
    "setup",
    "memory",
    "ledger",
    "doctor",
)


def test_core_modules_import_only_the_standard_library():
    script = (
        "import sys, importlib\n"
        "def third_party():\n"
        "    return {k for k, v in sys.modules.items()"
        " if getattr(v, '__file__', None) and 'site-packages' in (v.__file__ or '')"
        " and not k.startswith('weftgate')}\n"
        "before = third_party()  # .pth hooks (pywin32_bootstrap, editable finders) preload\n"
        f"for m in {CORE!r}:\n"
        "    importlib.import_module('weftgate.' + m)\n"
        "print('\\n'.join(sorted(third_party() - before)))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    third_party = [line for line in proc.stdout.splitlines() if line.strip()]
    # Editable installs may expose a path hook; anything else is a real dependency.
    third_party = [m for m in third_party if not m.startswith("_") and "editable" not in m]
    assert third_party == [], f"core pulled in third-party modules: {third_party}"
    assert sysconfig.get_paths()["purelib"]  # sanity: the check looked somewhere real


def test_strenum_backport_matches_the_real_thing():
    script = (
        "import sys\n"
        "sys.version_info = (3, 10, 0, 'final', 0)\n"
        "import weftgate.types as t\n"
        "assert t.StrEnum.__module__ == 'weftgate.types', t.StrEnum.__module__\n"
        "assert str(t.Level.REJECT) == 'reject' and t.Level.REJECT == 'reject'\n"
        "assert t.Level('review') is t.Level.REVIEW\n"
        "assert t.worst([t.Level.REVIEW, t.Level.UNVERIFIABLE]) is t.Level.REVIEW\n"
        "import json; assert json.dumps({'v': t.Level.ACCEPT}) == '{\"v\": \"accept\"}'\n"
        "print('backport ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "backport ok" in proc.stdout
