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

# Content directory: holds raw/, knowledge/, notes/, and the compile state.
# In linked mode this resolves through the symlink to the content repo root;
# in solo mode it equals ROOT_DIR. The compile state lives here (not under
# scripts/) so it travels with the content repo and stays in sync across
# machines.
CONTENT_DIR = RAW_DIR.resolve().parent

INDEX_FILE = KNOWLEDGE_DIR / "index.md"
LOG_FILE = KNOWLEDGE_DIR / "log.md"
STATE_FILE = CONTENT_DIR / "state.json"

# ── One-shot migration: state.json moved out of scripts/ into the content
# dir in 2026-05. On any machine/KB clone whose state still lives at the
# legacy path, relocate it on first import. Idempotent — once the new file
# exists this is a single stat() call per process. Safe to delete this
# block once every KB has been migrated and pushed.
_LEGACY_STATE_FILE = SCRIPTS_DIR / "state.json"
if _LEGACY_STATE_FILE.exists() and not STATE_FILE.exists():
    import shutil as _shutil
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _shutil.move(str(_LEGACY_STATE_FILE), str(STATE_FILE))
    print(
        f"[config] Migrated compile state: "
        f"{_LEGACY_STATE_FILE.relative_to(ROOT_DIR)} → {STATE_FILE} "
        f"(commit it in the content repo to sync across machines)."
    )

# ── Timezone ───────────────────────────────────────────────────────────
TIMEZONE = "America/Chicago"


def now_iso() -> str:
    """Current time in ISO 8601 format."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    """Current date in ISO 8601 format."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
