---
description: Run all knowledge base health checks (includes LLM contradiction check)
allowed-tools: Bash(uv run python scripts/lint.py:*)
---

Run `uv run python scripts/lint.py` and report any broken links, orphans, stale hashes, or contradictions it finds.
