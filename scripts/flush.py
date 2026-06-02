"""
Memory flush agent - extracts important knowledge from conversation context.

Spawned by session-end.py or pre-compact.py as a background process. Reads
pre-extracted conversation context from a .md file, uses the Claude Agent SDK
to decide what's worth saving, and appends the result to today's daily log.

Usage:
    uv run python flush.py <context_file.md> <session_id>
"""

from __future__ import annotations

# Recursion prevention: set this BEFORE any imports that might trigger Claude
import os
os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"

import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "raw" / "daily"
SESSIONS_DIR = ROOT / "notes" / "sessions"   # cross-device session logs (outside compile pipeline)
SCRIPTS_DIR = ROOT / "scripts"
STATE_FILE = SCRIPTS_DIR / "last-flush.json"
LOG_FILE = SCRIPTS_DIR / "flush.log"


def _stage_in_content(rel_path: str) -> None:
    """Stage one path (relative to the content-repo root) in the content repo.

    The end-of-session push commits only the staged index (never `git add -A`),
    so each writer must stage its own output. Best-effort: failures are logged.
    """
    content_repo = (ROOT / "raw").resolve().parent
    try:
        subprocess.run(
            ["git", "-C", str(content_repo), "add", "--", rel_path],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception as e:
        logging.error("Failed to stage %s: %s", rel_path, e)

# Set up file-based logging so we can verify the background process ran.
# The parent process sends stdout/stderr to DEVNULL (to avoid the inherited
# file handle bug on Windows), so this is our only observability channel.
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def load_flush_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_flush_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def append_to_daily_log(content: str, section: str = "Session") -> None:
    """Append content to today's daily log."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = DAILY_DIR / f"{today.strftime('%Y-%m-%d')}.md"

    if not log_path.exists():
        DAILY_DIR.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n## Sessions\n\n## Memory Maintenance\n\n",
            encoding="utf-8",
        )

    time_str = today.strftime("%H:%M")
    entry = f"### {section} ({time_str})\n\n{content}\n\n"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)


async def run_flush(context: str) -> str:
    """Use Claude Agent SDK to extract important knowledge from conversation context."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    prompt = f"""Review the conversation context below and respond with a concise summary
of important items that should be preserved in the daily log.
Do NOT use any tools — just return plain text.

Format your response as a structured daily log entry with these sections:

**Context:** [One line about what the user was working on]

**Key Exchanges:**
- [Important Q&A or discussions]

**Decisions Made:**
- [Any decisions with rationale]

**Lessons Learned:**
- [Gotchas, patterns, or insights discovered]

**Action Items:**
- [Follow-ups or TODOs mentioned]

Skip anything that is:
- Routine tool calls or file reads
- Content that's trivial or obvious
- Trivial back-and-forth or clarification exchanges

Only include sections that have actual content. If nothing is worth saving,
respond with exactly: FLUSH_OK

## Conversation Context

{context}"""

    response = ""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                # Log tokens + cost for diagnostics. Cost is API-equivalent only
                # — no charge if the user runs Claude Code via a subscription plan.
                from utils import format_token_usage
                cost = message.total_cost_usd or 0.0
                logging.info(
                    "Flush usage: %s | Cost*: $%.4f",
                    format_token_usage(message.usage),
                    cost,
                )
    except Exception as e:
        import traceback
        logging.error("Agent SDK error: %s\n%s", e, traceback.format_exc())
        response = f"FLUSH_ERROR: {type(e).__name__}: {e}"

    return response


async def run_session_log(context: str) -> str:
    """Second LLM pass: produce a rich operational session log for notes/sessions/.

    Unlike the daily-log flush (which feeds the compile pipeline), this is the
    cross-device continuity layer — read at the start of future sessions. Format
    mirrors the canonical 8-section session dump. Returns the markdown body, or
    "SESSION_LOG_SKIP" if there's nothing worth a continuity log.
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    prompt = f"""Write an operational SESSION LOG from the conversation context below.
This is continuity for a FUTURE session (possibly on another machine) to resume
work with zero re-deriving — not a knowledge article. Do NOT use any tools; return
plain Markdown only.

Produce these sections as Markdown `##` headings, in this order. Include a section
only if it has real content (omit empty ones), but always include 1, 7, and 8:

1. **High-level arc** — the phases of work this session, in chronological order
2. **Files created or modified** — every path, grouped by area
3. **Key facts** that surfaced or got refined
4. **Decisions made** — and the rationale
5. **Open issues / pending verifications** — anything the user must confirm or decide
6. **Tools / dependencies installed** during the session
7. **State of long-running efforts** — scrapes, compiles, builds, CI — each with the
   exact command to resume it (write "None." if there are none)
8. **Next-up bookmarks** — concrete continuation points in priority order, so resuming
   needs zero re-deriving (write "None." if there are none)

If the session was trivial (no durable work, decisions, or follow-ups worth resuming),
respond with exactly: SESSION_LOG_SKIP

## Conversation Context

{context}"""

    response = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                from utils import format_token_usage
                logging.info("Session-log usage: %s", format_token_usage(message.usage))
    except Exception as e:
        import traceback
        logging.error("Session-log SDK error: %s\n%s", e, traceback.format_exc())
        return "SESSION_LOG_SKIP"

    return response


def write_session_log(body: str) -> str | None:
    """Write a session log to notes/sessions/<YYYY-MM-DD>-<HHMM>.md. Returns the
    content-repo-relative path that was written (for staging), or None if skipped.
    """
    if not body or "SESSION_LOG_SKIP" in body:
        logging.info("Session log: SKIP (nothing worth logging)")
        return None

    now = datetime.now(timezone.utc).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y-%m-%d-%H%M")
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    log_path = SESSIONS_DIR / f"{stamp}.md"
    # Avoid clobbering a same-minute log from another session.
    suffix = 1
    while log_path.exists():
        log_path = SESSIONS_DIR / f"{stamp}-{suffix}.md"
        suffix += 1

    frontmatter = (
        "---\n"
        f"session_date: {date_str}\n"
        f'session_time: "{now.strftime("%H:%M %Z")}"\n'
        "title: Session context dump\n"
        "type: session-log\n"
        "visibility: internal\n"
        "tags: [session, context-dump]\n"
        "---\n\n"
        f"# Session context — {date_str}\n\n"
        "Operational dump of this session's conversation, written automatically at "
        "session end. Outside the compile pipeline (lives in `notes/`); read at the "
        "start of future sessions for cross-device continuity.\n\n"
        "---\n\n"
    )
    log_path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")
    logging.info("Session log written: %s (%d chars)", log_path.name, len(body))
    return f"notes/sessions/{log_path.name}"


# ---------------------------------------------------------------------------
# DISABLED 2026-06-02: end-of-day auto-compilation.
#
# This used to spawn compile.py in the background whenever flush ran after
# 6 PM and today's log had uncompiled changes. It was disabled because it
# spent tokens / Claude credits without consent — kicking off an expensive
# compile from a detached process the user couldn't see, sometimes exhausting
# the quota before they realized it was running. Bad planning around credit
# use. Replaced by a passive, free reminder in hooks/session-start.py
# (pending_compile_note) that surfaces uncompiled changes at session start so
# the user can choose to run `/compile` themselves.
#
# Kept here (commented) rather than deleted in case auto-compile is ever
# reintroduced behind an explicit opt-in / budget guard.
#
# COMPILE_AFTER_HOUR = 18  # 6 PM local time
#
#
# def maybe_trigger_compilation() -> None:
#     """If it's past the compile hour and today's log hasn't been compiled, run compile.py."""
#     import subprocess as _sp
#
#     now = datetime.now(timezone.utc).astimezone()
#     if now.hour < COMPILE_AFTER_HOUR:
#         return
#
#     # Check if today's log has already been compiled. State keys are paths
#     # relative to the repo root (e.g. "raw/daily/2026-04-10.md").
#     today_name = f"{now.strftime('%Y-%m-%d')}.md"
#     today_key = str((DAILY_DIR / today_name).relative_to(ROOT))
#     # Compile state lives next to raw/, not under scripts/ — see config.py.
#     compile_state_file = (ROOT / "raw").resolve().parent / "state.json"
#     if compile_state_file.exists():
#         try:
#             compile_state = json.loads(compile_state_file.read_text(encoding="utf-8"))
#             ingested = compile_state.get("ingested", {})
#             if today_key in ingested:
#                 # Already compiled today - check if the log has changed since
#                 from hashlib import sha256
#                 log_path = DAILY_DIR / today_name
#                 if log_path.exists():
#                     current_hash = sha256(log_path.read_bytes()).hexdigest()[:16]
#                     if ingested[today_key].get("hash") == current_hash:
#                         return  # log unchanged since last compile
#         except (json.JSONDecodeError, OSError):
#             pass
#
#     compile_script = SCRIPTS_DIR / "compile.py"
#     if not compile_script.exists():
#         return
#
#     logging.info("End-of-day compilation triggered (after %d:00)", COMPILE_AFTER_HOUR)
#
#     cmd = ["uv", "run", "--directory", str(ROOT), "python", str(compile_script)]
#
#     kwargs: dict = {}
#     if sys.platform == "win32":
#         kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
#     else:
#         kwargs["start_new_session"] = True
#
#     try:
#         log_handle = open(str(SCRIPTS_DIR / "compile.log"), "a")
#         _sp.Popen(cmd, stdout=log_handle, stderr=_sp.STDOUT, cwd=str(ROOT), **kwargs)
#     except Exception as e:
#         logging.error("Failed to spawn compile.py: %s", e)
# ---------------------------------------------------------------------------


def push_repos() -> None:
    """Push the content repo now that the daily log is written.

    flush.py is the detached process that produces end-of-session content, so
    this is the correct push point: the new daily-log entry is on disk before
    we commit+push. Delegated to scripts/sync.py (pure git, no SDK), which
    pushes the CONTENT repo only — the structural repo is pushed manually.
    Best-effort — failures are logged, never raised, so a sync problem can't
    break a flush.
    """
    sync_script = SCRIPTS_DIR / "sync.py"
    if not sync_script.exists():
        return
    try:
        proc = subprocess.run(
            ["uv", "run", "python", str(sync_script), "push"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        logging.info("Repo push:\n%s", (proc.stdout or proc.stderr or "").strip())
    except Exception as e:
        logging.error("Repo push failed to run: %s", e)


def main():
    if len(sys.argv) < 3:
        logging.error("Usage: %s <context_file.md> <session_id>", sys.argv[0])
        sys.exit(1)

    context_file = Path(sys.argv[1])
    session_id = sys.argv[2]

    logging.info("flush.py started for session %s, context: %s", session_id, context_file)

    if not context_file.exists():
        logging.error("Context file not found: %s", context_file)
        return

    # Deduplication: skip if same session was flushed within 60 seconds
    state = load_flush_state()
    if (
        state.get("session_id") == session_id
        and time.time() - state.get("timestamp", 0) < 60
    ):
        logging.info("Skipping duplicate flush for session %s", session_id)
        context_file.unlink(missing_ok=True)
        return

    # Read pre-extracted context
    context = context_file.read_text(encoding="utf-8").strip()
    if not context:
        logging.info("Context file is empty, skipping")
        context_file.unlink(missing_ok=True)
        return

    logging.info("Flushing session %s: %d chars", session_id, len(context))

    # Run the LLM extraction
    response = asyncio.run(run_flush(context))

    # Append to daily log (compile-pipeline feedstock), and stage it so the
    # end-of-session push commits it (push commits only the staged index).
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    substantive = False
    if "FLUSH_OK" in response:
        logging.info("Result: FLUSH_OK")
        append_to_daily_log(
            "FLUSH_OK - Nothing worth saving from this session", "Memory Flush"
        )
    elif "FLUSH_ERROR" in response:
        logging.error("Result: %s", response)
        append_to_daily_log(response, "Memory Flush")
    else:
        logging.info("Result: saved to daily log (%d chars)", len(response))
        append_to_daily_log(response, "Session")
        substantive = True
    _stage_in_content(f"raw/daily/{today}.md")

    # Cross-device session log (notes/sessions/) — a richer operational dump for
    # future sessions to resume from. Only for substantive sessions, to avoid a
    # second LLM call (and a clutter file) on trivial ones.
    if substantive:
        try:
            session_body = asyncio.run(run_session_log(context))
            session_rel = write_session_log(session_body)
            if session_rel:
                _stage_in_content(session_rel)
        except Exception as e:
            logging.error("Session log step failed: %s", e)

    # Update dedup state
    save_flush_state({"session_id": session_id, "timestamp": time.time()})

    # Clean up context file
    context_file.unlink(missing_ok=True)

    # DISABLED 2026-06-02: auto-compile previously ran here via
    # maybe_trigger_compilation() (see the commented-out block above). It was
    # turned off because it spent tokens / Claude credits without consent.
    # Uncompiled changes are now surfaced as a passive reminder at session
    # start (hooks/session-start.py) so the user runs `/compile` deliberately.
    # maybe_trigger_compilation()

    # Cross-machine sync: push both repos now that the daily log is on disk.
    push_repos()

    logging.info("Flush complete for session %s", session_id)


if __name__ == "__main__":
    main()
