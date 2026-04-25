# obsidian-brain command runner — see `just --list`

# Default: show available recipes
default:
    @just --list

# Install/refresh Python deps and tools
setup:
    ./scripts/setup.sh

# Compile new/changed raw files into knowledge/
compile:
    uv run python scripts/compile.py

# Force a full recompile of every raw file
compile-all:
    uv run python scripts/compile.py --all

# Preview what compile would do without writing
compile-dry:
    uv run python scripts/compile.py --dry-run

# Ask the knowledge base a question
ask question:
    uv run python scripts/query.py "{{question}}"

# Ask + save the answer into knowledge/qa/
ask-save question:
    uv run python scripts/query.py "{{question}}" --file-back

# Run all health checks (includes LLM contradiction check)
lint:
    uv run python scripts/lint.py

# Run only the free structural checks
lint-structural:
    uv run python scripts/lint.py --structural-only

# Manually flush a session transcript
flush:
    uv run python scripts/flush.py

# Move stray root images into raw/clippings/assets/
collect-assets:
    uv run python scripts/collect-assets.py

# Preview asset moves without touching files
collect-assets-dry:
    uv run python scripts/collect-assets.py --dry-run

# Interactive content setup — prompts for linked (symlinks) or solo (local dirs)
setup-content:
    uv run python scripts/link-content.py

# Solo mode: create raw/, knowledge/, notes/ as real dirs inside this repo (gitignored)
solo:
    uv run python scripts/link-content.py --solo

# Link an existing content repo into this working dir as symlinks
link-content path:
    uv run python scripts/link-content.py {{path}}

# Create a new skeleton content repo at path and link it here
init-content path:
    uv run python scripts/link-content.py {{path}} --init

# Fetch a YouTube transcript and save it as a markdown note in raw/transcripts/
transcript url_or_id:
    uv run python scripts/transcript.py "{{url_or_id}}"

# Commit + push content-repo changes (linked mode only)
push-content msg:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -L raw ]; then
        echo "error: raw is not a symlink — solo mode has no separate content repo." >&2
        exit 1
    fi
    content=$(cd "$(dirname "$(readlink raw)")" && pwd -P)
    cd "$content"
    git add -A
    if git diff --cached --quiet; then
        echo "no content changes to commit"
        exit 0
    fi
    git commit -m "{{msg}}"
    git push
