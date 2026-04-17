---
name: kb-collect-assets-dry
description: Use when the user wants to preview which stray root images WOULD be moved to raw/clippings/assets/ without actually moving them. Runs `uv run python scripts/collect-assets.py --dry-run`.
---

Run `uv run python scripts/collect-assets.py --dry-run` via the Bash tool. Report which files would be moved, but note that no files are actually being touched. If the user confirms, follow up with the `kb-collect-assets` skill to actually perform the moves.
