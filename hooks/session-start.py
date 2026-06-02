"""
SessionStart hook - injects knowledge base context into every conversation.

This is the "context injection" layer. When Claude Code starts a session,
this hook reads the knowledge base index and recent daily log, then injects
them as additional context so Claude always "remembers" what it has learned.

Configure in .claude/settings.json:
{
    "hooks": {
        "SessionStart": [{
            "matcher": "",
            "command": "uv run python hooks/session-start.py"
        }]
    }
}
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

# Recursion guard: exit immediately if we were spawned by a script that uses
# the Agent SDK (flush.py, compile.py, query.py). Those scripts set
# CLAUDE_INVOKED_BY before invoking the SDK; the SDK inherits env vars into
# its bundled Claude Code subprocess, which would otherwise fire this hook
# and trigger needless overhead (collect-assets subprocess + context injection)
# that can destabilize the SDK session.
if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

# Paths relative to project root
ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = ROOT / "knowledge"
DAILY_DIR = ROOT / "raw" / "daily"
SESSIONS_DIR = ROOT / "notes" / "sessions"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"
COLLECT_ASSETS_SCRIPT = ROOT / "scripts" / "collect-assets.py"
SYNC_SCRIPT = ROOT / "scripts" / "sync.py"

MAX_CONTEXT_CHARS = 20_000
MAX_LOG_LINES = 30
RECENT_SESSION_LOGS = 3


def get_recent_log() -> str:
    """Read the most recent daily log (today or yesterday)."""
    today = datetime.now(timezone.utc).astimezone()

    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            # Return last N lines to keep context small
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)

    return "(no recent daily log)"


def recent_session_logs_note() -> str:
    """Point at the most recent cross-device session logs (notes/sessions/).

    These operational continuity logs are too large to inline (tens of KB each),
    so we list the most recent filenames and let Claude Read them on demand when
    the user's first message continues prior work. Returns "" if none exist.
    """
    if not SESSIONS_DIR.exists():
        return ""
    try:
        logs = sorted(
            (p for p in SESSIONS_DIR.glob("*.md") if p.is_file()),
            key=lambda p: p.name,
            reverse=True,
        )[:RECENT_SESSION_LOGS]
    except OSError:
        return ""
    if not logs:
        return ""

    listed = "\n".join(f"- `notes/sessions/{p.name}`" for p in logs)
    return (
        "## Recent session logs (cross-device continuity)\n\n"
        "Operational logs written automatically at the end of past sessions and "
        "synced via the content repo. Most recent first:\n\n"
        f"{listed}\n\n"
        "If the user's first message **continues prior work** (\"keep going\", "
        "\"where did we leave off\", references recent work, or assumes shared "
        "context), `Read` the most recent log(s) in full before responding and "
        "surface any unfinished **Next-up bookmarks** / **State of long-running "
        "efforts** — they often won't remember them. Skip this for a purely fresh "
        "or structural/tooling task."
    )


def pending_compile_note() -> str:
    """Return a reminder string if uncompiled daily-log changes are pending.

    Auto-compilation was removed (it spent tokens without consent). Instead we
    detect, at session start, whether the most recent daily log is missing from
    the compile state or has changed since it was last compiled, and surface a
    reminder so the user can choose to run `/compile`. Returns "" when nothing
    is pending or state can't be read.
    """
    today = datetime.now(timezone.utc).astimezone()

    # Find the most recent existing daily log (today or yesterday).
    log_path = None
    for offset in range(2):
        date = today - timedelta(days=offset)
        candidate = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if candidate.exists():
            log_path = candidate
            break
    if log_path is None:
        return ""

    # Compile state lives next to raw/, not under scripts/ — see config.py.
    state_file = (ROOT / "raw").resolve().parent / "state.json"
    log_key = str(log_path.relative_to(ROOT))

    try:
        if state_file.exists():
            ingested = json.loads(state_file.read_text(encoding="utf-8")).get("ingested", {})
            entry = ingested.get(log_key)
            if entry is not None:
                current_hash = sha256(log_path.read_bytes()).hexdigest()[:16]
                if entry.get("hash") == current_hash:
                    return ""  # already compiled, unchanged — nothing pending
    except (json.JSONDecodeError, OSError):
        return ""  # can't tell — stay silent rather than nag

    return (
        f"## ⏳ Compile pending\n\n"
        f"`{log_key}` has changes that haven't been compiled into the knowledge "
        f"base yet. Compilation is **not** automatic (it spends tokens), so run "
        f"`/compile` (or `just compile`) when you're ready, or ignore this for now."
    )


def pull_repos() -> str:
    """Pull both repos (structural + content) so the session starts current.

    Runs `scripts/sync.py pull`, which fetches + merges and — on conflict —
    leaves the repo mid-merge and returns an action-required block instructing
    Claude to resolve it now. Best-effort: a timeout or any failure returns a
    short note instead of crashing the hook. Returns "" only if the sync script
    is absent (e.g. an old checkout).
    """
    if not SYNC_SCRIPT.exists():
        return ""
    try:
        proc = subprocess.run(
            ["uv", "run", "python", str(SYNC_SCRIPT), "pull"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        out = (proc.stdout or "").strip()
        if out:
            return out
        return "## 🔄 Repo sync (launch pull)\n\n_Sync produced no output._"
    except subprocess.TimeoutExpired:
        return (
            "## 🔄 Repo sync (launch pull)\n\n"
            "_Pull timed out — network may be slow. Run `uv run python "
            "scripts/sync.py pull` manually if you want to sync before working._"
        )
    except (FileNotFoundError, OSError) as e:
        return f"## 🔄 Repo sync (launch pull)\n\n_Pull could not run: {e}_"


def build_context() -> str:
    """Assemble the context to inject into the conversation."""
    parts = []

    # Cross-machine sync: pull both repos first so everything below reflects
    # the latest state. Surfaced at the top so any conflict-resolution prompt
    # is the first thing Claude sees.
    sync_note = pull_repos()
    if sync_note:
        parts.append(sync_note)

    # Today's date
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    # Reminder if there's uncompiled daily-log work (replaces old auto-compile).
    note = pending_compile_note()
    if note:
        parts.append(note)

    # Recent cross-device session logs (notes/sessions/) — placed before the
    # large index so this high-value pointer survives MAX_CONTEXT_CHARS truncation.
    sessions_note = recent_session_logs_note()
    if sessions_note:
        parts.append(sessions_note)

    # Knowledge base index (the core retrieval mechanism)
    if INDEX_FILE.exists():
        index_content = INDEX_FILE.read_text(encoding="utf-8")
        parts.append(f"## Knowledge Base Index\n\n{index_content}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")

    # Recent daily log
    recent_log = get_recent_log()
    parts.append(f"## Recent Daily Log\n\n{recent_log}")

    context = "\n\n---\n\n".join(parts)

    # Truncate if too long
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"

    return context


def collect_stray_assets() -> None:
    """File away any stray root-level images dropped by Obsidian Web Clipper.

    Must never crash the hook: output is swallowed and failures are ignored.
    The hook's stdout is reserved for the JSON hookSpecificOutput payload, so
    we capture the script's stdout/stderr instead of letting it leak out.
    """
    if not COLLECT_ASSETS_SCRIPT.exists():
        return
    try:
        subprocess.run(
            ["uv", "run", "python", str(COLLECT_ASSETS_SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def main():
    collect_stray_assets()
    context = build_context()

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
