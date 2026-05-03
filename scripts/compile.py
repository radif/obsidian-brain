"""
Compile raw source documents into structured knowledge articles.

This is the "LLM compiler" - it reads raw sources (the source code layer,
e.g. conversation logs in raw/daily/ and web clippings in raw/clippings/)
and produces organized knowledge articles (the executable layer).

Usage:
    uv run python compile.py                          # compile new/changed sources only
    uv run python compile.py --all                    # force recompile everything
    uv run python compile.py --file raw/daily/2026-04-01.md  # compile a specific source
    uv run python compile.py --dry-run                # show what would be compiled
"""

from __future__ import annotations

# Hook recursion guard: tells the hooks in .claude/settings.json to no-op
# inside the Claude Code subprocess that the Agent SDK will spawn below.
# Must be set BEFORE any imports that might invoke the SDK.
import os
os.environ["CLAUDE_INVOKED_BY"] = "compile"

import argparse
import asyncio
import sys
from pathlib import Path

from config import AGENTS_FILE, CONCEPTS_DIR, CONNECTIONS_DIR, KNOWLEDGE_DIR, RAW_DIR, now_iso
from utils import (
    COST_DISCLAIMER,
    file_hash,
    format_token_usage,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_wiki_index,
    save_state,
)

# ── Paths for the LLM to use ──────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent


async def compile_source(source_path: Path, state: dict) -> float:
    """Compile a single raw source document into knowledge articles.

    Returns the API cost of the compilation.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    source_content = source_path.read_text(encoding="utf-8")
    source_rel = source_path.relative_to(ROOT_DIR)
    source_bucket = source_rel.parts[1] if len(source_rel.parts) >= 2 else "unknown"
    schema = AGENTS_FILE.read_text(encoding="utf-8")
    wiki_index = read_wiki_index()

    # Read existing articles for context
    existing_articles_context = ""
    existing = {}
    for article_path in list_wiki_articles():
        rel = article_path.relative_to(KNOWLEDGE_DIR)
        existing[str(rel)] = article_path.read_text(encoding="utf-8")

    if existing:
        parts = []
        for rel_path, content in existing.items():
            parts.append(f"### {rel_path}\n```markdown\n{content}\n```")
        existing_articles_context = "\n\n".join(parts)

    timestamp = now_iso()

    prompt = f"""You are a knowledge compiler. Your job is to read a raw source document
and extract knowledge into structured wiki articles.

## Schema (AGENTS.md)

{schema}

## Current Wiki Index

{wiki_index}

## Existing Wiki Articles

{existing_articles_context if existing_articles_context else "(No existing articles yet)"}

## Raw Source to Compile

**Path:** {source_rel}
**Bucket:** {source_bucket}

{source_content}

## Your Task

Read the raw source above and compile it into wiki articles following the schema exactly.

### Rules:

1. **Extract key concepts** - Identify 3-7 distinct concepts worth their own article
2. **Create concept articles** in `knowledge/concepts/` - One .md file per concept
   - Use the exact article format from AGENTS.md (YAML frontmatter + sections)
   - Include `sources:` in frontmatter pointing to the raw source file (path relative to repo root, e.g. `raw/daily/2026-04-01.md`)
   - Use `[[concepts/slug]]` wikilinks to link to related concepts
   - Write in encyclopedia style - neutral, comprehensive
3. **Create connection articles** in `knowledge/connections/` if this source reveals non-obvious
   relationships between 2+ existing concepts
4. **Update existing articles** if this source adds new information to concepts already in the wiki
   - Read the existing article, add the new information, add the source to frontmatter
5. **Update knowledge/index.md** - Add new entries to the table
   - Each entry: `| [[path/slug]] | One-line summary | source-file | {timestamp[:10]} |`
6. **Append to knowledge/log.md** - Add a timestamped entry:
   ```
   ## [{timestamp}] compile | {source_rel}
   - Source: {source_rel}
   - Articles created: [[concepts/x]], [[concepts/y]]
   - Articles updated: [[concepts/z]] (if any)
   ```

### File paths:
- Write concept articles to: {CONCEPTS_DIR}
- Write connection articles to: {CONNECTIONS_DIR}
- Update index at: {KNOWLEDGE_DIR / 'index.md'}
- Append log at: {KNOWLEDGE_DIR / 'log.md'}

### Quality standards:
- Every article must have complete YAML frontmatter
- Every article must link to at least 2 other articles via [[wikilinks]]
- Key Points section should have 3-5 bullet points
- Details section should have 2+ paragraphs
- Related Concepts section should have 2+ entries
- Sources section should cite the daily log with specific claims extracted
"""

    cost = 0.0
    got_result = False

    def on_stderr(line: str) -> None:
        # Surface bundled-CLI stderr so spurious post-compile exit-1 errors
        # become diagnosable instead of disappearing into the void.
        print(f"  [cli stderr] {line}")

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                system_prompt={"type": "preset", "preset": "claude_code"},
                allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
                permission_mode="acceptEdits",
                max_turns=30,
                stderr=on_stderr,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        pass  # compilation output - LLM writes files directly
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
                got_result = True
                print(f"  Tokens: {format_token_usage(message.usage)}")
                print(f"  Cost*:  ${cost:.4f}")
    except Exception as e:
        print(f"  Error: {e}")
        # Fall through to state save when the model already returned a
        # ResultMessage — the work was billed, articles were written, and
        # we don't want to re-bill on the next run. The bundled Claude
        # Code CLI sometimes exits 1 in cleanup after a successful query.
        if not got_result:
            return 0.0

    # Update state. Key is the path relative to the repo root so different
    # buckets (raw/daily/foo.md vs raw/clippings/foo.md) can't collide.
    rel_key = str(source_path.relative_to(ROOT_DIR))
    state.setdefault("ingested", {})[rel_key] = {
        "hash": file_hash(source_path),
        "compiled_at": now_iso(),
        "cost_usd": cost,
    }
    state["total_cost"] = state.get("total_cost", 0.0) + cost
    save_state(state)

    return cost


def main():
    parser = argparse.ArgumentParser(description="Compile raw sources into knowledge articles")
    parser.add_argument("--all", action="store_true", help="Force recompile all sources")
    parser.add_argument("--file", type=str, help="Compile a specific raw source file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be compiled")
    args = parser.parse_args()

    state = load_state()

    # Determine which files to compile
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            # Try relative to repo root first (e.g. "raw/daily/2026-04-01.md")
            candidate = ROOT_DIR / args.file
            if candidate.exists():
                target = candidate
            else:
                # Fallback: assume it's a daily log and resolve by bare name
                target = RAW_DIR / "daily" / target.name
        if not target.exists():
            print(f"Error: {args.file} not found")
            sys.exit(1)
        to_compile = [target]
    else:
        all_sources = list_raw_files()
        if args.all:
            to_compile = all_sources
        else:
            to_compile = []
            for source_path in all_sources:
                rel_key = str(source_path.relative_to(ROOT_DIR))
                prev = state.get("ingested", {}).get(rel_key, {})
                if not prev or prev.get("hash") != file_hash(source_path):
                    to_compile.append(source_path)

    if not to_compile:
        print("Nothing to compile - all raw sources are up to date.")
        return

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Files to compile ({len(to_compile)}):")
    for f in to_compile:
        print(f"  - {f.relative_to(ROOT_DIR)}")

    if args.dry_run:
        return

    # Compile each file sequentially
    total_cost = 0.0
    for i, source_path in enumerate(to_compile, 1):
        print(f"\n[{i}/{len(to_compile)}] Compiling {source_path.relative_to(ROOT_DIR)}...")
        cost = asyncio.run(compile_source(source_path, state))
        total_cost += cost
        print(f"  Done.")

    articles = list_wiki_articles()
    print(f"\nCompilation complete. Total cost*: ${total_cost:.2f}")
    print(f"Knowledge base: {len(articles)} articles")
    print(COST_DISCLAIMER)


if __name__ == "__main__":
    main()
