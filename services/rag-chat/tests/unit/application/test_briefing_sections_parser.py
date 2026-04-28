"""PLAN-0049 T-A-1-04 — _parse_sections_from_markdown contract tests.

Pin the parser's behaviour: when given a clean ``## DETAILS`` block split into
``### Drivers`` / ``### Risks`` etc., it produces a structured ``BriefSection[]``
payload. When given malformed or unstructured markdown, it returns ``[]`` so the
frontend falls back to ``<MarkdownContent>`` over narrative — never breaks.
"""

from __future__ import annotations

import pytest
from rag_chat.api.schemas import BriefSection
from rag_chat.application.use_cases.generate_briefing import _parse_sections_from_markdown


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
        for s in sections:
            BriefSection(**s)

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
