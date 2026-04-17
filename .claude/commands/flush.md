---
description: Manually flush a session transcript into raw/daily/
allowed-tools: Bash(uv run python scripts/flush.py:*)
---

Run `uv run python scripts/flush.py` and report what was appended to the daily log. Normally this is triggered automatically by SessionEnd/PreCompact hooks — only run manually for debugging or if the hook didn't fire.
