#!/usr/bin/env python3
"""Convert an RTF file to Markdown via pandoc.

Output defaults to the same directory and stem as the input, with a `.md`
extension. Override with `--output` / `-o`, or use `--stdout` to print.

Usage:
    just rtf-to-md path/to/file.rtf
    uv run python scripts/rtf-to-md.py path/to/file.rtf
    uv run python scripts/rtf-to-md.py file.rtf -o other.md
    uv run python scripts/rtf-to-md.py file.rtf --stdout
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert RTF to Markdown via pandoc.")
    parser.add_argument("input", type=Path, help="Path to .rtf file")
    parser.add_argument("-o", "--output", type=Path, help="Output .md path (default: same dir/stem)")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of writing a file")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output file")
    args = parser.parse_args()

    if shutil.which("pandoc") is None:
        print("error: pandoc not found on PATH (install with `brew install pandoc`)", file=sys.stderr)
        return 1

    src = args.input.expanduser().resolve()
    if not src.is_file():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 1

    cmd = ["pandoc", "-f", "rtf", "-t", "gfm", "--wrap=none", str(src)]

    if args.stdout:
        result = subprocess.run(cmd, check=False)
        return result.returncode

    dst = (args.output.expanduser().resolve() if args.output else src.with_suffix(".md"))
    if dst.exists() and not args.force:
        print(f"error: {dst} exists (use --force to overwrite)", file=sys.stderr)
        return 1

    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd.extend(["-o", str(dst)])
    result = subprocess.run(cmd, check=False)
    if result.returncode == 0:
        print(dst)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
