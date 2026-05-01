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
import shutil
import subprocess
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


def fetch_yt_metadata(video_id: str) -> dict:
    """Return {upload_date, channel_handle, channel_name} for video_id.

    Single yt-dlp call. Empty dict on any failure — never raises. Uses yt-dlp's
    metadata endpoint (different from the captions endpoint that can be IP-blocked).
    """
    if shutil.which("yt-dlp") is None:
        return {}
    try:
        result = subprocess.run(
            [
                "yt-dlp", "--skip-download", "--no-warnings", "--quiet",
                "--print", "%(upload_date)s\t%(uploader_id)s\t%(channel)s",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    parts = result.stdout.strip().split("\t")
    if len(parts) != 3:
        return {}
    raw_date, uploader_id, channel = parts
    out: dict[str, str] = {}
    if re.fullmatch(r"\d{8}", raw_date):
        out["upload_date"] = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    handle = uploader_id.lstrip("@").strip()
    if handle and handle != "NA":
        out["channel_handle"] = handle
    if channel and channel != "NA":
        out["channel_name"] = channel
    return out


def fetch_upload_date(video_id: str) -> str | None:
    """Backward-compat thin wrapper around fetch_yt_metadata."""
    return fetch_yt_metadata(video_id).get("upload_date")


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


def get_transcript(video_id: str, languages: list[str], auto_fallback: bool = False):
    """Fetch a transcript for video_id. Returns (transcript, language_used).

    Tries languages in order. If `auto_fallback` is True and none match,
    falls back to whatever transcript is available (manual preferred over
    auto-generated). Raises TranscriptsDisabled / NoTranscriptFound on failure.
    """
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import NoTranscriptFound

    api = YouTubeTranscriptApi()
    try:
        transcript = api.fetch(video_id, languages=languages)
        return transcript, transcript.language_code
    except NoTranscriptFound:
        if not auto_fallback:
            raise
    listing = api.list(video_id)
    candidates = list(listing) if hasattr(listing, "__iter__") else []
    candidates.sort(key=lambda t: getattr(t, "is_generated", True))
    if not candidates:
        raise NoTranscriptFound(video_id, languages, [])
    chosen = candidates[0]
    return chosen.fetch(), chosen.language_code


def format_transcript(
    transcript,
    include_timestamps: bool,
    paragraph_gap: float = 4.0,
    separator_gap: float = 7.0,
) -> str:
    """Render snippets to text. With timestamps off, inserts a blank line when
    the inter-onset interval between consecutive snippets is ≥ paragraph_gap,
    and a `---` separator at ≥ separator_gap.

    Uses inter-onset (next.start - prev.start), not post-end gap, because
    YouTube's snippet `duration` stretches to span pauses — so end-to-start gaps
    are always near zero. Inter-onset reliably catches real pauses (continuous
    speech runs ~1-3s/snippet; a real pause pushes onset spacing to 4+s).

    These gaps are NOT speaker labels — pauses don't always mean turn changes
    and turn changes don't always have long pauses. They're a readability aid
    that highlights *likely* break points.
    """
    if include_timestamps:
        return "\n".join(
            f"[{int(e.start // 60)}:{int(e.start % 60):02d}] {e.text}" for e in transcript
        )

    parts: list[str] = []
    prev_start: float | None = None
    for entry in transcript:
        text = entry.text.strip()
        if not text:
            continue
        if prev_start is None:
            parts.append(text)
        else:
            interval = entry.start - prev_start
            if interval >= separator_gap:
                parts.append(f"\n\n---\n\n{text}")
            elif interval >= paragraph_gap:
                parts.append(f"\n\n{text}")
            else:
                parts.append(f" {text}")
        prev_start = entry.start
    return "".join(parts)


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def build_note(
    video_id: str,
    title: str,
    author: str,
    language: str,
    body: str,
    published: str | None = None,
) -> str:
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
        ]
    )
    if published:
        fm_lines.append(f"published: {published}")
    fm_lines.extend(
        [
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
    p.add_argument(
        "--language",
        default="en",
        help="Comma-separated language code preferences, tried in order (default: en)",
    )
    p.add_argument(
        "--auto-fallback",
        action="store_true",
        help="If preferred languages fail, use any available transcript (manual preferred over auto)",
    )
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

    languages = [lang.strip() for lang in args.language.split(",") if lang.strip()]
    from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

    try:
        transcript, lang_used = get_transcript(video_id, languages, auto_fallback=args.auto_fallback)
    except TranscriptsDisabled:
        print(f"error: transcripts are disabled for video {video_id}", file=sys.stderr)
        return 1
    except NoTranscriptFound:
        print(
            f"error: no transcript found for {video_id} (languages={languages}). "
            f"Try --language=<other-code> or --auto-fallback.",
            file=sys.stderr,
        )
        return 1
    body = format_transcript(transcript, include_timestamps=args.timestamps)

    if args.stdout:
        print(body)
        return 0

    title, author = fetch_video_metadata(video_id)
    yt_meta = fetch_yt_metadata(video_id)
    published = yt_meta.get("upload_date")
    channel_handle = yt_meta.get("channel_handle") or "unknown-channel"
    slug = slugify(title) or video_id
    filename = f"{slug}-{video_id}.md"

    out_dir = TRANSCRIPTS_DIR / channel_handle
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    note = build_note(video_id, title, author, lang_used, body, published=published)
    out_path.write_text(note, encoding="utf-8")

    rel = out_path.relative_to(ROOT)
    word_count = len(body.split())
    print(f"saved: {rel}")
    print(f"  title:    {title}")
    if author:
        print(f"  author:   {author}")
    print(f"  language: {lang_used}")
    print(f"  segments: {len(transcript)}, ~{word_count:,} words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
