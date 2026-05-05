#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marker-pdf>=1.6",
# ]
# ///
"""Convert a PDF file to Markdown using marker.

Output defaults to the same directory and stem as the input, with a `.md`
extension. Figures are extracted into a sibling `assets/<stem>/` directory
and referenced via relative paths, matching the project's `assets/`
convention (these dirs are skipped by `list_raw_files()` in scripts/utils.py
so they never enter the compile pipeline).

Marker is the right tool for academic papers — it preserves equations as
LaTeX, reconstructs tables, and handles multi-column layouts. First run
downloads several GB of ML models into uv's tool cache; subsequent runs are
fast. The script lives in its own PEP-723 environment so these heavy deps
don't bloat the main project venv that hooks and compile depend on.

Usage:
    just pdf-to-md path/to/file.pdf
    uv run scripts/pdf-to-md.py path/to/file.pdf
    uv run scripts/pdf-to-md.py file.pdf --force

Defaults to CPU because marker's surya layout encoder hits MPS attention bugs
on certain PDFs. Override with `TORCH_DEVICE=mps just pdf-to-md ...` if you
want to try the GPU path.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("TORCH_DEVICE", "cpu")


def rewrite_image_paths(text: str, image_names: list[str], rel_prefix: str) -> str:
    """Rewrite markdown image references to point at assets/<stem>/<name>.

    Marker emits `![alt](filename.jpeg)` with bare filenames. We re-route them
    to the assets subdir without disturbing other link-shaped tokens.
    """
    for name in image_names:
        pattern = re.compile(rf"\]\(\s*{re.escape(name)}\s*\)")
        text = pattern.sub(f"]({rel_prefix}{name})", text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a PDF to Markdown using marker.")
    parser.add_argument("input", type=Path, help="Path to .pdf file")
    parser.add_argument("--force", action="store_true", help="Overwrite existing .md output")
    args = parser.parse_args()

    src = args.input.expanduser().resolve()
    if not src.is_file():
        print(f"error: input not found: {src}", file=sys.stderr)
        return 1
    if src.suffix.lower() != ".pdf":
        print(f"error: {src} is not a .pdf", file=sys.stderr)
        return 1

    dst = src.with_suffix(".md")
    if dst.exists() and not args.force:
        print(f"error: {dst} exists (use --force to overwrite)", file=sys.stderr)
        return 1

    print("loading marker models (first run downloads several GB)...", flush=True)
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter(str(src))
    text, _ext, images = text_from_rendered(rendered)
    images = images or {}

    n_images = 0
    if images:
        asset_subdir = src.parent / "assets" / src.stem
        asset_subdir.mkdir(parents=True, exist_ok=True)
        for fname, image in images.items():
            image.save(asset_subdir / fname)
            n_images += 1
        text = rewrite_image_paths(text, list(images), f"assets/{src.stem}/")

    dst.write_text(text, encoding="utf-8")
    print(f"{dst} ({len(text):,} chars, {n_images} images)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
