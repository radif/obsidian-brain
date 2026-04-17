---
name: kb-compile
description: Use when the user wants to compile new or changed raw files into knowledge articles. Runs `uv run python scripts/compile.py`, which only processes files whose hash in scripts/state.json changed since last run.
---

Run `uv run python scripts/compile.py` via the Bash tool. This only processes raw files whose hash has changed — it's safe and cheap to run repeatedly. Report which files were compiled and whether any new concept or connection articles were created. If the user wanted a full recompile of everything, use the `kb-compile-all` skill instead.
