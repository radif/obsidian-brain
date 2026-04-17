---
description: Ask the knowledge base and save the answer to knowledge/qa/
allowed-tools: Bash(uv run python scripts/query.py:*)
---

Run `uv run python scripts/query.py "$ARGUMENTS" --file-back` and report the answer. The answer is also persisted under `knowledge/qa/` as a compilable artifact. If `$ARGUMENTS` is empty, ask the user for the question first.
