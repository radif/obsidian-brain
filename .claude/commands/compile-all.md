---
description: Force a full recompile of every raw file
allowed-tools: Bash(uv run python scripts/compile.py --all:*)
---

Run `uv run python scripts/compile.py --all` and report what was rebuilt. Warn the user this is expensive — only use when you explicitly want to redo everything.
