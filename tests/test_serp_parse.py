"""Unit tests for scripts.serp_parse.parse_ai_overview.

The parser receives raw HTML of a Google SERP and an entity name to look for.
It returns a structured extraction. Tests use saved fixture HTML so we don't
hit the network and so test outputs are deterministic.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from serp_parse import parse_ai_overview  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_lily_named_first():
    result = parse_ai_overview(
        html=_read("serp_ai_overview_lily_first.html"),
        entity="Lily Garipova",
    )
    assert result["ai_overview_present"] is True
    assert result["entity_mentioned"] is True
    assert result["entity_position"] == 1
    assert result["total_entities_named"] == 5
    assert result["competitors_named"] == [
        "Lily Garipova",
        "Yurii Lavrentiev",
        "Luba Kharchenko",
        "Oleg Verbitski",
        "Lana Tsarikaeva",
    ]
    assert "lilygaripova.com" in str(result["cited_sources"])


def test_entity_not_mentioned():
    result = parse_ai_overview(
        html=_read("serp_ai_overview_no_lily.html"),
        entity="Lily Garipova",
    )
    assert result["ai_overview_present"] is True
    assert result["entity_mentioned"] is False
    assert result["entity_position"] is None
    assert result["total_entities_named"] == 3


def test_no_ai_overview_block():
    result = parse_ai_overview(
        html=_read("serp_no_ai_overview.html"),
        entity="Lily Garipova",
    )
    assert result["ai_overview_present"] is False
    assert result["entity_mentioned"] is False
    assert result["entity_position"] is None
    assert result["total_entities_named"] == 0
