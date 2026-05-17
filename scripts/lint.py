"""
Lint the knowledge base for structural and semantic health.

Runs 7 checks: broken links, orphan pages, orphan sources, stale articles,
contradictions (LLM), missing backlinks, and sparse articles.

Usage:
    uv run python lint.py                    # all checks
    uv run python lint.py --structural-only  # skip LLM checks (faster, cheaper)
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from config import KNOWLEDGE_DIR, REPORTS_DIR, ROOT_DIR, now_iso, today_iso
from utils import (
    COST_DISCLAIMER,
    count_inbound_links,
    extract_wikilinks,
    file_hash,
    format_token_usage,
    get_article_word_count,
    list_raw_files,
    list_wiki_articles,
    load_state,
    read_all_wiki_content,
    save_state,
    wiki_article_exists,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def check_broken_links() -> list[dict]:
    """Check for [[wikilinks]] that point to non-existent articles."""
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        for link in extract_wikilinks(content):
            if link.startswith("raw/"):
                continue  # raw source references are valid
            if not wiki_article_exists(link):
                issues.append({
                    "severity": "error",
                    "check": "broken_link",
                    "file": str(rel),
                    "detail": f"Broken link: [[{link}]] - target does not exist",
                })
    return issues


def check_orphan_pages() -> list[dict]:
    """Check for articles with zero inbound links."""
    issues = []
    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR)
        link_target = str(rel).replace(".md", "").replace("\\", "/")
        inbound = count_inbound_links(link_target)
        if inbound == 0:
            issues.append({
                "severity": "warning",
                "check": "orphan_page",
                "file": str(rel),
                "detail": f"Orphan page: no other articles link to [[{link_target}]]",
            })
    return issues


def check_orphan_sources() -> list[dict]:
    """Check for raw sources that haven't been compiled yet."""
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for source_path in list_raw_files():
        rel_key = str(source_path.relative_to(ROOT_DIR))
        if rel_key not in ingested:
            issues.append({
                "severity": "warning",
                "check": "orphan_source",
                "file": rel_key,
                "detail": f"Uncompiled source: {rel_key} has not been ingested",
            })
    return issues


def check_stale_articles() -> list[dict]:
    """Check if raw sources have changed since compilation."""
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for source_path in list_raw_files():
        rel_key = str(source_path.relative_to(ROOT_DIR))
        if rel_key in ingested:
            stored_hash = ingested[rel_key].get("hash", "")
            current_hash = file_hash(source_path)
            if stored_hash != current_hash:
                issues.append({
                    "severity": "warning",
                    "check": "stale_article",
                    "file": rel_key,
                    "detail": f"Stale: {rel_key} has changed since last compilation",
                })
    return issues


def check_missing_backlinks() -> list[dict]:
    """Check for asymmetric links: A links to B but B doesn't link to A."""
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        source_link = str(rel).replace(".md", "").replace("\\", "/")

        for link in extract_wikilinks(content):
            if link.startswith("raw/"):
                continue
            target_path = KNOWLEDGE_DIR / f"{link}.md"
            if target_path.exists():
                target_content = target_path.read_text(encoding="utf-8")
                if f"[[{source_link}]]" not in target_content:
                    issues.append({
                        "severity": "suggestion",
                        "check": "missing_backlink",
                        "file": str(rel),
                        "detail": f"[[{source_link}]] links to [[{link}]] but not vice versa",
                        "auto_fixable": True,
                    })
    return issues


def check_sparse_articles() -> list[dict]:
    """Check for articles with fewer than 200 words."""
    issues = []
    for article in list_wiki_articles():
        word_count = get_article_word_count(article)
        if word_count < 200:
            rel = article.relative_to(KNOWLEDGE_DIR)
            issues.append({
                "severity": "suggestion",
                "check": "sparse_article",
                "file": str(rel),
                "detail": f"Sparse article: {word_count} words (minimum recommended: 200)",
            })
    return issues


def check_stale_transaction_counts() -> list[dict]:
    """Flag hardcoded "N closed transactions" mentions that don't match the
    actual count of files in raw/operations/transactions/.

    Source of truth: per-transaction frontmatter files under
    raw/operations/transactions/*.md. Anything else that hardcodes a number
    (brochure copy, brand source, marketing snippets) drifts when new
    transactions are added — this check catches the drift.
    """
    import re

    issues = []
    txn_dir = ROOT_DIR / "raw" / "operations" / "transactions"
    if not txn_dir.exists():
        return issues  # nothing to compare against
    canonical_count = sum(1 for _ in txn_dir.glob("*.md"))

    # Patterns that capture a 2- or 3-digit number meant as a transaction
    # COUNT, not a price/year/per-period figure. Each captures the number
    # plus enough surrounding context for the proximity-guard below.
    # MIN_COUNT filters out per-year and per-cohort breakdowns (no real-estate
    # practice has a meaningful career-total under 50).
    MIN_COUNT = 50
    patterns = [
        # "99 closed transactions" / "99 closed sales" / "99 closed deals"
        re.compile(r"\b(\d{2,3})\s+closed\s+(?:transactions?|sales?|deals?|closings?)\b", re.IGNORECASE),
        # "99 transactions closed" / "99 transactions completed"
        re.compile(r"\b(\d{2,3})\s+transactions?\s+(?:closed|completed|done)\b", re.IGNORECASE),
        # Stat-list: "99 transactions · $105M" or "99 transactions,"
        re.compile(r"\b(\d{2,3})\s+transactions?\s*(?=[·,|\)]|\s+·)"),
        # Stat-list ending with $ amount: "99 transactions $105M"
        re.compile(r"\b(\d{2,3})\s+transactions?\s+\$"),
    ]

    # A match only counts as a "stale Lily-count" claim if it appears within
    # ~200 chars of a Lily-specific marker. This excludes competitor counts
    # (Kate Fomina's 234 deals, etc.) and breakdown tables.
    LILY_MARKERS = re.compile(
        r"\b(Lily|Garipova|lilygaripova\.com|105M|105,251,499|"
        r"\$105 million|Centermac|career|cumulative|practice|documented)\b",
        re.IGNORECASE,
    )
    # Negative guard: if any of these markers appear in the same window, the
    # match is documenting a third-party count (Homes.com inconsistency,
    # Zillow's reported count, ZoomInfo's older figure) — NOT Lily's own
    # marketing claim. Skip these.
    THIRD_PARTY_MARKERS = re.compile(
        r"\b(Homes\.com|ZoomInfo|Realtor\.com|directory drift|directory-drift|"
        r"third-party|offsite drift|off-site drift|internal inconsistency|"
        r"summary card|conflicting|stale figure)\b",
        re.IGNORECASE,
    )
    LILY_WINDOW = 200          # chars for the must-be-near-Lily guard
    THIRD_PARTY_WINDOW = 500   # chars for the must-not-be-near-third-party guard

    scan_roots = [
        ROOT_DIR / "raw",
        ROOT_DIR / "knowledge",
        ROOT_DIR / "projects",
        ROOT_DIR / "notes",
    ]
    excluded_substrings = (
        "/raw/operations/transactions/",         # source-of-truth files themselves
        "/knowledge/data/transactions.md",        # auto-generated
        "/knowledge/data/transactions-aggregates.md",  # auto-generated
        "/raw/competitors/",                      # competitor data (Kate's 234 etc.)
        "/raw/brand/online-research-saves/",      # literal third-party page captures
        "/notes/backups/",                        # historical snapshots
        "/notes/sessions/",                       # session logs — frozen in time
        "/reports/",                              # lint reports themselves
    )

    for root in scan_roots:
        if not root.exists():
            continue
        for md_file in root.rglob("*.md"):
            path_str = str(md_file).replace("\\", "/")
            if any(excl in path_str for excl in excluded_substrings):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            stale_numbers: set[int] = set()
            for pat in patterns:
                for m in pat.finditer(content):
                    try:
                        n = int(m.group(1))
                    except (ValueError, IndexError):
                        continue
                    if n == canonical_count or n < MIN_COUNT:
                        continue
                    # Proximity guards — require Lily-context (narrow window)
                    # AND not a third-party-citation context (wider window —
                    # third-party stat blocks tend to be long).
                    lily_start = max(0, m.start() - LILY_WINDOW)
                    lily_end = min(len(content), m.end() + LILY_WINDOW)
                    if not LILY_MARKERS.search(content[lily_start:lily_end]):
                        continue
                    tp_start = max(0, m.start() - THIRD_PARTY_WINDOW)
                    tp_end = min(len(content), m.end() + THIRD_PARTY_WINDOW)
                    if THIRD_PARTY_MARKERS.search(content[tp_start:tp_end]):
                        continue
                    stale_numbers.add(n)

            if stale_numbers:
                try:
                    rel = md_file.relative_to(ROOT_DIR)
                except ValueError:
                    rel = md_file
                stale_list = ", ".join(str(n) for n in sorted(stale_numbers))
                issues.append({
                    "severity": "warning",
                    "check": "stale_transaction_count",
                    "file": str(rel),
                    "detail": (
                        f"Hardcoded Lily transaction count(s) {stale_list} disagree with canonical "
                        f"count {canonical_count} from raw/operations/transactions/. "
                        f"Add missing transaction files, run `just transactions`, then update or remove the hardcoded number."
                    ),
                })

    return issues


async def check_contradictions() -> list[dict]:
    """Use LLM to detect contradictions across articles."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )
    cost = 0.0

    wiki_content = read_all_wiki_content()

    prompt = f"""Review this knowledge base for contradictions, inconsistencies, or
conflicting claims across articles.

## Knowledge Base

{wiki_content}

## Instructions

Look for:
- Direct contradictions (article A says X, article B says not-X)
- Inconsistent recommendations (different articles recommend conflicting approaches)
- Outdated information that conflicts with newer entries

For each issue found, output EXACTLY one line in this format:
CONTRADICTION: [file1] vs [file2] - description of the conflict
INCONSISTENCY: [file] - description of the inconsistency

If no issues found, output exactly: NO_ISSUES

Do NOT output anything else - no preamble, no explanation, just the formatted lines."""

    response = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                cost = message.total_cost_usd or 0.0
                print(f"    Tokens: {format_token_usage(message.usage)}")
                print(f"    Cost*:  ${cost:.4f}")
    except Exception as e:
        return [{"severity": "error", "check": "contradiction", "file": "(system)", "detail": f"LLM check failed: {e}"}]

    issues = []
    if "NO_ISSUES" not in response:
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("CONTRADICTION:") or line.startswith("INCONSISTENCY:"):
                issues.append({
                    "severity": "warning",
                    "check": "contradiction",
                    "file": "(cross-article)",
                    "detail": line,
                })

    return issues


def generate_report(all_issues: list[dict]) -> str:
    """Generate a markdown lint report."""
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]
    suggestions = [i for i in all_issues if i["severity"] == "suggestion"]

    lines = [
        f"# Lint Report - {today_iso()}",
        "",
        f"**Total issues:** {len(all_issues)}",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        f"- Suggestions: {len(suggestions)}",
        "",
    ]

    for severity, issues, marker in [
        ("Errors", errors, "x"),
        ("Warnings", warnings, "!"),
        ("Suggestions", suggestions, "?"),
    ]:
        if issues:
            lines.append(f"## {severity}")
            lines.append("")
            for issue in issues:
                fixable = " (auto-fixable)" if issue.get("auto_fixable") else ""
                lines.append(f"- **[{marker}]** `{issue['file']}` - {issue['detail']}{fixable}")
            lines.append("")

    if not all_issues:
        lines.append("All checks passed. Knowledge base is healthy.")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Lint the knowledge base")
    parser.add_argument(
        "--structural-only",
        action="store_true",
        help="Skip LLM-based checks (contradictions) - faster and free",
    )
    args = parser.parse_args()

    print("Running knowledge base lint checks...")
    all_issues: list[dict] = []

    # Structural checks (free, instant)
    checks = [
        ("Broken links", check_broken_links),
        ("Orphan pages", check_orphan_pages),
        ("Orphan sources", check_orphan_sources),
        ("Stale articles", check_stale_articles),
        ("Missing backlinks", check_missing_backlinks),
        ("Sparse articles", check_sparse_articles),
        ("Stale transaction counts", check_stale_transaction_counts),
    ]

    for name, check_fn in checks:
        print(f"  Checking: {name}...")
        issues = check_fn()
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")

    # LLM check (costs money)
    if not args.structural_only:
        print("  Checking: Contradictions (LLM)...")
        issues = asyncio.run(check_contradictions())
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")
    else:
        print("  Skipping: Contradictions (--structural-only)")

    # Generate and save report
    report = generate_report(all_issues)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"lint-{today_iso()}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Update state
    state = load_state()
    state["last_lint"] = now_iso()
    save_state(state)

    # Summary
    errors = sum(1 for i in all_issues if i["severity"] == "error")
    warnings = sum(1 for i in all_issues if i["severity"] == "warning")
    suggestions = sum(1 for i in all_issues if i["severity"] == "suggestion")
    print(f"\nResults: {errors} errors, {warnings} warnings, {suggestions} suggestions")

    if not args.structural_only:
        print(COST_DISCLAIMER)

    if errors > 0:
        print("\nErrors found - knowledge base needs attention!")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
