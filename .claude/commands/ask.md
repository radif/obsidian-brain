---
description: Ask the knowledge base a question (isolated sub-agent)
allowed-tools: Bash(uv run python scripts/query.py:*)
---

Run `uv run python scripts/query.py "$ARGUMENTS"` and report the answer verbatim. If `$ARGUMENTS` is empty, ask the user what they want to know before running anything.
