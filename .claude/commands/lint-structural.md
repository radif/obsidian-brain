---
description: Free structural health checks only (no LLM contradiction check)
allowed-tools: Bash(uv run python scripts/lint.py --structural-only:*)
---

Run `uv run python scripts/lint.py --structural-only` and report any broken links, orphans, or stale hashes. This skips the LLM contradiction check and is free to run.
