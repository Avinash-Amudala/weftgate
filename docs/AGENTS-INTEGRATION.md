# Agent integration and activation

Install `weftgate` into the environment visible to your editor, then run:

```bash
weftgate setup --agents codex,claude,cursor,antigravity --hooks --instructions --dry-run
weftgate setup --agents codex,claude,cursor,antigravity --hooks --instructions
weftgate doctor
```

Setup merges existing configuration, preserves custom hooks and rules, and does
not edit global client settings. It prints snippets for global-only integrations.
`--instructions` adds short context/recall/checkpoint guidance. Existing AGENTS.md
content is preserved with an appended Weftgate block. Review generated changes
before committing them. A configuration file's presence is not proof of activation.

Git worktrees receive their own editor configuration. Git hooks shared with another
checkout, or an external `core.hooksPath`, are preserved and reported with a manual
integration hint. Existing Git hooks are never overwritten.

| Agent | MCP file | Completion hook file | Workflow guidance |
| --- | --- | --- | --- |
| Codex | `.codex/config.toml` | `.codex/hooks.json` | AGENTS.md appended block |
| Claude Code | `.mcp.json` | `.claude/settings.json` | `.claude/rules/weftgate.md` |
| Cursor | `.cursor/mcp.json` | `.cursor/hooks.json` | `.cursor/rules/weftgate.mdc` |
| Antigravity | `.agents/mcp_config.json` | `.agents/hooks.json` | `.agents/rules/weftgate.md` |
| VS Code / Copilot | `.vscode/mcp.json` | Git/CI fallback | `.github/instructions/weftgate.instructions.md` |

Claude also receives a PreToolUse adapter for reconstructible Edit/Write/MultiEdit
operations. The other new adapters run at completion, after writes occurred; they
do not intercept every edit or shell command. Stop checks catch changed source
files even when an agent used another editing tool.

## Activate and prove it in your client

1. Ensure `weftgate --version` runs in the editor's shell environment. Restart the
   MCP server if it was running an older package. Use the target repo as its cwd.
2. Trust the project and enable the configured MCP server. In Codex, review and
   trust the hook definition with `/hooks`. Organization policy may disallow it.
3. Ask the agent to call `resolve` for a known symbol and `recall` for a saved note.
4. In a disposable fixture with `.env.example` declaring `DATABASE_URL`, add a
   source read of `os.environ['DATABSE_URL']`. A completion hook should request repair;
   Claude's supported pre-edit tool should block before writing. Correct the spelling
   and recheck. A dynamic key should remain advisory. Do not plant this in production.
5. Confirm normal tests still run, and make the GitHub Action a required status
   check if merges must be gated regardless of client behavior.

The adapters have automated protocol-fixture tests. They have not been interactively
certified against every editor build, operating system and organization policy.
MCP, rules, and local hooks are useful guardrails and can be disabled or skipped by
host policy. None is a complete enforcement boundary for every tool path.

## Official integration references

Checked September 13, 2026:

- [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) and
  [Codex hooks](https://learn.chatgpt.com/docs/hooks): project config and hook trust.
- [Claude Code hooks](https://code.claude.com/docs/en/hooks): PreToolUse and Stop shapes.
- [Cursor hooks](https://cursor.com/docs/hooks) and
  [Cursor rules](https://cursor.com/docs/rules): project hooks, stop follow-ups and rules.
- [Antigravity MCP](https://antigravity.google/docs/mcp),
  [hooks](https://antigravity.google/docs/hooks/) and
  [rules](https://antigravity.google/docs/rules-workflows): workspace paths and camelCase payloads.
