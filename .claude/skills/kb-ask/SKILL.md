---
name: kb-ask
description: Use when the user wants a cross-article synthesis from the knowledge base without polluting the current conversation's context, or when they want a fresh perspective unbiased by the current session. Runs `uv run python scripts/query.py "question"` which spawns an isolated sub-agent.
---

Run `uv run python scripts/query.py "<question>"` via the Bash tool and report the answer verbatim.

**When NOT to use this skill:** if the question is about a single concept already in `knowledge/index.md` (injected into every session), it's faster and cheaper to `Read` the article directly than to spawn a sub-agent. Reserve this skill for multi-article synthesis or when you explicitly want context isolation. If the user wants the answer persisted as a durable artifact, use the `kb-ask-save` skill instead.
