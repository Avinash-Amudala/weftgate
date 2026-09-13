#!/usr/bin/env bash
# Wire weftgate into a target project: git pre-commit + Claude Code PreToolUse hook +
# the MCP server entry. Both hooks block only on a REJECT verdict.
#
#   bash scripts/install-hooks.sh /path/to/your/project
#
# This is a thin wrapper over `weftgate setup --hooks`, which does the merging into
# .claude/settings.json and .mcp.json without clobbering what is already there.
set -euo pipefail
TARGET="${1:-.}"

if command -v weftgate >/dev/null 2>&1; then
  weftgate --repo "$TARGET" setup --hooks
elif python3 -c 'import weftgate' >/dev/null 2>&1; then
  python3 -m weftgate --repo "$TARGET" setup --hooks
else
  echo "weftgate is not installed. Install it (pip install weftgate) and re-run, or wire it by hand:" >&2
  echo "  git pre-commit: weftgate check --staged --format=github" >&2
  echo "  Claude Code PreToolUse hook (matcher Edit|Write|MultiEdit): weftgate hook claude" >&2
  echo "  MCP server: {\"mcpServers\": {\"weftgate\": {\"command\": \"weftgate\", \"args\": [\"mcp\"]}}}" >&2
  exit 1
fi
