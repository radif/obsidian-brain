#!/usr/bin/env python3
"""Bulk-transcribe every video in a YouTube channel into raw/transcripts/.

Enumerates videos via `yt-dlp --flat-playlist`, then for each video tries the
preferred language list (default: ru,en) with auto-fallback to any available
transcript. Skips videos already saved (matched by video_id suffix).

Usage:
    just transcribe-channel "https://www.youtube.com/@somechannel"
    uv run python scripts/transcribe-channel.py <channel-url> --languages=en
    uv run python scripts/transcribe-channel.py <channel-url> --no-fallback
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_NOISE_TAG_RE = re.compile(r"\[(?:music|applause|laughter|sound|noise|inaudible)\]", re.IGNORECASE)


def is_music_only(body: str) -> bool:
    """True if the transcript has no meaningful speech beyond music/applause tags.

    Strips bracket annotations like [Music] then counts tokens >= 3 chars. Property
    tour videos with only background music typically yield <30 such tokens.
    """
    cleaned = _NOISE_TAG_RE.sub(" ", body)
    meaningful = [w for w in cleaned.split() if len(w) >= 3]
    return len(meaningful) < 30

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / "raw" / "transcripts"

sys.path.insert(0, str(ROOT / "scripts"))
from transcript import (  # noqa: E402
    build_note,
    fetch_video_metadata,
    fetch_yt_metadata,
    format_transcript,
    get_transcript,
    slugify,
)


def derive_channel_handle(channel_url: str) -> str | None:
    """Extract `handle` from URLs like https://www.youtube.com/@handle/videos."""
    m = re.search(r"@([a-zA-Z0-9_.\-]+)", channel_url)
    return m.group(1) if m else None


def list_channel_videos(channel_url: str) -> list[tuple[str, str]]:
    """Return [(video_id, title), ...] for every video in the channel."""
    if shutil.which("yt-dlp") is None:
        raise SystemExit("error: yt-dlp not found on PATH (install with `brew install yt-dlp`)")
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--print", "%(id)s\t%(title)s", channel_url],
        check=True,
        capture_output=True,
        text=True,
    )
    videos = []
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        if vid:
            videos.append((vid.strip(), title.strip()))
    return videos


def already_saved(video_id: str, channel_handle: str | None = None) -> Path | None:
    """Find an existing transcript for video_id. Searches the channel subdir
    when known, plus the legacy flat layout under TRANSCRIPTS_DIR for compat."""
    if channel_handle:
        matches = list((TRANSCRIPTS_DIR / channel_handle).glob(f"*-{video_id}.md"))
        if matches:
            return matches[0]
    legacy = list(TRANSCRIPTS_DIR.glob(f"*-{video_id}.md"))
    return legacy[0] if legacy else None


def transcribe_one(
    video_id: str,
    languages: list[str],
    auto_fallback: bool,
    channel_handle: str | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """Fetch + write one transcript. Returns (status, detail).

    If `force` is True, re-fetches even when a saved file exists. The existing
    file is left in place until the new fetch succeeds, then overwritten.
    """
    from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

    existing = already_saved(video_id, channel_handle)
    if existing and not force:
        return "skip", f"already saved: {existing.relative_to(TRANSCRIPTS_DIR)}"

    try:
        transcript, lang_used = get_transcript(video_id, languages, auto_fallback=auto_fallback)
    except TranscriptsDisabled:
        return "fail", "transcripts disabled"
    except NoTranscriptFound:
        return "fail", f"no transcript (tried {languages}, fallback={auto_fallback})"
    except Exception as e:
        return "fail", f"{type(e).__name__}: {e}"

    body = format_transcript(transcript, include_timestamps=False)
    if is_music_only(body):
        return "skip", "music-only transcript"
    title, author = fetch_video_metadata(video_id)
    yt_meta = fetch_yt_metadata(video_id)
    published = yt_meta.get("upload_date")
    handle = channel_handle or yt_meta.get("channel_handle") or "unknown-channel"
    slug = slugify(title) or video_id
    out_dir = TRANSCRIPTS_DIR / handle
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}-{video_id}.md"
    out_path.write_text(
        build_note(video_id, title, author, lang_used, body, published=published),
        encoding="utf-8",
    )
    word_count = len(body.split())
    return "ok", f"{out_path.relative_to(TRANSCRIPTS_DIR)} ({lang_used}, ~{word_count:,} words)"


def main() -> int:
    p = argparse.ArgumentParser(description="Bulk-transcribe a YouTube channel into raw/transcripts/.")
    p.add_argument("channel_url", help="YouTube channel URL (e.g. https://www.youtube.com/@handle)")
    p.add_argument(
        "--languages",
        default="ru,en",
        help="Comma-separated language preferences, tried in order (default: ru,en)",
    )
    p.add_argument(
        "--no-fallback",
        action="store_true",
        help="Disable auto-fallback to any available transcript when preferred languages fail",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch even if a saved transcript already exists (overwrites in place)",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="Seconds to wait between fetch attempts to avoid rate-limit/IP blocks (default: 5.0)",
    )
    args = p.parse_args()

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]
    auto_fallback = not args.no_fallback

    channel_handle = derive_channel_handle(args.channel_url)
    print(
        f"enumerating: {args.channel_url} (handle={channel_handle or 'unknown'})",
        file=sys.stderr,
    )
    videos = list_channel_videos(args.channel_url)
    print(f"found {len(videos)} videos\n", file=sys.stderr)

    counts = {"ok": 0, "skip": 0, "fail": 0}
    for i, (vid, title) in enumerate(videos, 1):
        prefix = f"[{i}/{len(videos)}] {vid}"
        status, detail = transcribe_one(
            vid, languages, auto_fallback, channel_handle=channel_handle, force=args.force
        )
        counts[status] += 1
        symbol = {"ok": "✓", "skip": "·", "fail": "✗"}[status]
        print(f"{prefix} {symbol} {detail}  — {title[:60]}", flush=True)
        if i < len(videos) and args.delay > 0 and status != "skip":
            time.sleep(args.delay)

    print(
        f"\ndone: {counts['ok']} new, {counts['skip']} skipped, {counts['fail']} failed",
        file=sys.stderr,
    )
    return 0 if counts["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
