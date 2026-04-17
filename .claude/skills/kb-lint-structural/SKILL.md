---
name: kb-lint-structural
description: Use when the user wants fast, free health checks of the knowledge base — broken links, orphans, stale hashes — without the LLM-based contradiction check. Runs `uv run python scripts/lint.py --structural-only`.
---

Run `uv run python scripts/lint.py --structural-only` via the Bash tool. Report any broken `[[wikilinks]]`, orphaned articles, or stale hashes. This is free and fast, so it's the right default after any compile. For deeper semantic checks, use the `kb-lint` skill.
