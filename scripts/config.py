"""Path constants and configuration for the personal knowledge base."""

from pathlib import Path
from datetime import datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent

# Raw source layer. Any immediate subdirectory of RAW_DIR is treated as a
# source bucket and scanned for *.md files by list_raw_files() in utils.py.
# New source types (meetings/, pdfs/, etc.) can be added with `mkdir raw/<name>`
# — no code changes required.
RAW_DIR = ROOT_DIR / "raw"
DAILY_DIR = RAW_DIR / "daily"            # conversation logs written by flush.py
CLIPPINGS_DIR = RAW_DIR / "clippings"    # Obsidian Web Clipper output
RESEARCH_DIR = RAW_DIR / "research"      # long-form notes, papers, investigation

# Compiled knowledge layer (LLM-owned).
KNOWLEDGE_DIR = ROOT_DIR / "knowledge"
CONCEPTS_DIR = KNOWLEDGE_DIR / "concepts"
CONNECTIONS_DIR = KNOWLEDGE_DIR / "connections"
QA_DIR = KNOWLEDGE_DIR / "qa"

REPORTS_DIR = ROOT_DIR / "reports"
SCRIPTS_DIR = ROOT_DIR / "scripts"
HOOKS_DIR = ROOT_DIR / "hooks"
AGENTS_FILE = ROOT_DIR / "AGENTS.md"

INDEX_FILE = KNOWLEDGE_DIR / "index.md"
LOG_FILE = KNOWLEDGE_DIR / "log.md"
STATE_FILE = SCRIPTS_DIR / "state.json"

# ── Timezone ───────────────────────────────────────────────────────────
TIMEZONE = "America/Chicago"


def now_iso() -> str:
    """Current time in ISO 8601 format."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    """Current date in ISO 8601 format."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
