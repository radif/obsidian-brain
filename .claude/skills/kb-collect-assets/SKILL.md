---
name: kb-collect-assets
description: Use when the user has stray image/attachment files at the project root (typically dropped there by Obsidian Web Clipper when its attachment folder isn't configured) and wants them moved into raw/clippings/assets/. Runs `uv run python scripts/collect-assets.py`.
---

Run `uv run python scripts/collect-assets.py` via the Bash tool. Report which image files were moved. If the user wants to preview the moves without actually touching files, use the `kb-collect-assets-dry` skill instead.

If this script is run often, recommend the user fix the underlying Obsidian settings (Files and links → attachment folder → `assets`; Web Clipper template output → `raw/clippings`) so the janitor isn't needed.
