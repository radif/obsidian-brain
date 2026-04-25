---
description: Fetch a YouTube transcript and save it as a markdown note in raw/transcripts/
allowed-tools: Bash(uv run python scripts/transcript.py:*)
argument-hint: <youtube-url-or-video-id>
---

If `$ARGUMENTS` is empty, ask the user for a YouTube URL or 11-character video ID before doing anything.

Otherwise, run `uv run python scripts/transcript.py "$ARGUMENTS"` via the Bash tool and report the saved file path verbatim. Then offer (in one short sentence) to read the saved transcript and help the user summarize, take notes on it, or extract specific sections — but do not auto-read or auto-summarize unless the user asks. Notes go in the `## Notes` section at the top of the saved file; the raw transcript is below.
