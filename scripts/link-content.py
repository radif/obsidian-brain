#!/usr/bin/env python3
"""Set up content storage for obsidian-brain.

Two supported content models:

  * Linked mode (recommended): raw/, knowledge/, notes/ are symlinks into a
    separate private content repo. Gives you version history, backup, and
    cross-machine sync. Use when you want GitHub-hosted content.

  * Solo mode: raw/, knowledge/, notes/ are real directories inside the
    structural repo working directory — gitignored here, so they never leak
    into the public structural repo. Use when you don't want a second repo.

Either mode works with the same scripts and hooks. The structural repo's
.gitignore (patterns without trailing slashes) intentionally matches both
symlinks *and* real directories, so you can switch modes later without
changes to the ignore list.

Usage:
    uv run python scripts/link-content.py                     # interactive
    uv run python scripts/link-content.py --solo              # solo mode
    uv run python scripts/link-content.py <path>              # link existing content repo
    uv run python scripts/link-content.py <path> --init       # create skeleton + link

Symlinks in linked mode are *relative*, so the two repos remain linked when
relocated together. The script is idempotent — re-running with the same
choice verifies the existing state instead of rebuilding it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

CONTENT_DIRS = ["raw", "knowledge", "notes"]
SKELETON_SUBDIRS = [
    "raw/daily",
    "raw/clippings",
    "knowledge/concepts",
    "knowledge/connections",
    "knowledge/qa",
    "notes",
]

ROOT = Path(__file__).resolve().parent.parent

CONTENT_README = """\
# Content repo

Private companion to the obsidian-brain structural repo. Holds authored
knowledge (`raw/`, `knowledge/`, `notes/`); consumed via symlinks from
the structural repo's working directory.

Don't work in this repo directly — open the structural repo in Claude Code
and let the scripts + hooks operate through the symlinks.
"""

CONTENT_GITIGNORE = """\
# Uncomment to exclude reconstructible reference material (downloaded corpora,
# unzipped external repos) that bloats history without adding authored value.
# raw/research/code-samples/**
# raw/research/research-papers/*.zip

.DS_Store
Thumbs.db
"""


# ── Linked-mode helpers ──────────────────────────────────────────────────

def init_content_repo(path: Path) -> None:
    path.mkdir(parents=True)
    for sub in SKELETON_SUBDIRS:
        d = path / sub
        d.mkdir(parents=True)
        (d / ".gitkeep").touch()
    (path / ".gitignore").write_text(CONTENT_GITIGNORE)
    (path / "README.md").write_text(CONTENT_README)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    print(f"  initialized: {path} (git init, skeleton, .gitignore, README.md)")


def link_or_verify(src: Path, target: Path) -> None:
    """Ensure src is a relative symlink to target. Idempotent; safe on existing
    correct symlinks. Errors cleanly on conflicts."""
    rel = src.relative_to(ROOT)
    if src.is_symlink():
        if os.path.realpath(src) == str(target):
            print(f"  {rel}: already linked -> {os.readlink(src)}")
            return
        raise SystemExit(
            f"error: {rel} is a symlink pointing elsewhere ({os.readlink(src)}).\n"
            f"  fix: rm {rel}  # then re-run"
        )
    if src.exists():
        if src.is_dir() and not any(src.iterdir()):
            src.rmdir()
        else:
            raise SystemExit(
                f"error: {rel} exists as a non-empty directory (solo mode setup).\n"
                f"  fix: move its contents into {target}/ first, then `rm -r {rel}` and re-run"
            )
    link_target = os.path.relpath(target, start=src.parent)
    src.symlink_to(link_target)
    print(f"  {rel} -> {link_target}")


def run_linked(content_path: Path, init: bool) -> int:
    content = content_path.expanduser().resolve()
    if not content.exists():
        if not init:
            print(f"error: {content} does not exist. Pass --init to create a skeleton.", file=sys.stderr)
            return 1
        init_content_repo(content)
    elif not content.is_dir():
        print(f"error: {content} is not a directory.", file=sys.stderr)
        return 1
    else:
        for d in CONTENT_DIRS:
            sub = content / d
            if not sub.is_dir():
                sub.mkdir(parents=True)
                print(f"  created missing subdir: {sub}")

    print(f"linking obsidian-brain -> {content}")
    for name in CONTENT_DIRS:
        link_or_verify(ROOT / name, content / name)
    print("\ndone. sanity check: just compile-dry")
    return 0


# ── Solo-mode helpers ────────────────────────────────────────────────────

def run_solo() -> int:
    """Create raw/, knowledge/, notes/ as real directories in the structural
    repo working directory. Gitignored via the structural repo's .gitignore."""
    for name in CONTENT_DIRS:
        path = ROOT / name
        if path.is_symlink():
            raise SystemExit(
                f"error: {name} is a symlink (linked mode is active).\n"
                f"  fix: rm {name}  # for each of raw/knowledge/notes, then re-run with --solo"
            )
    for sub in SKELETON_SUBDIRS:
        d = ROOT / sub
        d.mkdir(parents=True, exist_ok=True)
    print("solo mode: real directories created in the structural repo")
    for name in CONTENT_DIRS:
        print(f"  {name}/  (gitignored — content stays local to this checkout)")
    print("\nswitch to a separate content repo later with:")
    print("  mv raw knowledge notes <path>/ && just link-content <path>")
    return 0


# ── Interactive entry ────────────────────────────────────────────────────

def prompt_mode() -> str:
    print()
    print("How would you like to manage your knowledge content?")
    print()
    print("  [1] Work directly in this checkout.")
    print("      raw/, knowledge/, notes/ become real directories inside")
    print("      the structural repo. They're gitignored here, so they")
    print("      never get committed to the public structural repo.")
    print()
    print("  [2] Use a separate private git repo for your content.  (recommended)")
    print("      raw/, knowledge/, notes/ become symlinks into that repo.")
    print("      Gives you version history, off-site backup, cross-machine sync.")
    print()
    while True:
        choice = input("Choice [1/2]: ").strip()
        if choice == "1":
            return "solo"
        if choice == "2":
            return "linked"
        print("  please enter 1 or 2")


def prompt_linked_path() -> tuple[Path, bool]:
    default = "../obsidian-brain-content"
    entered = input(f"\nPath to content repo [{default}]: ").strip()
    path = Path(entered or default)
    resolved = path.expanduser().resolve()
    init = not resolved.exists()
    if init:
        print(f"  {resolved} does not exist — will create a skeleton there.")
    return path, init


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Set up content storage for obsidian-brain (linked or solo).",
        epilog="Run without arguments for interactive mode.",
    )
    ap.add_argument("content_path", type=Path, nargs="?",
                    help="path to content repo (linked mode). Omit to prompt.")
    ap.add_argument("--init", action="store_true",
                    help="linked mode: create skeleton + git init if path doesn't exist")
    ap.add_argument("--solo", action="store_true",
                    help="solo mode: create raw/knowledge/notes as real dirs (no symlinks)")
    args = ap.parse_args()

    if args.solo:
        if args.content_path or args.init:
            ap.error("--solo cannot be combined with a path or --init")
        return run_solo()

    if args.content_path is None:
        mode = prompt_mode()
        if mode == "solo":
            return run_solo()
        path, init = prompt_linked_path()
        return run_linked(path, init)

    return run_linked(args.content_path, args.init)


if __name__ == "__main__":
    sys.exit(main())
