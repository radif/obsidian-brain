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

from config import AGENTS_FILE, CONCEPTS_DIR, CONNECTIONS_DIR, KNOWLEDGE_DIR, LOG_FILE, QA_DIR, RAW_DIR, now_iso
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

# Switching point between inline and lookup modes when --mode=auto. If total
# bytes of existing wiki articles is below this, the agent receives every
# article body inline (fast, more grounding for small KBs); above, it gets only
# the index and reads bodies on demand (scales past ~150+ articles where inline
# starts exhausting max_turns).
INLINE_BYTES_THRESHOLD = 500_000


def _snapshot_articles() -> dict[str, float]:
    """Map relative-to-knowledge paths to mtimes for every article the sub-agent
    might create or edit. Used to compute the post-compile log entry without
    asking the sub-agent to write to log.md (which would echo the full file via
    tool_use_result on every edit, blowing the SDK's 1 MiB per-message buffer
    once log.md grows past ~960 KB)."""
    snapshot: dict[str, float] = {}
    for sub in (CONCEPTS_DIR, CONNECTIONS_DIR, QA_DIR):
        if not sub.exists():
            continue
        for p in sub.rglob("*.md"):
            snapshot[str(p.relative_to(KNOWLEDGE_DIR))] = p.stat().st_mtime
    return snapshot


def _diff_articles(before: dict[str, float], after: dict[str, float]) -> tuple[list[str], list[str]]:
    """Return (created, updated) lists of slugs (path without the .md suffix) in
    deterministic order."""
    created = sorted(p[:-3] for p in set(after) - set(before))
    updated = sorted(p[:-3] for p in (set(after) & set(before)) if after[p] > before[p])
    return created, updated


def _append_log_entry(
    timestamp: str,
    source_rel: Path,
    created: list[str],
    updated: list[str],
    cost: float,
) -> None:
    """Append one structured entry to knowledge/log.md. The runner owns this
    file; the compile sub-agent must not touch it."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.write_text("# Build Log\n", encoding="utf-8")

    lines = [f"\n## [{timestamp}] compile | {source_rel}"]
    if created:
        lines.append("- Created: " + ", ".join(f"[[{slug}]]" for slug in created))
    if updated:
        lines.append("- Updated: " + ", ".join(f"[[{slug}]]" for slug in updated))
    if not created and not updated:
        lines.append("- (no article changes)")
    lines.append(f"- Cost: ${cost:.4f}")

    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def build_articles_context(mode: str) -> tuple[str, str, int]:
    """Build the existing-articles section of the compile prompt.

    Returns ``(text, resolved_mode, total_bytes)``. If ``mode == "auto"``,
    resolves to ``"inline"`` when total wiki bytes < ``INLINE_BYTES_THRESHOLD``,
    else ``"lookup"``.
    """
    articles = list_wiki_articles()
    total_bytes = sum(p.stat().st_size for p in articles)
    if mode == "auto":
        mode = "inline" if total_bytes < INLINE_BYTES_THRESHOLD else "lookup"
    if not articles:
        return "(No existing articles yet)", mode, 0
    if mode == "inline":
        parts = [
            f"### {p.relative_to(KNOWLEDGE_DIR)}\n```markdown\n{p.read_text(encoding='utf-8')}\n```"
            for p in articles
        ]
        return "\n\n".join(parts), mode, total_bytes
    return (
        "(Article bodies are NOT included below — only their summaries via the index above. "
        "Use the Read tool on `knowledge/concepts/<slug>.md`, `knowledge/connections/<slug>.md`, "
        "or `knowledge/qa/<slug>.md` to fetch any article body you need to update or reference.)",
        mode,
        total_bytes,
    )


async def compile_source(source_path: Path, state: dict, mode: str) -> float:
    """Compile a single raw source document into knowledge articles.

    Returns the API cost of the compilation. ``mode`` is one of ``"auto"``,
    ``"inline"``, or ``"lookup"`` and controls whether existing article bodies
    are inlined into the prompt or fetched on demand by the agent via Read.
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
    existing_articles_context, resolved_mode, _ = build_articles_context(mode)
    snapshot_before = _snapshot_articles()
    task_preamble = ""
    if resolved_mode == "lookup":
        task_preamble = (
            "**Lookup mode**: existing article bodies are NOT inlined. Before writing "
            "or updating anything, identify which existing articles this source may "
            "relate to (by slug from the index), then use the Read tool to fetch each "
            "one. Only after Reading the articles you intend to touch should you "
            "proceed with creating, updating, or cross-linking.\n\n"
        )

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

{task_preamble}Read the raw source above and compile it into wiki articles following the schema exactly.

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

### File paths:
- Write concept articles to: {CONCEPTS_DIR}
- Write connection articles to: {CONNECTIONS_DIR}
- Update index at: {KNOWLEDGE_DIR / 'index.md'}
- **Do NOT modify {KNOWLEDGE_DIR / 'log.md'}** — the runner appends a structured entry after success.

### Quality standards:
- Every article must have complete YAML frontmatter
- Every article must link to at least 2 other articles via [[wikilinks]]
- Key Points section should have 3-5 bullet points
- Details section should have 2+ paragraphs
- Related Concepts section should have 2+ entries
- Sources section should cite the daily log with specific claims extracted
"""

    cost = 0.0
    succeeded = False

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
                succeeded = not message.is_error
                print(f"  Tokens: {format_token_usage(message.usage)}")
                print(f"  Cost*:  ${cost:.4f}")
                if message.is_error:
                    print(f"  Result was an error (subtype={message.subtype}); not marking compiled.")
    except Exception as e:
        print(f"  Error: {e}")
        # Fall through to state save when the model already returned a
        # successful ResultMessage — the work was billed, articles were
        # written, and we don't want to re-bill on the next run. The
        # bundled Claude Code CLI sometimes exits 1 in cleanup after a
        # successful query. An is_error ResultMessage (rate limit,
        # out-of-credits, max-turns) does NOT count as success.
        if not succeeded:
            return 0.0

    if not succeeded:
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

    created, updated = _diff_articles(snapshot_before, _snapshot_articles())
    _append_log_entry(now_iso(), source_rel, created, updated, cost)

    return cost


def main():
    parser = argparse.ArgumentParser(description="Compile raw sources into knowledge articles")
    parser.add_argument("--all", action="store_true", help="Force recompile all sources")
    parser.add_argument("--file", type=str, help="Compile a specific raw source file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be compiled")
    parser.add_argument(
        "--mode",
        choices=["auto", "inline", "lookup"],
        default="auto",
        help=(
            "How existing wiki articles are presented to the compiler agent. "
            "auto (default): inline if total wiki bytes < %d, else lookup. "
            "inline: every article body included in the prompt — best grounding, "
            "doesn't scale past ~150 articles. "
            "lookup: only the index goes into the prompt; the agent reads bodies "
            "on demand via the Read tool — scales linearly with what each compile "
            "actually needs." % INLINE_BYTES_THRESHOLD
        ),
    )
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

    # Report mode resolution against current wiki size. The actual mode used per
    # file is re-resolved inside compile_source (so an --mode=auto run that
    # crosses the threshold mid-batch flips correctly), but reporting once here
    # gives the user advance notice of the cost profile.
    articles_now = list_wiki_articles()
    total_bytes_now = sum(p.stat().st_size for p in articles_now)
    threshold_kb = INLINE_BYTES_THRESHOLD // 1000
    wiki_kb = total_bytes_now / 1000
    if args.mode == "auto":
        if total_bytes_now < INLINE_BYTES_THRESHOLD:
            will_be = "inline"
            comparison = f"{wiki_kb:.0f} KB < {threshold_kb} KB threshold"
        else:
            will_be = "lookup"
            comparison = f"{wiki_kb:.0f} KB ≥ {threshold_kb} KB threshold"
        print(
            f"\nCompile mode: {will_be} "
            f"(auto-selected — wiki {comparison}, {len(articles_now)} articles)"
        )
    else:
        print(
            f"\nCompile mode: {args.mode} "
            f"(forced via --mode — wiki {wiki_kb:.0f} KB, {len(articles_now)} articles)"
        )

    if args.dry_run:
        return

    # Compile each file sequentially
    total_cost = 0.0
    for i, source_path in enumerate(to_compile, 1):
        print(f"\n[{i}/{len(to_compile)}] Compiling {source_path.relative_to(ROOT_DIR)}...")
        cost = asyncio.run(compile_source(source_path, state, args.mode))
        total_cost += cost
        print(f"  Done.")

    articles = list_wiki_articles()
    print(f"\nCompilation complete. Total cost*: ${total_cost:.2f}")
    print(f"Knowledge base: {len(articles)} articles")
    print(COST_DISCLAIMER)


if __name__ == "__main__":
    main()
