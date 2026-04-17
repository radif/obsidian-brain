---
name: kb-compile-all
description: Use when the user explicitly wants to force a full recompile of every raw file (e.g. after changing the AGENTS.md schema, fixing a compile bug, or rebuilding from scratch). Runs `uv run python scripts/compile.py --all`, which is expensive.
---

Run `uv run python scripts/compile.py --all` via the Bash tool. This recompiles every raw file regardless of hash state — it spends LLM tokens proportional to the full corpus, so warn the user if the knowledge base is large. For routine work, prefer the `kb-compile` skill which only touches changed files.
