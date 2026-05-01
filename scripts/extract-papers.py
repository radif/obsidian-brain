#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "marker-pdf>=1.6",
# ]
# ///
"""Convert research-paper PDFs into markdown using marker.

Walks `raw/research/research-papers/*.pdf` and writes a sibling `*.md` for each
PDF. Figures are extracted into `raw/research/research-papers/assets/<stem>/`
and referenced via relative paths, matching the project's `raw/*/assets/`
convention (these dirs are skipped by `list_raw_files()` in scripts/utils.py
so they never enter the compile pipeline).

Marker is the right tool for academic papers — it preserves equations as
LaTeX, reconstructs tables, and handles multi-column layouts. First run
downloads several GB of ML models into uv's tool cache; subsequent runs are
fast. The script lives in its own PEP-723 environment so these heavy deps
don't bloat the main project venv that hooks and compile depend on.

Skips PDFs whose .md already exists; pass --force to re-convert.

Usage:
    just extract-papers
    just extract-papers raw/research/research-papers/foo.pdf
    uv run scripts/extract-papers.py --force
    uv run scripts/extract-papers.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS_DIR = ROOT / "raw" / "research" / "research-papers"
ASSETS_DIR = PAPERS_DIR / "assets"


def find_pdfs() -> list[Path]:
    return sorted(PAPERS_DIR.glob("*.pdf"))


def display_path(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def needs_conversion(pdf: Path, force: bool) -> bool:
    if force:
        return True
    return not pdf.with_suffix(".md").exists()


def rewrite_image_paths(text: str, image_names: list[str], rel_prefix: str) -> str:
    """Rewrite markdown image references to point at assets/<stem>/<name>.

    Marker emits `![alt](filename.jpeg)` with bare filenames. We re-route them
    to the assets subdir without disturbing other link-shaped tokens.
    """
    for name in image_names:
        pattern = re.compile(rf"\]\(\s*{re.escape(name)}\s*\)")
        text = pattern.sub(f"]({rel_prefix}{name})", text)
    return text


def write_outputs(pdf: Path, text: str, images: dict) -> tuple[Path, int]:
    md_path = pdf.with_suffix(".md")
    n_images = 0
    if images:
        asset_subdir = ASSETS_DIR / pdf.stem
        asset_subdir.mkdir(parents=True, exist_ok=True)
        for fname, image in images.items():
            image.save(asset_subdir / fname)
            n_images += 1
        text = rewrite_image_paths(text, list(images), f"assets/{pdf.stem}/")
    md_path.write_text(text, encoding="utf-8")
    return md_path, n_images


def main() -> int:
    p = argparse.ArgumentParser(
        description="Convert research-paper PDFs to markdown using marker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("paths", nargs="*", help="Specific PDFs to convert (default: all in raw/research/research-papers/)")
    p.add_argument("--force", action="store_true", help="Re-convert even if .md exists")
    p.add_argument("--dry-run", action="store_true", help="List files that would be converted; no writes")
    args = p.parse_args()

    if args.paths:
        pdfs = []
        for raw in args.paths:
            path = Path(raw)
            if not path.is_file():
                print(f"error: {raw} not found", file=sys.stderr)
                return 1
            if path.suffix.lower() != ".pdf":
                print(f"error: {raw} is not a .pdf", file=sys.stderr)
                return 1
            pdfs.append(path)
    else:
        if not PAPERS_DIR.exists():
            print(f"error: {display_path(PAPERS_DIR)} does not exist", file=sys.stderr)
            return 1
        pdfs = find_pdfs()
        if not pdfs:
            print(f"no PDFs found in {display_path(PAPERS_DIR)}")
            return 0

    todo = [pdf for pdf in pdfs if needs_conversion(pdf, args.force)]
    print(f"found {len(pdfs)} PDFs, {len(todo)} need conversion")
    for pdf in todo:
        print(f"  {display_path(pdf)}")

    if not todo:
        print("nothing to do (use --force to re-convert)")
        return 0
    if args.dry_run:
        return 0

    print("loading marker models (first run downloads several GB)...", flush=True)
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    converter = PdfConverter(artifact_dict=create_model_dict())

    failures: list[tuple[Path, Exception]] = []
    for i, pdf in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {pdf.name}", flush=True)
        try:
            rendered = converter(str(pdf))
            text, _ext, images = text_from_rendered(rendered)
            md_path, n_images = write_outputs(pdf, text, images or {})
            print(f"  -> {display_path(md_path)} ({len(text):,} chars, {n_images} images)")
        except Exception as e:
            failures.append((pdf, e))
            print(f"  ERROR: {e}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} failures:", file=sys.stderr)
        for pdf, e in failures:
            print(f"  {pdf.name}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
