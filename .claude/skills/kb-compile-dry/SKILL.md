---
name: kb-compile-dry
description: Use when the user wants to preview what compile would do without actually writing anything. Runs `uv run python scripts/compile.py --dry-run`.
---

Run `uv run python scripts/compile.py --dry-run` via the Bash tool. Report which raw files would be (re)compiled based on hash state, but note that no files are being modified.
