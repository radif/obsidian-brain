"""Shared utilities for the personal knowledge base."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from config import (
    CONCEPTS_DIR,
    CONNECTIONS_DIR,
    INDEX_FILE,
    KNOWLEDGE_DIR,
    LOG_FILE,
    QA_DIR,
    RAW_DIR,
    STATE_FILE,
)

# Subdirectories under raw/ that should not be scanned for source markdown
# (e.g. assets/ is where image attachments live).
_RAW_SKIP_DIRS = {"assets"}


# ── State management ──────────────────────────────────────────────────

def load_state() -> dict:
    """Load persistent state from state.json."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"ingested": {}, "query_count": 0, "last_lint": None, "total_cost": 0.0}


def save_state(state: dict) -> None:
    """Save state to state.json."""
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── File hashing ──────────────────────────────────────────────────────

def file_hash(path: Path) -> str:
    """SHA-256 hash of a file (first 16 hex chars)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ── Token usage formatting ────────────────────────────────────────────

def format_token_usage(message_usage: dict | None) -> str:
    """Format a ResultMessage.usage dict for human display.

    Returns a string like "10,000 in, 500 out, 45,000 cache read".
    Cache fields are omitted when zero.
    """
    u = message_usage or {}
    parts = [
        f"{u.get('input_tokens', 0):,} in",
        f"{u.get('output_tokens', 0):,} out",
    ]
    cache_read = u.get('cache_read_input_tokens', 0)
    if cache_read:
        parts.append(f"{cache_read:,} cache read")
    cache_create = u.get('cache_creation_input_tokens', 0)
    if cache_create:
        parts.append(f"{cache_create:,} cache write")
    return ", ".join(parts)


# Shown after every cost display; cost figures are API pricing only.
COST_DISCLAIMER = (
    "* Cost reflects API pricing. No per-call charge if you use Claude Code via a "
    "Claude subscription (Max, Team, Enterprise)."
)


# ── Slug / naming ─────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


# ── Wikilink helpers ──────────────────────────────────────────────────

def extract_wikilinks(content: str) -> list[str]:
    """Extract all [[wikilinks]] from markdown content."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def wiki_article_exists(link: str) -> bool:
    """Check if a wikilinked article exists on disk."""
    path = KNOWLEDGE_DIR / f"{link}.md"
    return path.exists()


# ── Wiki content helpers ──────────────────────────────────────────────

def read_wiki_index() -> str:
    """Read the knowledge base index file."""
    if INDEX_FILE.exists():
        return INDEX_FILE.read_text(encoding="utf-8")
    return "# Knowledge Base Index\n\n| Article | Summary | Compiled From | Updated |\n|---------|---------|---------------|---------|"


def read_all_wiki_content() -> str:
    """Read index + all wiki articles into a single string for context."""
    parts = [f"## INDEX\n\n{read_wiki_index()}"]

    for subdir in [CONCEPTS_DIR, CONNECTIONS_DIR, QA_DIR]:
        if not subdir.exists():
            continue
        for md_file in sorted(subdir.glob("*.md")):
            rel = md_file.relative_to(KNOWLEDGE_DIR)
            content = md_file.read_text(encoding="utf-8")
            parts.append(f"## {rel}\n\n{content}")

    return "\n\n---\n\n".join(parts)


def list_wiki_articles() -> list[Path]:
    """List all wiki article files."""
    articles = []
    for subdir in [CONCEPTS_DIR, CONNECTIONS_DIR, QA_DIR]:
        if subdir.exists():
            articles.extend(sorted(subdir.glob("*.md")))
    return articles


def list_raw_files() -> list[Path]:
    """List every raw source markdown file across all buckets under raw/.

    A bucket is any immediate subdirectory of raw/ whose name isn't in
    _RAW_SKIP_DIRS. Each bucket is scanned *recursively* so buckets can
    organize their contents with sub-folders (e.g. raw/research/<topic>/).
    Any directory whose name is in _RAW_SKIP_DIRS is pruned at any depth,
    so attachment folders like raw/clippings/assets/ stay out of the queue.
    """
    if not RAW_DIR.exists():
        return []
    files: list[Path] = []
    for bucket in sorted(RAW_DIR.iterdir()):
        if not bucket.is_dir() or bucket.name in _RAW_SKIP_DIRS:
            continue
        for md in sorted(bucket.rglob("*.md")):
            rel_parts = md.relative_to(bucket).parts
            if any(part in _RAW_SKIP_DIRS for part in rel_parts):
                continue
            files.append(md)
    return files


# ── Index helpers ─────────────────────────────────────────────────────

def count_inbound_links(target: str, exclude_file: Path | None = None) -> int:
    """Count how many wiki articles link to a given target."""
    count = 0
    for article in list_wiki_articles():
        if article == exclude_file:
            continue
        content = article.read_text(encoding="utf-8")
        if f"[[{target}]]" in content:
            count += 1
    return count


def get_article_word_count(path: Path) -> int:
    """Count words in an article, excluding YAML frontmatter."""
    content = path.read_text(encoding="utf-8")
    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:]
    return len(content.split())


def build_index_entry(rel_path: str, summary: str, sources: str, updated: str) -> str:
    """Build a single index table row."""
    link = rel_path.replace(".md", "")
    return f"| [[{link}]] | {summary} | {sources} | {updated} |"
