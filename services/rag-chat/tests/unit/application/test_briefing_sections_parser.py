"""PLAN-0049 T-A-1-04 — _parse_sections_from_markdown contract tests.

Pin the parser's behaviour: when given a clean ``## DETAILS`` block split into
``### Drivers`` / ``### Risks`` etc., it produces a structured ``BriefSection[]``
payload. When given malformed or unstructured markdown, it returns ``[]`` so the
frontend falls back to ``<MarkdownContent>`` over narrative — never breaks.

PLAN-0062-W4 adaptation note: BriefSection.bullets is now list[BriefBullet] (not
list[str]). _parse_sections_from_markdown() returns legacy dicts with string bullets
(the function is kept for back-compat during migration). The BriefSection(**s)
assertion has been updated to first adapt the legacy bullet strings into BriefBullet
objects so the test correctly verifies that the dict shapes are structurally valid.
"""

from __future__ import annotations

import pytest
from rag_chat.api.schemas import BriefBullet, BriefCitation, BriefSection
from rag_chat.application.use_cases.generate_briefing import _parse_sections_from_markdown


def _adapt_legacy_section(s: dict) -> dict:  # type: ignore[type-arg]
    """Convert a legacy {title, bullets: list[str]} dict to a BriefSection-valid dict.

    _parse_sections_from_markdown() returns string bullets (legacy format).
    PLAN-0062-W4 changed BriefSection.bullets to list[BriefBullet]. To keep the
    existing structural-validity assertion working, we wrap each string bullet in
    a BriefBullet with a placeholder citation.

    WHY placeholder citation: _parse_sections_from_markdown() is a legacy function
    that doesn't have access to context citations. The adapted form is only used
    in tests to verify the section title/count structure — not the citation content.
    """
    placeholder_citation = BriefCitation(document_id="placeholder", snippet="Legacy parser does not attach citations.")
    return {
        "title": s["title"],
        "bullets": [BriefBullet(text=b, citations=[placeholder_citation]) for b in s["bullets"]],
    }


@pytest.mark.unit
class TestParseSectionsFromMarkdown:
    def test_parses_h3_sections_with_dash_bullets(self) -> None:
        md = """
### Drivers
- Strong Q4 guidance from AAPL
- Fed pause boosts duration

### Risks
- China tariff escalation
- Japanese yen volatility
"""
        sections = _parse_sections_from_markdown(md)
        assert len(sections) == 2
        assert sections[0]["title"] == "Drivers"
        assert sections[0]["bullets"] == [
            "Strong Q4 guidance from AAPL",
            "Fed pause boosts duration",
        ]
        assert sections[1]["title"] == "Risks"
        # Each section payload is valid BriefSection input.
        # WHY _adapt_legacy_section: PLAN-0062-W4 changed BriefSection.bullets to
        # list[BriefBullet]; the legacy parser still returns string bullets so we
        # adapt them to verify the structural contract (title, count) is intact.
        for s in sections:
            BriefSection(**_adapt_legacy_section(s))

    def test_parses_h2_sections_and_star_bullets(self) -> None:
        md = """
## Implications
* Earnings revisions trending up
* Defensive sectors lagging
"""
        sections = _parse_sections_from_markdown(md)
        assert len(sections) == 1
        assert sections[0]["title"] == "Implications"
        assert "Earnings revisions trending up" in sections[0]["bullets"]

    def test_parses_bold_only_pseudo_headings(self) -> None:
        md = """
**Key Drivers**
- One
- Two

**Key Risks**
- Three
- Four
"""
        sections = _parse_sections_from_markdown(md)
        assert len(sections) == 2
        assert sections[0]["title"] == "Key Drivers"
        assert sections[1]["title"] == "Key Risks"

    def test_caps_bullets_at_eight(self) -> None:
        bullets = "\n".join(f"- bullet {i}" for i in range(20))
        md = f"### Many\n{bullets}"
        sections = _parse_sections_from_markdown(md)
        assert len(sections) == 1
        assert len(sections[0]["bullets"]) == 8

    def test_returns_empty_for_unstructured_text(self) -> None:
        md = "This is just a paragraph with no headings or bullets at all."
        assert _parse_sections_from_markdown(md) == []

    def test_returns_empty_for_blank_input(self) -> None:
        assert _parse_sections_from_markdown("") == []
        assert _parse_sections_from_markdown("   \n  \n") == []

    def test_discards_single_bullet_section(self) -> None:
        # Avoids mis-parsing a single sentence as a section.
        md = "### Title\n- only one"
        assert _parse_sections_from_markdown(md) == []

    def test_truncates_long_titles_to_120_chars(self) -> None:
        long_title = "X" * 200
        md = f"### {long_title}\n- a\n- b"
        sections = _parse_sections_from_markdown(md)
        assert sections, "expected one section"
        assert len(sections[0]["title"]) <= 120
