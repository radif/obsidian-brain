#!/usr/bin/env python3
"""Fetch a YouTube transcript and save it as a markdown note in raw/transcripts/.

The saved note lands in a dedicated `transcripts` bucket under raw/. Like every
other raw bucket, it auto-discovers into the compile pipeline (see
`list_raw_files()` in scripts/utils.py) — once you've taken notes alongside
the transcript, run `just compile` to promote it into knowledge/.

Defaults:
- timestamps OFF (transcript body is plain prose) — pass `--timestamps` to prefix each line with `[m:ss]`
- language = "en"
- output = saved file (use --stdout to pipe instead)

Usage:
    just transcript "<youtube-url-or-id>"
    uv run python scripts/transcript.py <url> --timestamps
    uv run python scripts/transcript.py <url> --stdout
    uv run python scripts/transcript.py <url> --language=es
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / "raw" / "transcripts"

VIDEO_ID_PATTERNS = [
    r"(?:youtube\.com/watch\?v=)([a-zA-Z0-9_-]{11})",
    r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
    r"(?:youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
    r"(?:youtube\.com/embed/)([a-zA-Z0-9_-]{11})",
    r"^([a-zA-Z0-9_-]{11})$",
]


def extract_video_id(url_or_id: str) -> str | None:
    for pattern in VIDEO_ID_PATTERNS:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    return None


def fetch_video_metadata(video_id: str) -> tuple[str, str]:
    """Fetch (title, author) via YouTube's public oEmbed endpoint. No API key.

    Returns (video_id, "") on any failure — the script never blocks on metadata.
    """
    url = (
        "https://www.youtube.com/oembed"
        f"?url=https://www.youtube.com/watch?v={video_id}&format=json"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("title", video_id), data.get("author_name", "")
    except Exception:
        return video_id, ""


def get_transcript(video_id: str, language: str):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

    try:
        return YouTubeTranscriptApi().fetch(video_id, languages=[language])
    except TranscriptsDisabled:
        raise SystemExit(f"error: transcripts are disabled for video {video_id}")
    except NoTranscriptFound:
        raise SystemExit(
            f"error: no transcript found for {video_id} (language={language!r}). "
            f"Try --language=<other-code>."
        )


def format_transcript(transcript, include_timestamps: bool) -> str:
    if include_timestamps:
        lines = []
        for entry in transcript:
            mm = int(entry.start // 60)
            ss = int(entry.start % 60)
            lines.append(f"[{mm}:{ss:02d}] {entry.text}")
        return "\n".join(lines)
    return " ".join(e.text for e in transcript)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def build_note(video_id: str, title: str, author: str, language: str, body: str) -> str:
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    fm_lines = [
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
    ]
    if author:
        fm_lines.append(f'author: "{author.replace(chr(34), chr(39))}"')
    fm_lines.extend(
        [
            f"video_id: {video_id}",
            f"url: https://www.youtube.com/watch?v={video_id}",
            f"fetched: {today}",
            f"language: {language}",
            "tags: [transcript, youtube]",
            "---",
        ]
    )
    return "\n".join(fm_lines) + f"\n\n# {title}\n\n## Notes\n\n_(your notes go here)_\n\n## Transcript\n\n{body}\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch a YouTube transcript and save as a markdown note.")
    p.add_argument("url_or_id", help="YouTube URL or 11-character video ID")
    p.add_argument(
        "--timestamps",
        action="store_true",
        help="Prefix each line with [m:ss]. Off by default — body is plain prose.",
    )
    p.add_argument("--language", default="en", help="Transcript language code (default: en)")
    p.add_argument(
        "--stdout",
        action="store_true",
        help="Print transcript to stdout instead of saving a note",
    )
    args = p.parse_args()

    video_id = extract_video_id(args.url_or_id)
    if not video_id:
        print(f"error: could not extract video ID from {args.url_or_id!r}", file=sys.stderr)
        return 1

    transcript = get_transcript(video_id, args.language)
    body = format_transcript(transcript, include_timestamps=args.timestamps)

    if args.stdout:
        print(body)
        return 0

    title, author = fetch_video_metadata(video_id)
    slug = slugify(title) or video_id
    filename = f"{slug}-{video_id}.md"

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = TRANSCRIPTS_DIR / filename
    note = build_note(video_id, title, author, args.language, body)
    out_path.write_text(note, encoding="utf-8")

    rel = out_path.relative_to(ROOT)
    word_count = len(body.split())
    print(f"saved: {rel}")
    print(f"  title:    {title}")
    if author:
        print(f"  author:   {author}")
    print(f"  language: {args.language}")
    print(f"  segments: {len(transcript)}, ~{word_count:,} words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
