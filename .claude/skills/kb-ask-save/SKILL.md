---
name: kb-ask-save
description: Use when the user wants an answer from the knowledge base that is worth preserving as a durable artifact under knowledge/qa/. Runs `uv run python scripts/query.py "question" --file-back`, which both answers and writes the answer to knowledge/qa/ so future sessions can find it via the index.
---

Run `uv run python scripts/query.py "<question>" --file-back` via the Bash tool and report the answer. The sub-agent also writes the answer into `knowledge/qa/` and updates `knowledge/index.md`, so the answer becomes part of the corpus.

Prefer this over `kb-ask` when the question is one the user (or a future session) is likely to ask again, or when the synthesis is non-trivial enough that re-deriving it would be wasteful.
