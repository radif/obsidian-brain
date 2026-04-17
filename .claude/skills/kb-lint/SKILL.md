---
name: kb-lint
description: Use when the user wants a full health check of the knowledge base including broken links, orphans, stale hashes, AND LLM-based contradiction detection. Runs `uv run python scripts/lint.py`. This is not free — it spends tokens on the contradiction check.
---

Run `uv run python scripts/lint.py` via the Bash tool. Report any issues it finds: broken `[[wikilinks]]`, orphaned articles, stale hashes (raw files edited after compilation), and logical contradictions between articles. If the user only wants fast structural checks, use the `kb-lint-structural` skill instead.
