#!/usr/bin/env bash
# Wire weft into a target project: git pre-commit + Claude Code PreToolUse hook +
# the MCP server entry. Both hooks block only on a REJECT verdict.
#
#   bash scripts/install-hooks.sh /path/to/your/project
#
# This is a thin wrapper over `weft setup --hooks`, which does the merging into
# .claude/settings.json and .mcp.json without clobbering what is already there.
set -euo pipefail
TARGET="${1:-.}"

if command -v weft >/dev/null 2>&1; then
  weft --repo "$TARGET" setup --hooks
elif python3 -c 'import weft' >/dev/null 2>&1; then
  python3 -m weft --repo "$TARGET" setup --hooks
else
  echo "weft is not installed. Install it (pip install weft) and re-run, or wire it by hand:" >&2
  echo "  git pre-commit: weft check --staged --format=github" >&2
  echo "  Claude Code PreToolUse hook (matcher Edit|Write|MultiEdit): weft hook claude" >&2
  echo "  MCP server: {\"mcpServers\": {\"weft\": {\"command\": \"weft\", \"args\": [\"mcp\"]}}}" >&2
  exit 1
fi
