---
name: kb-flush
description: Use when the user explicitly wants to manually flush the current session transcript into raw/daily/. Normally this is triggered automatically by SessionEnd/PreCompact hooks, so only use this skill if the user asks for a manual flush, is debugging the flush pipeline, or suspects the hook didn't fire.
---

Run `uv run python scripts/flush.py` via the Bash tool. Report what was appended to today's `raw/daily/YYYY-MM-DD.md`.

**Important caveat from CLAUDE.md:** running a manual flush while the parent Claude Code session is still alive can race the bundled CLI subprocess. Prefer `/compact` or `/exit` for routine captures — only use this skill when the user has an explicit reason to bypass the hooks.
