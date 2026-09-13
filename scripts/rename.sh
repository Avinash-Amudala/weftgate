#!/usr/bin/env bash
# Rename the project in one go (the design says nothing depends on the name):
#   bash scripts/rename.sh <newname>
#
# Renames the package directory, the console script, the entry-point group, every
# import, the <NAME>_* environment variables, and every mention in docs, tests, hooks,
# and workflows. Resumable: if the directory was already moved, only the text step
# runs. Never touches this script, binaries, or the .git directory. Afterwards:
#   pip uninstall -y <oldname>; pip install -e ".[all,dev]"; then the five checks;
#   gh repo rename <newname> (GitHub redirects the old name); commit.
set -euo pipefail
NEW="${1:-}"
if [ -z "$NEW" ] || ! [[ "$NEW" =~ ^[a-z][a-z0-9_]*$ ]]; then
  echo "usage: bash scripts/rename.sh <newname>   (lowercase, letters/digits/_)" >&2
  exit 2
fi
cd "$(dirname "$0")/.."
# The current name is whatever pyproject.toml says, so a partially renamed tree
# (directory moved, text not yet replaced) resumes correctly.
OLD="$(sed -n 's/^name = "\([a-z][a-z0-9_-]*\)"$/\1/p' pyproject.toml | head -1)"
if [ -z "$OLD" ]; then echo "cannot read the current name from pyproject.toml" >&2; exit 1; fi
if [ "$OLD" = "$NEW" ]; then echo "already named $NEW"; exit 0; fi
OLD_UPPER="$(printf '%s' "$OLD" | tr '[:lower:]' '[:upper:]')"
NEW_UPPER="$(printf '%s' "$NEW" | tr '[:lower:]' '[:upper:]')"

# 1) the package directory (skipped when a previous run already moved it)
if [ -d "$OLD" ] && [ ! -d "$NEW" ]; then
  git mv "$OLD" "$NEW" 2>/dev/null || mv "$OLD" "$NEW"
elif [ ! -d "$NEW" ]; then
  echo "neither $OLD/ nor $NEW/ exists; nothing to rename" >&2; exit 1
fi

# 2) every textual mention, word-bounded, in tracked text files
self="scripts/rename.sh"
changed=0
while IFS= read -r -d '' f; do
  [ "$f" = "$self" ] && continue
  [ -f "$f" ] || continue
  case "$f" in *.png|*.jpg|*.gif|*.ico|*.sqlite|*.whl|.coverage) continue ;; esac
  if grep -qI -w -e "$OLD" -e "${OLD_UPPER}_" "$f"; then
    perl -pi -e "s/\\b${OLD}\\b/${NEW}/g; s/\\b${OLD_UPPER}_/${NEW_UPPER}_/g" "$f"
    changed=$((changed + 1))
  fi
done < <(git ls-files -z 2>/dev/null || find . -type f -not -path './.git/*' -not -path './.venv/*' -print0)

echo "renamed '$OLD' -> '$NEW' ($changed files edited)."
echo "next: pip uninstall -y $OLD; pip install -e '.[all,dev]'"
echo "      ruff check . && ruff format --check . && mypy $NEW && python -m $NEW.selftest && pytest -q"
echo "      gh repo rename $NEW; git add -A; git commit"
