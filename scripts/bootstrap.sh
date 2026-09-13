#!/usr/bin/env bash
# One-command dev setup. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if ! "$PY" -c 'import sys; assert sys.version_info[:2] >= (3,10)' 2>/dev/null; then
  echo "weftgate needs Python 3.10+. Set PYTHON=/path/to/python3.10 and re-run." >&2
  exit 1
fi

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

python -m pip install --upgrade pip
# editable install with every extra + dev tools, so the build env is complete
pip install -e ".[all,dev]"

echo
echo "Running self-test..."
python -m weftgate.selftest
echo
echo "Ready. Activate with:  . .venv/bin/activate"
