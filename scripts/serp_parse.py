"""Parse Google AI Overview blocks out of raw SERP HTML.

The parser is intentionally HTML-structure-based, not LLM-based. AI Overview
markup changes occasionally; when it does, regenerate fixtures from a real
capture, run the tests, and adjust the selectors here. Keep the LLM out of
the hot loop so weekly runs are fast and deterministic.

Supports two markup shapes:
  1. Synthetic fixture shape: <div data-attrid="AIOverview"> with .aio-summary
     and <b> name tags. Used by the unit tests.
  2. Real Google shape (as of 2026-05): the "Show more AI Overview" button has
     aria-label="Show more AI Overview"; named entities are <strong> tags
     inside the AI Overview container; sources are <a> tags. The container
     is identified by walking up from the show-more button.
"""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag


def _find_real_ai_overview_block(soup: BeautifulSoup) -> Tag | None:
    """Real Google: locate the AI Overview container by walking up from the
    'Show more AI Overview' button. Returns None if not present.

    Strategy: walk up the full ancestor chain and pick the deepest ancestor
    whose subtree contains the most <strong> tags. This is more robust than
    "first ancestor with N strong tags" because Google's markup nests section
    headers and the realtor list in separate sub-blocks at different depths.
    Limit walk to 15 levels to avoid grabbing all of <body>.
    """
    btn = soup.find(attrs={"aria-label": "Show more AI Overview"})
    if btn is None:
        return None
    cur: Tag | None = btn
    best: Tag | None = None
    best_strong_count = 0
    for _ in range(15):
        if cur is None or cur.parent is None:
            break
        cur = cur.parent
        if cur.name in (None, "body", "html"):
            break
        count = len(cur.find_all("strong"))
        if count > best_strong_count:
            best = cur
            best_strong_count = count
    return best


def parse_ai_overview(html: str, entity: str | list[str]) -> dict[str, Any]:
    """Extract structured data from a SERP HTML page.

    `entity` may be a single string or a list of variants (e.g.
    ["Lily Garipova", "Лилия Гарипова"]) to handle the same person rendered
    in different scripts. Position is the 1-indexed first match across variants.

    Returns:
        {
            "ai_overview_present": bool,
            "entity_mentioned": bool,
            "entity_position": int | None,   # 1-indexed; null if not present
            "total_entities_named": int,
            "competitors_named": list[str],  # in order, including the target entity
            "cited_sources": list[str],      # URLs from the AI Overview source chips
            "framing_snippet": str,          # ~200 chars around the entity for downstream diff
        }
    """
    soup = BeautifulSoup(html, "html.parser")

    # First try the synthetic fixture format (used by unit tests).
    block = soup.find(attrs={"data-attrid": "AIOverview"})
    name_tag = "b"
    summary: Tag | None = None
    if block is not None:
        summary = block.find(class_="aio-summary")
    else:
        # Fall back to the real Google markup.
        block = _find_real_ai_overview_block(soup)
        name_tag = "strong"
        # In real Google markup the "summary" is the whole block.
        summary = block

    if block is None:
        return {
            "ai_overview_present": False,
            "entity_mentioned": False,
            "entity_position": None,
            "total_entities_named": 0,
            "competitors_named": [],
            "cited_sources": [],
            "framing_snippet": "",
        }

    summary_text = (
        summary.get_text(" ", strip=True) if summary else block.get_text(" ", strip=True)
    )

    # Named entities live in <b> (fixture) or <strong> (real Google) tags,
    # BUT real Google's AI Overview is inconsistent — sometimes realtor names
    # are <strong>, sometimes only plain <a> links to their website. So we
    # collect candidate names from BOTH source types in document order, filter
    # for "looks like a person name", and de-duplicate.
    #
    # Real Google's strong tags can include:
    #   - a trailing colon ("Lily Garipova:")
    #   - a parenthetical region qualifier ("Lily Garipova (East Bay & South Bay)")
    #   - section headers ("San Francisco & The Peninsula", "How to Choose")
    # Strip the parenthetical and trailing colon FIRST, then apply header filter.
    # Heuristics validated 2026-05-16 against the live SERP for the canonical
    # "best russian speaking realtor bay area" query.
    import re

    HEADER_PREFIXES = ("how ", "what ", "why ", "when ", "where ", "top ", "best ")
    # UI-label denylist for anchors — short link texts that aren't realtor names.
    UI_LABELS = {
        "facebook", "whatsapp", "x", "twitter", "email", "linkedin", "instagram",
        "privacy policy", "terms", "read more", "show more", "show less",
        "learn more", "more info", "yelp", "zillow", "realtor.com", "compass",
    }

    def _is_candidate_name(text: str) -> bool:
        """Heuristic: does this look like a realtor's full name?"""
        if not text or len(text) < 5 or len(text) > 60:
            return False
        if text.lower() in UI_LABELS:
            return False
        # Must contain a space (multi-word — first + last name minimum).
        if " " not in text:
            return False
        # No URL-like content.
        if text.lower().startswith(("http", "www.")):
            return False
        return True

    def _normalize(raw: str) -> str:
        """Strip parenthetical region qualifiers and trailing punctuation."""
        n = re.sub(r"\s*\([^)]*\)\s*", " ", raw).strip()
        return n.rstrip(":,.").strip()

    # Build an ordered list of (kind, text, dom_position) from strongs + anchors.
    candidates: list[tuple[int, str, str]] = []  # (dom_idx, kind, normalized_name)
    descendants = list(summary.descendants) if summary else []

    for dom_idx, el in enumerate(descendants):
        if not hasattr(el, "name") or el.name not in (name_tag, "a"):
            continue
        text = el.get_text(" ", strip=True)
        n = _normalize(text)
        if not n or len(n) < 3 or n.isdigit():
            continue
        if "&" in n or "/" in n:
            continue
        if n.lower().startswith(HEADER_PREFIXES):
            continue
        # For anchors, apply the candidate-name heuristic. For strongs, only
        # require the basic filters above (strongs in AI Overview lists are
        # usually entities already, sometimes single-word like "Lily").
        if el.name == "a" and not _is_candidate_name(n):
            continue
        candidates.append((dom_idx, el.name, n))

    # De-duplicate by name (case-insensitive), preserving first-occurrence order.
    seen_lower: set[str] = set()
    names: list[str] = []
    for _, _, n in candidates:
        key = n.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        names.append(n)

    # Accept entity as string or list of variants (e.g. EN + RU forms).
    entity_variants = [entity] if isinstance(entity, str) else list(entity)
    entity_lower = [e.lower() for e in entity_variants]

    entity_position: int | None = None
    for i, name in enumerate(names, start=1):
        if any(v in name.lower() for v in entity_lower):
            entity_position = i
            break

    sources = [a.get("href", "") for a in block.find_all("a") if a.get("href")]

    snippet = ""
    summary_text_lower = summary_text.lower()
    for variant, variant_lower in zip(entity_variants, entity_lower):
        if variant_lower in summary_text_lower:
            idx = summary_text_lower.index(variant_lower)
            start = max(0, idx - 80)
            end = min(len(summary_text), idx + len(variant) + 120)
            snippet = summary_text[start:end]
            break

    return {
        "ai_overview_present": True,
        "entity_mentioned": entity_position is not None,
        "entity_position": entity_position,
        "total_entities_named": len(names),
        "competitors_named": names,
        "cited_sources": sources,
        "framing_snippet": snippet,
    }
