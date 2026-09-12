#!/usr/bin/env bash
# Rename the project in one go (the design says nothing depends on the name).
# The distribution name "weft" is taken on PyPI, so pick a free one before the
# first release:  bash scripts/rename.sh <newname>
#
# Renames the package directory, the console script, the entry-point group, every
# import, and every mention in docs, tests, hooks, and workflows. Re-run the four
# checks afterwards; the self-test proves the rename left the wiring intact.
set -euo pipefail
NEW="${1:-}"
if [ -z "$NEW" ] || ! [[ "$NEW" =~ ^[a-z][a-z0-9_]*$ ]]; then
  echo "usage: bash scripts/rename.sh <newname>   (lowercase, letters/digits/_)" >&2
  exit 2
fi
cd "$(dirname "$0")/.."
OLD="weft"
if [ ! -d "$OLD" ]; then
  echo "package directory '$OLD' not found; already renamed?" >&2
  exit 1
fi
# 1) the package directory
git mv "$OLD" "$NEW" 2>/dev/null || mv "$OLD" "$NEW"
# 2) every textual mention, word-bounded, in tracked text files (not the .git dir,
#    not the venv, not this script's own usage line)
files=$(git ls-files 2>/dev/null || find . -type f -not -path './.git/*' -not -path './.venv/*')
for f in $files; do
  case "$f" in *.png|*.jpg|*.gif|*.sqlite|*.whl) continue ;; esac
  [ -f "$f" ] || continue
  if grep -qI "$OLD" "$f"; then
    perl -pi -e "s/\\b${OLD}\\b/${NEW}/g; s/\\bWEFT_/\\U${NEW}_/g" "$f"
  fi
done
echo "renamed '$OLD' -> '$NEW'. Now: pip install -e '.[all,dev]' && ruff check . && mypy $NEW && python -m $NEW.selftest && pytest -q"
echo "then update the GitHub repo name and the PyPI trusted publisher, and commit."
