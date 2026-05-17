"""Weekly orchestrator for SERP monitoring.

Reads notes/serp-monitoring/queries.yaml, captures each query via Playwright,
parses each capture for Lily's position in the AI Overview, appends one CSV
row per query to notes/serp-monitoring/positions.csv, and writes an
ALERTS-<date>.md file if any Tier A query has demoted Lily below position 2.

Usage:
    just monitor-serp                                # all queries
    uv run python scripts/monitor_serp.py            # same
    uv run python scripts/monitor_serp.py --only A1,A2  # subset
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import date
from pathlib import Path

import yaml

# Project paths derived from this script's location so it works regardless of
# where the user invokes it from. The runner is owned by the structural repo
# but writes everything under notes/ (content repo via symlink).
ROOT = Path(__file__).resolve().parent.parent
QUERIES_FILE = ROOT / "notes" / "serp-monitoring" / "queries.yaml"
POSITIONS_CSV = ROOT / "notes" / "serp-monitoring" / "positions.csv"
# Entity to track in the AI Overview. List form so Russian Cyrillic
# transliteration matches the same person — Tier A query A5 is Cyrillic and
# Google renders "Лилия Гарипова" in that AI Overview.
ENTITY = ["Lily Garipova", "Лилия Гарипова"]

# Late imports so a syntax error in serp_parse doesn't break --help.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from serp_capture import CaptureCaptchaError, capture_serp  # noqa: E402
from serp_parse import parse_ai_overview  # noqa: E402

POSITIONS_HEADERS = [
    "date",
    "query_id",
    "tier",
    "query_text",
    "ai_overview_present",
    "entity_mentioned",
    "entity_position",
    "total_entities_named",
    "competitors_named",
    "framing_snippet",
    "cited_sources",
]


def slugify(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    return "".join(out).strip("-")[:60]


async def run_one(query: dict, run_dir: Path) -> dict:
    """Capture + parse a single query. Returns the row to write to positions.csv."""
    slug = f"{query['id']}-{slugify(query['text'])}"
    capture = await capture_serp(query["text"], run_dir, slug)
    parsed = parse_ai_overview(
        html=capture.html_path.read_text(encoding="utf-8"),
        entity=ENTITY,
    )
    # Sidecar JSON so we don't have to re-parse the HTML to inspect a run.
    (run_dir / f"{slug}.json").write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    return {
        "date": run_dir.name,
        "query_id": query["id"],
        "tier": query["tier"],
        "query_text": query["text"],
        "ai_overview_present": parsed["ai_overview_present"],
        "entity_mentioned": parsed["entity_mentioned"],
        "entity_position": parsed["entity_position"] if parsed["entity_position"] is not None else "",
        "total_entities_named": parsed["total_entities_named"],
        "competitors_named": "|".join(parsed["competitors_named"]),
        "framing_snippet": parsed["framing_snippet"],
        "cited_sources": "|".join(parsed["cited_sources"]),
    }


def append_csv(rows: list[dict]) -> None:
    write_header = not POSITIONS_CSV.exists()
    POSITIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with POSITIONS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSITIONS_HEADERS)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_alerts(run_dir: Path, rows: list[dict]) -> Path | None:
    """Tier A regression alert: any A-query that has Lily missing or below 2."""
    bad = []
    for row in rows:
        if row["tier"] != "A":
            continue
        pos = row["entity_position"]
        if pos == "" or (isinstance(pos, int) and pos > 2):
            bad.append(row)
    if not bad:
        return None
    alert_path = run_dir.parent / f"ALERTS-{run_dir.name}.md"
    lines = [f"# SERP Monitoring Alert — {run_dir.name}", "", "Tier A regression detected:", ""]
    for r in bad:
        lines.append(
            f"- **{r['query_id']}** `{r['query_text']}` — "
            f"position={r['entity_position'] or 'absent'} "
            f"named=[{r['competitors_named']}]"
        )
    alert_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return alert_path


async def main_async(only_ids: set[str] | None) -> int:
    queries = yaml.safe_load(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]
    if only_ids:
        queries = [q for q in queries if q["id"] in only_ids]
        if not queries:
            print(f"No queries match --only {sorted(only_ids)}")
            return 2

    today = date.today().isoformat()
    run_dir = POSITIONS_CSV.parent / today
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for q in queries:
        print(f"[{q['id']}] {q['text']}")
        try:
            row = await run_one(q, run_dir)
        except CaptureCaptchaError as e:
            # Hard stop — re-priming is required, not per-query recovery.
            print(f"\nCAPTCHA detected. Aborting run.\n{e}")
            return 4
        except Exception as e:
            print(f"  capture/parse failed: {e}")
            row = {
                "date": today,
                "query_id": q["id"],
                "tier": q["tier"],
                "query_text": q["text"],
                "ai_overview_present": False,
                "entity_mentioned": False,
                "entity_position": "",
                "total_entities_named": 0,
                "competitors_named": "",
                "framing_snippet": f"ERROR: {e}",
                "cited_sources": "",
            }
        rows.append(row)
        pos = row["entity_position"]
        present = "yes" if row["ai_overview_present"] else "no"
        print(f"  ai_overview={present} position={pos or '-'} named={row['total_entities_named']}")

    append_csv(rows)
    alert = write_alerts(run_dir, rows)
    if alert:
        print(f"\nALERT written: {alert}")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly SERP monitor for the Google AI Overview defense project")
    parser.add_argument("--only", type=str, default=None, help="Comma-separated query IDs, e.g. 'A1,A2'")
    args = parser.parse_args()
    only_ids = set(args.only.split(",")) if args.only else None
    code = asyncio.run(main_async(only_ids))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
