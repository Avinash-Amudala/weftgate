#!/usr/bin/env bash
# Install weftgate's own pre-push hook: the five checks CI runs, so a push that would go
# red never leaves the machine. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .git ] || { echo "run from a git checkout of weftgate" >&2; exit 1; }
cat > .git/hooks/pre-push <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
echo "weftgate pre-push: ruff, format, mypy, selftest, pytest"
"$PY" -m ruff check . && "$PY" -m ruff format --check . && "$PY" -m mypy weftgate \
  && "$PY" -m weftgate.selftest && "$PY" -m pytest -q
SH
chmod +x .git/hooks/pre-push
echo "installed .git/hooks/pre-push"
