"""
Move stray image files from the project root into raw/clippings/assets/.

Obsidian Web Clipper drops attachments at the vault root when its attachment
folder setting isn't configured. This script is a janitor: it scoops up any
top-level image files and files them into the clippings assets directory.

Fix the underlying settings (Obsidian: Files and links → Default location for
new attachments → "In subfolder under current folder" + "assets"; Web Clipper:
template output → raw/clippings) and you won't need to run this. Until then,
run it after each clip.

Usage:
    uv run python scripts/collect-assets.py            # move images
    uv run python scripts/collect-assets.py --dry-run  # preview without moving
"""

from __future__ import annotations

import argparse
import sys

from config import CLIPPINGS_DIR, ROOT_DIR

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Move root-level images into raw/clippings/assets/")
    parser.add_argument("--dry-run", action="store_true", help="Show what would move, don't touch anything")
    args = parser.parse_args()

    assets_dir = CLIPPINGS_DIR / "assets"
    stray = sorted(
        p for p in ROOT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )

    if not stray:
        print("Project root is clean — no stray images to move.")
        return 0

    print(f"Found {len(stray)} stray image(s) at project root:")
    for p in stray:
        print(f"  - {p.name}")

    if args.dry_run:
        print(f"\n[DRY RUN] Would move to: {assets_dir.relative_to(ROOT_DIR)}/")
        return 0

    assets_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped = 0
    for src in stray:
        dest = assets_dir / src.name
        if dest.exists():
            print(f"  SKIP {src.name} — already exists in assets/")
            skipped += 1
            continue
        src.rename(dest)
        moved += 1

    print(f"\nMoved {moved}, skipped {skipped}. Assets now in: {assets_dir.relative_to(ROOT_DIR)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
