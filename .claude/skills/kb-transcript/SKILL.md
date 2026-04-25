---
name: kb-transcript
description: Use when the user wants to fetch a YouTube video's transcript and save it as a markdown note for note-taking. Runs `uv run python scripts/transcript.py <url-or-id>` which writes to `raw/transcripts/<slug>-<video_id>.md` with frontmatter (title, author, video_id, url, fetched date, language) and a `## Notes` section above the transcript body for the user to fill in.
---

Run `uv run python scripts/transcript.py "<url-or-id>"` via the Bash tool. The script extracts the video ID from URL or accepts a bare 11-char ID, fetches the transcript via the public `youtube-transcript-api` package, fetches title + author via the public oEmbed endpoint (no API key), and saves a note to `raw/transcripts/<slug>-<video_id>.md`.

Defaults: timestamps OFF (body is plain prose), language `en`, output saved to file. Flags available if the user asks: `--timestamps` (prefix each line with `[m:ss]` — useful when they want to cite specific moments), `--language=<code>`, `--stdout` (pipe instead of save).

After the script returns, report the saved path verbatim. Don't auto-read the transcript file unless the user explicitly asks — transcripts can be very long and shouldn't pollute conversation context by default. The saved file has a `## Notes` section above the transcript where the user fills in their own notes; once they have, `just compile` will promote the file into `knowledge/` like any other raw source.
