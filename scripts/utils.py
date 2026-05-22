"""Shared utilities for the personal knowledge base."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from config import (
    CONCEPTS_DIR,
    CONNECTIONS_DIR,
    CONTENT_DIR,
    INDEX_FILE,
    KNOWLEDGE_DIR,
    LOG_FILE,
    QA_DIR,
    RAW_DIR,
    STATE_FILE,
)

# Subdirectories under raw/ that should not be scanned for source markdown
# (e.g. assets/ is where image attachments live). Content repos can extend
# this set with a `<content-repo>/project/raw-skip.txt` file — one directory
# name per line, `#` comments allowed. Lets a content repo carry project-
# specific skips (e.g. a vendored corpus) without modifying this file.
_RAW_SKIP_DIRS = {"assets"}

_PROJECT_SKIP_FILE = CONTENT_DIR / "project" / "raw-skip.txt"
if _PROJECT_SKIP_FILE.is_file():
    for _ln in _PROJECT_SKIP_FILE.read_text(encoding="utf-8").splitlines():
        _ln = _ln.strip()
        if _ln and not _ln.startswith("#"):
            _RAW_SKIP_DIRS.add(_ln)


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


def _parse_frontmatter(text: str) -> dict | None:
    """Extract the YAML frontmatter block from a markdown file. Returns None
    when there's no frontmatter or it's malformed."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def rebuild_index() -> None:
    """Regenerate knowledge/index.md from every article's frontmatter.

    The runner calls this after a successful compile or file-back query.
    Sub-agents must NOT touch index.md. Keeping the runner as the sole
    writer means row count and per-row width are both bounded by
    frontmatter (summary capped at 200 chars per AGENTS.md), so the
    rebuilt index stays well under the Claude Agent SDK's 1 MiB
    per-message buffer.

    Article order matches list_wiki_articles(): concepts/, connections/,
    qa/, alphabetical within each. Articles with no parseable frontmatter
    are skipped silently (lint catches them separately).
    """
    rows: list[str] = []
    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR).with_suffix("")
        fm = _parse_frontmatter(article.read_text(encoding="utf-8"))
        if fm is None:
            continue
        summary = (
            str(fm.get("summary") or "").replace("|", "\\|").replace("\n", " ").strip()
        )
        sources = fm.get("sources") or []
        if isinstance(sources, list):
            sources_cell = ", ".join(str(s) for s in sources)
        else:
            sources_cell = str(sources)
        sources_cell = sources_cell.replace("|", "\\|").replace("\n", " ").strip()
        updated = str(fm.get("updated") or "").strip()
        rows.append(f"| [[{rel}]] | {summary} | {sources_cell} | {updated} |")

    body = (
        "# Knowledge Base Index\n\n"
        "| Article | Summary | Compiled From | Updated |\n"
        "|---------|---------|---------------|---------|\n"
        + "\n".join(rows)
        + "\n"
    )
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(body, encoding="utf-8")


def list_raw_files() -> list[Path]:
    """List every raw source markdown file across all buckets under raw/.

    A bucket is any immediate subdirectory of raw/ whose name isn't in
    _RAW_SKIP_DIRS. Each bucket is scanned *recursively* so buckets can
    organize their contents with sub-folders (e.g. raw/research/<topic>/).
    Any directory whose name is in _RAW_SKIP_DIRS is pruned at any depth,
    so attachment folders like raw/clippings/assets/ stay out of the queue.

    Files with byte-identical content are deduplicated: the first occurrence
    (by sorted bucket then sorted recursive path) is kept, later duplicates
    are dropped. This lets the same transcript live in `raw/transcripts/`
    *and* be co-located with its webinar in `raw/webinars/<year>/<event>/`
    without compile ingesting it twice.
    """
    if not RAW_DIR.exists():
        return []
    files: list[Path] = []
    seen_hashes: set[str] = set()
    for bucket in sorted(RAW_DIR.iterdir()):
        if not bucket.is_dir() or bucket.name in _RAW_SKIP_DIRS:
            continue
        for md in sorted(bucket.rglob("*.md")):
            rel_parts = md.relative_to(bucket).parts
            if any(part in _RAW_SKIP_DIRS for part in rel_parts):
                continue
            h = file_hash(md)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
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
