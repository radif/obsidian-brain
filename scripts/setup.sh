#!/usr/bin/env bash
# Bootstrap the obsidian-brain project: install `just`, `uv`, and Python deps.
# Idempotent — safe to re-run.

set -euo pipefail

cd "$(dirname "$0")/.."

have() { command -v "$1" >/dev/null 2>&1; }

# Homebrew is the install channel for `just` and `uv` on macOS.
if ! have brew; then
    echo "error: Homebrew is required. Install from https://brew.sh" >&2
    exit 1
fi

if ! have just; then
    echo "installing just..."
    brew install just
else
    echo "just already installed ($(just --version))"
fi

if ! have uv; then
    echo "installing uv..."
    brew install uv
else
    echo "uv already installed ($(uv --version))"
fi

echo "syncing python dependencies..."
uv sync

echo
echo "setup complete. run 'just' to see available recipes."
