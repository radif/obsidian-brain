"""
One-shot migration: backfill `summary:` frontmatter on every wiki article.

Pre-summary articles store their one-line summary in `knowledge/index.md` rows
that have grown to encyclopedic length and pushed the file past the Claude
Agent SDK's 1 MiB per-message buffer. After the schema change that hands
index.md to the runner, every article needs a `summary:` field of its own
(≤200 chars). This script compresses each existing long index row into a
one-liner via Haiku 4.5 and writes it into the article's frontmatter.

Usage:
    uv run python scripts/backfill-summaries.py             # all articles missing summary
    uv run python scripts/backfill-summaries.py --limit 5   # only first 5 (smoke test)
    uv run python scripts/backfill-summaries.py --all       # re-process even articles that already have summary
    uv run python scripts/backfill-summaries.py --dry-run   # show what would happen, no LLM, no writes
"""

from __future__ import annotations

import os
os.environ["CLAUDE_INVOKED_BY"] = "backfill-summaries"

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from config import INDEX_FILE, KNOWLEDGE_DIR
from utils import (
    COST_DISCLAIMER,
    _parse_frontmatter,
    format_token_usage,
    list_wiki_articles,
    rebuild_index,
)

BATCH_SIZE = 20
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SUMMARY_MAX_CHARS = 200
BACKUP_FILE = INDEX_FILE.with_suffix(INDEX_FILE.suffix + ".pre-migration.bak")


_ROW_RE = re.compile(r"^\|\s*\[\[(?P<slug>[^\]]+)\]\]\s+\|\s*(?P<summary>.*?)\s+\|\s*(?P<sources>.*?)\s+\|\s*(?P<updated>[^|]*?)\s*\|\s*$")


def parse_index_rows(index_text: str) -> dict[str, str]:
    """Parse knowledge/index.md into a slug -> long-summary map.

    Splits cells on ` | ` rather than `|` so the regex doesn't mis-cut on
    piped-display wikilinks like `[[concepts/foo|Foo]]` that appear inside
    the summary prose.
    """
    rows: dict[str, str] = {}
    for line in index_text.splitlines():
        m = _ROW_RE.match(line)
        if not m:
            continue
        rows[m.group("slug")] = m.group("summary").strip()
    return rows


def article_slug(article: Path) -> str:
    return str(article.relative_to(KNOWLEDGE_DIR).with_suffix(""))


def has_summary(article: Path) -> bool:
    fm = _parse_frontmatter(article.read_text(encoding="utf-8"))
    if not fm:
        return False
    summary = fm.get("summary")
    return isinstance(summary, str) and bool(summary.strip())


def first_paragraph(article: Path) -> str:
    """Fallback when the article isn't in the existing index. Pulls the
    intro paragraph below the frontmatter and the H1."""
    text = article.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + 5:]
    text = text.lstrip()
    if text.startswith("# "):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    text = text.lstrip()
    para = text.split("\n\n", 1)[0]
    return " ".join(para.split())


def upsert_summary(text: str, summary: str) -> str:
    """Insert or replace the `summary:` line in the article's frontmatter.

    Idempotent: an existing summary line gets overwritten. When inserting,
    placement is immediately after the `title:` line so the field order
    matches AGENTS.md (title, summary, ...). Returns the original text
    unchanged if the file has no parseable frontmatter."""
    if not text.startswith("---\n"):
        return text
    end_idx = text.find("\n---\n", 4)
    if end_idx == -1:
        return text
    fm_block = text[4:end_idx]
    rest = text[end_idx:]

    escaped = summary.replace("\\", "\\\\").replace('"', '\\"')
    new_line = f'summary: "{escaped}"'

    lines = fm_block.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("summary:"):
            lines[i] = new_line
            return "---\n" + "\n".join(lines) + rest

    out_lines: list[str] = []
    inserted = False
    for line in lines:
        out_lines.append(line)
        if not inserted and line.startswith("title:"):
            out_lines.append(new_line)
            inserted = True
    if not inserted:
        out_lines.insert(0, new_line)
    return "---\n" + "\n".join(out_lines) + rest


def build_batch_prompt(items: list[tuple[str, str]]) -> str:
    """items: list of (slug, long_summary) tuples."""
    article_blocks = "\n\n".join(f"### {slug}\n{long}" for slug, long in items)
    return f"""You compress long encyclopedic summaries into one-line summaries (max {SUMMARY_MAX_CHARS} characters each) for a knowledge-base index.

Rules:
1. Preserve load-bearing entities, dates, numbers, proper nouns, and any verbatim quoted strings that appear inside the long summary.
2. Neutral encyclopedic register. No marketing language, no superlatives.
3. Hard cap {SUMMARY_MAX_CHARS} characters. If you can express the core fact more tightly, prefer the shorter form.
4. For Russian-language content, keep the summary in Russian. For mixed-language content, prefer English with key Russian terms preserved.
5. Output ONLY a JSON object mapping each article slug exactly as provided to its compressed summary string. No prose, no preamble, no trailing commentary, no code fences.

Articles to compress:

{article_blocks}

Output the JSON object now."""


def extract_json(text: str) -> dict[str, str]:
    """Pull the first {...} block out of the model's response and json.loads it.
    Tolerates ```json fences and surrounding prose."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in response")
        candidate = text[start : end + 1]
    return json.loads(candidate)


async def compress_batch(items: list[tuple[str, str]]) -> tuple[dict[str, str], float]:
    """Run one Haiku call on a batch. Returns (slug -> compressed, cost_usd)."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    prompt = build_batch_prompt(items)
    response_text = ""
    cost = 0.0

    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            model=HAIKU_MODEL,
            system_prompt={"type": "preset", "preset": "claude_code"},
            allowed_tools=[],
            permission_mode="default",
            max_turns=2,
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    response_text += block.text
        elif isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0
            print(f"  Tokens: {format_token_usage(message.usage)}")
            print(f"  Cost*:  ${cost:.4f}")

    try:
        parsed = extract_json(response_text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  Parse error: {e}")
        print(f"  Response preview: {response_text[:400]}")
        return {}, cost

    cleaned: dict[str, str] = {}
    for slug, summary in parsed.items():
        if not isinstance(summary, str):
            continue
        s = " ".join(summary.split()).strip()
        if len(s) > SUMMARY_MAX_CHARS:
            s = s[:SUMMARY_MAX_CHARS].rstrip()
        cleaned[slug] = s
    return cleaned, cost


def chunk(seq: list, size: int) -> list[list]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


async def main_async(args: argparse.Namespace) -> int:
    articles = list_wiki_articles()
    targets: list[Path] = []
    for article in articles:
        if args.all or not has_summary(article):
            targets.append(article)

    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("Nothing to backfill: every article already has a non-empty summary.")
        return 0

    source_file = BACKUP_FILE if BACKUP_FILE.exists() else INDEX_FILE
    if BACKUP_FILE.exists():
        print(f"Reading long-form summaries from {BACKUP_FILE.name} (re-runnable source).")
    existing_rows = parse_index_rows(source_file.read_text(encoding="utf-8")) if source_file.exists() else {}

    items: list[tuple[str, str, Path]] = []
    for article in targets:
        slug = article_slug(article)
        long = existing_rows.get(slug, "").strip()
        if not long:
            long = first_paragraph(article)
        if not long:
            long = "(no existing summary or intro paragraph available)"
        items.append((slug, long, article))

    print(f"Targets: {len(items)} article(s) missing summary (or --all set).")
    if args.dry_run:
        for slug, long, _ in items[:10]:
            preview = (long[:120] + "...") if len(long) > 120 else long
            print(f"  - {slug}\n      {preview}")
        if len(items) > 10:
            print(f"  ... and {len(items) - 10} more")
        return 0

    if INDEX_FILE.exists() and not BACKUP_FILE.exists():
        BACKUP_FILE.write_bytes(INDEX_FILE.read_bytes())
        print(f"Backup written: {BACKUP_FILE}")
    elif BACKUP_FILE.exists():
        print(f"Backup already exists, not overwriting: {BACKUP_FILE}")

    batches = chunk(items, BATCH_SIZE)
    total_cost = 0.0
    written = 0
    failed_slugs: list[str] = []

    for i, batch in enumerate(batches, 1):
        print(f"\n[{i}/{len(batches)}] Compressing {len(batch)} articles via {HAIKU_MODEL}...")
        batch_input = [(slug, long) for slug, long, _ in batch]
        result, cost = await compress_batch(batch_input)
        total_cost += cost

        slug_to_path = {slug: path for slug, _, path in batch}
        for slug, _, path in batch:
            new_summary = result.get(slug)
            if not new_summary:
                failed_slugs.append(slug)
                continue
            original = path.read_text(encoding="utf-8")
            updated = upsert_summary(original, new_summary)
            if updated != original:
                path.write_text(updated, encoding="utf-8")
                written += 1

    print(f"\nDone. Wrote summaries to {written} article(s). Total cost*: ${total_cost:.4f}")
    if failed_slugs:
        print(f"\n{len(failed_slugs)} article(s) did not receive a summary:")
        for slug in failed_slugs[:20]:
            print(f"  - {slug}")
        if len(failed_slugs) > 20:
            print(f"  ... and {len(failed_slugs) - 20} more")

    print("\nRegenerating index.md from updated frontmatter...")
    rebuild_index()
    new_size = INDEX_FILE.stat().st_size
    print(f"index.md is now {new_size:,} bytes ({new_size / 1024:.1f} KB).")

    print(COST_DISCLAIMER)
    return 0 if not failed_slugs else 1


def main():
    parser = argparse.ArgumentParser(description="Backfill summary: frontmatter on existing wiki articles")
    parser.add_argument("--all", action="store_true", help="Re-process every article, even those with an existing summary")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N articles (for smoke testing)")
    parser.add_argument("--dry-run", action="store_true", help="List targets and inputs without calling the LLM")
    args = parser.parse_args()

    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
