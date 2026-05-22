"""
Query the knowledge base using index-guided retrieval (no RAG).

The LLM reads the index, picks relevant articles, and synthesizes an answer.
No vector database, no embeddings, no chunking - just structured markdown
and an index the LLM can reason over.

Usage:
    uv run python query.py "How should I handle auth redirects?"
    uv run python query.py "What patterns do I use for API design?" --file-back
"""

from __future__ import annotations

# Hook recursion guard: tells the hooks in .claude/settings.json to no-op
# inside the Claude Code subprocess that the Agent SDK will spawn below.
# Must be set BEFORE any imports that might invoke the SDK.
import os
os.environ["CLAUDE_INVOKED_BY"] = "query"

import argparse
import asyncio
from pathlib import Path

from config import KNOWLEDGE_DIR, LOG_FILE, QA_DIR, now_iso
from utils import COST_DISCLAIMER, format_token_usage, load_state, read_all_wiki_content, rebuild_index, save_state


def _snapshot_qa() -> dict[str, float]:
    if not QA_DIR.exists():
        return {}
    return {str(p.relative_to(KNOWLEDGE_DIR)): p.stat().st_mtime for p in QA_DIR.rglob("*.md")}


def _append_query_log(timestamp: str, question: str, created: list[str], updated: list[str], cost: float) -> None:
    """Append a structured one-entry record to knowledge/log.md for a file-back
    query. Runner-owned to keep log.md bounded (see compile.py for context)."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# Build Log\n", encoding="utf-8")
    summary = question if len(question) <= 100 else question[:97] + "..."
    lines = [f"\n## [{timestamp}] query (filed) | {summary}"]
    if created:
        lines.append("- Filed: " + ", ".join(f"[[{slug}]]" for slug in created))
    if updated:
        lines.append("- Updated: " + ", ".join(f"[[{slug}]]" for slug in updated))
    lines.append(f"- Cost: ${cost:.4f}")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

ROOT_DIR = Path(__file__).resolve().parent.parent


async def run_query(question: str, file_back: bool = False) -> str:
    """Query the knowledge base and optionally file the answer back."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    wiki_content = read_all_wiki_content()

    tools = ["Read", "Glob", "Grep"]
    if file_back:
        tools.extend(["Write", "Edit"])

    file_back_instructions = ""
    if file_back:
        file_back_instructions = f"""

## File Back Instructions

After answering, do the following:
1. Create a Q&A article at {QA_DIR}/ with the filename being a slugified version
   of the question (e.g., knowledge/qa/how-to-handle-auth-redirects.md)
2. Use the Q&A article format from the schema (frontmatter with title, question,
   consulted articles, filed date, and a `summary:` line ≤200 chars in neutral
   encyclopedic register; the runner uses this verbatim as the index row's Summary)
3. **Do NOT modify {KNOWLEDGE_DIR / 'index.md'} or {KNOWLEDGE_DIR / 'log.md'}**. The runner regenerates the index from per-article frontmatter and appends a structured log entry after success.
"""

    prompt = f"""You are a knowledge base query engine. Answer the user's question by
consulting the knowledge base below.

## How to Answer

1. Read the INDEX section first - it lists every article with a one-line summary
2. Identify 3-10 articles that are relevant to the question
3. Read those articles carefully (they're included below)
4. Synthesize a clear, thorough answer
5. Cite your sources using [[wikilinks]] (e.g., [[concepts/supabase-auth]])
6. If the knowledge base doesn't contain relevant information, say so honestly

## Knowledge Base

{wiki_content}

## Question

{question}
{file_back_instructions}"""

    answer = ""
    cost = 0.0
    snapshot_before = _snapshot_qa() if file_back else {}

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                system_prompt={"type": "preset", "preset": "claude_code"},
                allowed_tools=tools,
                permission_mode="acceptEdits",
                max_turns=15,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        answer += block.text
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
                print(f"Tokens: {format_token_usage(message.usage)}")
                print(f"Cost*:  ${cost:.4f}")
    except Exception as e:
        answer = f"Error querying knowledge base: {e}"

    # Update state
    state = load_state()
    state["query_count"] = state.get("query_count", 0) + 1
    state["total_cost"] = state.get("total_cost", 0.0) + cost
    save_state(state)

    if file_back:
        after = _snapshot_qa()
        created = sorted(p[:-3] for p in set(after) - set(snapshot_before))
        updated = sorted(p[:-3] for p in (set(after) & set(snapshot_before)) if after[p] > snapshot_before[p])
        rebuild_index()
        _append_query_log(now_iso(), question, created, updated, cost)

    return answer


def main():
    parser = argparse.ArgumentParser(description="Query the personal knowledge base")
    parser.add_argument("question", help="The question to ask")
    parser.add_argument(
        "--file-back",
        action="store_true",
        help="File the answer back into the knowledge base as a Q&A article",
    )
    args = parser.parse_args()

    print(f"Question: {args.question}")
    print(f"File back: {'yes' if args.file_back else 'no'}")
    print("-" * 60)

    answer = asyncio.run(run_query(args.question, file_back=args.file_back))
    print(answer)

    if args.file_back:
        print("\n" + "-" * 60)
        qa_count = len(list(QA_DIR.glob("*.md"))) if QA_DIR.exists() else 0
        print(f"Answer filed to knowledge/qa/ ({qa_count} Q&A articles total)")

    print(COST_DISCLAIMER)


if __name__ == "__main__":
    main()
