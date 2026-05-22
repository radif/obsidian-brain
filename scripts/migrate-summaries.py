"""
One-shot structural migration: copy each `knowledge/index.md` row's Summary
cell into the matching article's `summary:` frontmatter.

Use on smaller projects where index summaries are already short and don't need
LLM compression. No API calls, no cost. Idempotent (re-running skips articles
that already have a summary).

Delete this file (and `backfill-summaries.py`) once every project has been
migrated.

Usage: uv run python scripts/migrate-summaries.py
"""

from __future__ import annotations

import os
os.environ["CLAUDE_INVOKED_BY"] = "migrate-summaries"

import re
import sys
from pathlib import Path

from config import INDEX_FILE, KNOWLEDGE_DIR
from utils import _parse_frontmatter, list_wiki_articles, rebuild_index

SUMMARY_MAX_CHARS = 200
BACKUP_FILE = INDEX_FILE.parent / (INDEX_FILE.name + ".pre-migration.bak")

_ROW_RE = re.compile(
    r"^\|\s*\[\[(?P<slug>[^\]]+)\]\]\s+\|\s*(?P<summary>.*?)\s+\|\s*(?P<sources>.*?)\s+\|\s*(?P<updated>[^|]*?)\s*\|\s*$"
)


def parse_index_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m:
            rows[m.group("slug")] = m.group("summary").strip()
    return rows


def has_summary(article: Path) -> bool:
    fm = _parse_frontmatter(article.read_text(encoding="utf-8"))
    if not fm:
        return False
    s = fm.get("summary")
    return isinstance(s, str) and bool(s.strip())


def upsert_summary(text: str, summary: str) -> str:
    """Insert summary: after title: in the YAML frontmatter, or replace it
    if already present. Returns text unchanged when no frontmatter is found."""
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


def main() -> int:
    if not INDEX_FILE.exists():
        print(f"Error: {INDEX_FILE} not found. Nothing to migrate from.")
        return 1

    if not BACKUP_FILE.exists():
        BACKUP_FILE.write_bytes(INDEX_FILE.read_bytes())
        print(f"Backup written: {BACKUP_FILE}")
    else:
        print(f"Backup already exists, not overwriting: {BACKUP_FILE}")

    source_file = BACKUP_FILE
    rows = parse_index_rows(source_file.read_text(encoding="utf-8"))
    print(f"Parsed {len(rows)} row(s) from {source_file.name}.")

    written = 0
    already = 0
    oversized: list[tuple[str, int]] = []
    orphans: list[str] = []

    for article in list_wiki_articles():
        slug = str(article.relative_to(KNOWLEDGE_DIR).with_suffix(""))
        if has_summary(article):
            already += 1
            continue
        summary = rows.get(slug, "").strip()
        if not summary:
            orphans.append(slug)
            continue
        if len(summary) > SUMMARY_MAX_CHARS:
            oversized.append((slug, len(summary)))
        original = article.read_text(encoding="utf-8")
        updated = upsert_summary(original, summary)
        if updated != original:
            article.write_text(updated, encoding="utf-8")
            written += 1

    print(f"\nWrote summaries to {written} article(s).")
    print(f"Skipped {already} article(s) that already had a summary.")

    if oversized:
        print(f"\n{len(oversized)} article(s) have summary > {SUMMARY_MAX_CHARS} chars (written verbatim, please trim by hand):")
        for slug, n in oversized:
            print(f"  - {slug} ({n} chars)")

    if orphans:
        print(f"\n{len(orphans)} article(s) have no matching index row (no summary written):")
        for slug in orphans:
            print(f"  - {slug}")

    print("\nRegenerating index.md from updated frontmatter...")
    rebuild_index()
    new_size = INDEX_FILE.stat().st_size
    print(f"index.md is now {new_size:,} bytes ({new_size / 1024:.1f} KB).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
