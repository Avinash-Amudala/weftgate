"""Portable pre-release project rename; the shell wrapper delegates here."""

import os
import pathlib
import re
import subprocess
import sys

if len(sys.argv) != 2 or not re.fullmatch(r"[a-z][a-z0-9_]*", sys.argv[1]):
    raise SystemExit("usage: bash scripts/rename.sh <lowercase_python_identifier>")
new = sys.argv[1]
root = pathlib.Path(__file__).resolve().parents[1]
os.chdir(root)
match = re.search(r'^name = "([a-z][a-z0-9_-]*)"$', (root / "pyproject.toml").read_text(), re.M)
if not match:
    raise SystemExit("cannot read the project name from pyproject.toml")
old = match.group(1)
if old == new:
    print("already named " + new)
    raise SystemExit(0)
for suffix in ("", ".toml"):
    src, dst = root / (old + suffix), root / (new + suffix)
    if src.exists() and dst.exists():
        raise SystemExit("refusing to overwrite " + str(dst))
if not (root / old).is_dir() and not (root / new).is_dir():
    raise SystemExit("package directory not found")
# Limit the rewrite to tracked UTF-8 text. Exclude this script and binary assets.
files = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
for suffix in ("", ".toml"):
    src, dst = root / (old + suffix), root / (new + suffix)
    if src.exists():
        subprocess.run(["git", "mv", str(src), str(dst)], check=True)
count = 0
for rel in files:
    if not rel or rel in {"scripts/rename.sh", "scripts/rename.py"}:
        continue
    if rel == old + ".toml":
        rel = new + ".toml"
    if rel.startswith(old + "/"):
        rel = new + rel[len(old) :]
    path = root / rel
    if not path.is_file():
        continue
    data = path.read_bytes()
    if b"\0" in data:
        continue
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        continue
    result = re.sub(r"\b" + re.escape(old) + r"\b", new, text)
    result = re.sub(r"\b" + re.escape(old.upper()) + "_", new.upper() + "_", result)
    if result != text:
        path.write_bytes(result.encode("utf-8"))
        count += 1
print(f"renamed {old} -> {new} ({count} text files)")
print(f"Next: pip uninstall -y {old}; pip install -e '.[all,dev]'")
print("Run lint, types, selftest, and pytest before committing or renaming the remote.")
