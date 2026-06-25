"""Unit tests for BriefParser (PLAN-0089 C-3).

Covers: parse_sections_from_markdown (legacy), split_summary_and_details,
parse_sections_with_citations, backfill_uncited_bullets, compute_confidence,
materialize_brief_citations, strip_reasoning, and edge-case handling.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rag_chat.application.use_cases.brief_parser import BriefParser
from rag_chat.domain.brief import BriefBullet, BriefCitation, BriefSection

pytestmark = pytest.mark.unit


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_citation(idx: int = 1) -> BriefCitation:
    """Helper to build a minimal valid BriefCitation."""
    return BriefCitation(
        document_id=f"doc-{idx}",
        snippet=f"Snippet text {idx}",
        source_type="article",
        title=f"Article {idx}",
    )


def _make_parser() -> BriefParser:
    return BriefParser()


# ── 1. test_parse_empty_response ───────────────────────────────────────────────


def test_parse_empty_response() -> None:
    """parse_sections_from_markdown returns [] for empty input."""
    parser = _make_parser()
    assert parser.parse_sections_from_markdown("") == []
    assert parser.parse_sections_from_markdown("   \n  \n") == []


# ── 2. test_parse_single_section ──────────────────────────────────────────────


def test_parse_single_section_with_multiple_bullets() -> None:
    """A single section with ≥2 bullets produces one dict entry (not discarded)."""
    parser = _make_parser()
    md = "## Drivers\n- First point\n- Second point\n- Third point"
    sections = parser.parse_sections_from_markdown(md)
    assert len(sections) == 1
    assert sections[0]["title"] == "Drivers"
    assert len(sections[0]["bullets"]) == 3


def test_parse_single_section_one_bullet_discarded() -> None:
    """A single section with only 1 bullet is considered a mis-parse and discarded."""
    parser = _make_parser()
    md = "## Risk\n- Only one bullet"
    # Single section / single bullet → treated as mis-parsed prose
    sections = parser.parse_sections_from_markdown(md)
    assert sections == []


# ── 3. test_parse_multiple_sections ───────────────────────────────────────────


def test_parse_multiple_sections() -> None:
    """Multiple ## headings produce multiple section entries."""
    parser = _make_parser()
    md = (
        "## Drivers\n"
        "- Revenue beats\n"
        "- Margin expansion\n"
        "\n"
        "## Risks\n"
        "- Rate sensitivity\n"
        "- Valuation stretch\n"
    )
    sections = parser.parse_sections_from_markdown(md)
    assert len(sections) == 2
    assert sections[0]["title"] == "Drivers"
    assert sections[1]["title"] == "Risks"
    assert len(sections[0]["bullets"]) == 2
    assert len(sections[1]["bullets"]) == 2


# ── 4. test_parse_with_citations ──────────────────────────────────────────────


def test_parse_sections_with_citations_resolves_cn_markers() -> None:
    """[cN] markers in DETAILS bullets are resolved to BriefCitation objects."""
    parser = _make_parser()
    ctx_cits = [_make_citation(1), _make_citation(2)]
    md = (
        "## LEAD\n"
        "Apple beat estimates [c1].\n"
        "---\n"
        "## DETAILS\n"
        "### Drivers\n"
        "- Revenue beat [c1]\n"
        "- Margin up [c2]\n"
    )
    lead, lead_cits, sections = parser.parse_sections_with_citations(md, ctx_cits)
    assert lead is not None
    assert len(lead_cits) == 1
    assert len(sections) == 1
    assert len(sections[0].bullets) == 2
    assert sections[0].bullets[0].citations[0].document_id == "doc-1"
    assert sections[0].bullets[1].citations[0].document_id == "doc-2"


# ── 5. test_parse_malformed_markdown ──────────────────────────────────────────


def test_parse_malformed_markdown_no_divider() -> None:
    """v3.0 parser returns (None, [], []) when there is no --- divider."""
    parser = _make_parser()
    md = "Some prose without a divider line\nAnd more prose"
    lead, lead_cits, sections = parser.parse_sections_with_citations(md, [])
    assert lead is None
    assert lead_cits == []
    assert sections == []


def test_parse_malformed_markdown_no_bullets() -> None:
    """Markdown with headings but no bullet lines produces no sections."""
    parser = _make_parser()
    md = "## Heading\nJust prose here, no bullets at all."
    sections = parser.parse_sections_from_markdown(md)
    # Heading with zero bullets → nothing to flush → []
    assert sections == []


# ── 6. test_parse_empty_sections_skipped ──────────────────────────────────────


def test_backfill_drops_empty_sections() -> None:
    """backfill_uncited_bullets removes sections whose bullets list is empty."""
    parser = _make_parser()
    empty_sec = BriefSection(title="Empty Section", bullets=[])
    ctx_cits = [_make_citation(1)]
    result = parser.backfill_uncited_bullets([empty_sec], ctx_cits)
    assert result == []


def test_backfill_drops_all_when_no_citations() -> None:
    """backfill_uncited_bullets drops everything when context_citations is empty."""
    parser = _make_parser()
    cit = _make_citation(1)
    sec = BriefSection(title="S", bullets=[BriefBullet(text="Bullet", citations=[cit])])
    result = parser.backfill_uncited_bullets([sec], [])
    assert result == []


def test_backfill_passes_through_cited_sections() -> None:
    """Sections that already have bullets with citations are preserved unchanged."""
    parser = _make_parser()
    cit = _make_citation(1)
    sec = BriefSection(title="Good", bullets=[BriefBullet(text="A point", citations=[cit])])
    ctx_cits = [cit]
    result = parser.backfill_uncited_bullets([sec], ctx_cits)
    assert len(result) == 1
    assert result[0].title == "Good"


# ── 7. test_parse_citation_extraction ─────────────────────────────────────────


def test_citation_extraction_out_of_range_skipped() -> None:
    """[cN] markers whose index exceeds the citations list are silently skipped."""
    parser = _make_parser()
    ctx_cits = [_make_citation(1)]  # only index 0 valid
    md = (
        "## LEAD\n"
        "Something [c1].\n"
        "---\n"
        "## DETAILS\n"
        "### Section\n"
        "- Bullet cites [c1] and [c9]\n"  # [c9] is out of range
        "- Another [c1]\n"
    )
    _, _, sections = parser.parse_sections_with_citations(md, ctx_cits)
    # Both bullets cite [c1] → 2 bullets survive; [c9] silently dropped
    assert len(sections) == 1
    assert len(sections[0].bullets) == 2
    assert len(sections[0].bullets[0].citations) == 1  # only c1, c9 dropped


# ── 8. test_parse_fallback_for_plain_text ─────────────────────────────────────


def test_parse_fallback_for_plain_text_no_headings() -> None:
    """Plain text with no headings produces empty section list (frontend fallback)."""
    parser = _make_parser()
    md = "This is just a paragraph of plain text.\nNo structure whatsoever."
    sections = parser.parse_sections_from_markdown(md)
    assert sections == []


# ── 9. test_parse_section_with_header ─────────────────────────────────────────


def test_split_summary_and_details_strips_headers() -> None:
    """split_summary_and_details removes ## SUMMARY / ## DETAILS headings."""
    parser = _make_parser()
    content = "## SUMMARY\nLead sentence.\n\n---\n\n## DETAILS\nBody text here."
    summary, narrative = parser.split_summary_and_details(content)
    assert summary is not None
    assert "## SUMMARY" not in (summary or "")
    assert "## DETAILS" not in narrative
    assert "Lead sentence" in (summary or "")
    assert "Body text" in narrative


def test_split_summary_no_divider_returns_none_summary() -> None:
    """When no --- divider is present, summary is None and narrative is the full text."""
    parser = _make_parser()
    content = "Just a single block of text with no divider."
    summary, narrative = parser.split_summary_and_details(content)
    assert summary is None
    assert narrative == content


def test_split_empty_content_returns_none_full() -> None:
    """Empty content returns (None, '')."""
    parser = _make_parser()
    summary, narrative = parser.split_summary_and_details("")
    assert summary is None
    assert narrative == ""


# ── 10. test_parse_handles_none_input ─────────────────────────────────────────


def test_parse_sections_with_citations_none_markdown() -> None:
    """parse_sections_with_citations returns (None, [], []) for empty/None-like input."""
    parser = _make_parser()
    lead, lead_cits, sections = parser.parse_sections_with_citations("", [])
    assert lead is None
    assert lead_cits == []
    assert sections == []


def test_materialize_brief_citations_none_ctx() -> None:
    """materialize_brief_citations returns [] when ctx is None."""
    parser = _make_parser()
    result = parser.materialize_brief_citations(None)
    assert result == []


def test_materialize_brief_citations_news_ordering() -> None:
    """materialize_brief_citations respects the news → events → alerts ordering."""
    parser = _make_parser()

    article = MagicMock()
    article.article_id = "art-1"
    article.title = "Breaking news"
    article.summary = "Summary text"
    article.url = "https://example.com/article"

    event = MagicMock()
    event.event_id = "ev-1"
    event.event_type = "EARNINGS"
    event.event_text = "Earnings beat"

    ctx = MagicMock()
    ctx.news_articles = [article]
    ctx.recent_events = [event]
    ctx.active_alerts = []

    citations = parser.materialize_brief_citations(ctx)
    assert len(citations) == 2
    assert citations[0].source_type == "article"
    assert citations[1].source_type == "event"


# ── 11. Confidence scoring ─────────────────────────────────────────────────────


def test_compute_confidence_zero_when_no_data() -> None:
    """compute_confidence returns 0 when there are no sections and no lead."""
    parser = _make_parser()
    score = parser.compute_confidence([], None, [])
    assert score == 0.0


def test_compute_confidence_high_with_full_data() -> None:
    """compute_confidence returns a value > 0 when lead + multiple cited bullets present."""
    parser = _make_parser()
    cits = [_make_citation(i) for i in range(8)]
    bullets = [BriefBullet(text=f"Point {i}", citations=[cits[i]]) for i in range(4)]
    section = BriefSection(title="Section", bullets=bullets)
    score = parser.compute_confidence([section], lead="Lead text", lead_citations=cits[:2])
    assert score > 0.0
    assert score <= 1.0


# ── 12. strip_reasoning ────────────────────────────────────────────────────────


def test_strip_reasoning_removes_think_tags() -> None:
    """strip_reasoning removes <think>...</think> blocks."""
    parser = _make_parser()
    raw = "<think>Internal reasoning here.</think>\n\nActual content."
    result = parser.strip_reasoning(raw)
    assert "<think>" not in result
    assert "Actual content" in result


def test_strip_reasoning_removes_code_fences() -> None:
    """strip_reasoning removes ```markdown ... ``` fences."""
    parser = _make_parser()
    raw = "```markdown\nActual content here.\n```"
    result = parser.strip_reasoning(raw)
    assert "```" not in result
    assert "Actual content here" in result


def test_strip_reasoning_plain_text_unchanged() -> None:
    """strip_reasoning leaves plain text without think/fence wrappers untouched."""
    parser = _make_parser()
    raw = "Clean plain text with no special wrappers."
    result = parser.strip_reasoning(raw)
    assert result == raw


# ── 13. PLAN-0103 W3 (BP-624): v4.2 ``## Summary`` paragraph split ───────────
# These tests cover ``split_summary_paragraph`` (extracts the leading 1-3
# sentence paragraph for the dashboard collapsed view) and
# ``check_section_completeness`` (post-generation observability gate for the
# 6 mandatory v4.2 sections).


def test_split_summary_paragraph_extracts_v42_block() -> None:
    """v4.2 brief: ``## Summary`` block is extracted as a single paragraph."""
    parser = _make_parser()
    content = (
        "## Summary\n"
        "AI infrastructure momentum continues with Dell up 40%. Volatility "
        "remains contained ahead of NVDA earnings.\n"
        "\n"
        "## Details\n"
        "**Market Snapshot**\n"
        "- SPY +0.20%, QQQ +0.45%, VIX 14.2 [N1]\n"
    )
    summary, remainder = parser.split_summary_paragraph(content)
    assert summary is not None
    assert "Dell up 40%" in summary
    assert "NVDA" in summary
    assert "## Details" in remainder
    # Summary heading must NOT appear in the remainder (it would render twice).
    assert "## Summary" not in remainder


def test_split_summary_paragraph_returns_none_for_legacy_brief() -> None:
    """Legacy v4.1 (no ``## Summary`` heading) → (None, content) — back-compat."""
    parser = _make_parser()
    legacy = "**Market Snapshot**\n" "- SPY +0.2% [N1]\n" "**Your Portfolio Today**\n" "- AAPL flat [N2]\n"
    summary, remainder = parser.split_summary_paragraph(legacy)
    assert summary is None
    assert remainder == legacy


def test_split_summary_paragraph_strips_citation_markers() -> None:
    """[cN]/[N#] markers must be stripped — collapsed view has no chip UI."""
    parser = _make_parser()
    content = (
        "## Summary\n"
        "Tech-heavy holdings benefit from Dell rally [N1][c3].\n"
        "\n"
        "## Details\n"
        "**Market Snapshot**\n"
        "- SPY [N1]\n"
    )
    summary, _ = parser.split_summary_paragraph(content)
    assert summary is not None
    assert "[N1]" not in summary
    assert "[c3]" not in summary
    # The substantive content must survive.
    assert "Dell rally" in summary


def test_split_summary_paragraph_caps_at_1500_chars() -> None:
    """Long summary blocks are truncated at sentence boundary ≤1500 chars.

    PLAN-0103 W11 (v4.5): the parser cap was raised 300 → 1500 chars to
    accommodate the new adaptive Summary length (target ~100 words; up to
    200 words ≈ 1400 chars for large portfolios / very active days).
    Anything below 1500 chars now passes through untrimmed; only runaway
    summaries get cut at the nearest sentence boundary.
    """
    parser = _make_parser()
    # Build a > 1500 char summary so the cap actually fires.
    long_sentence = "X" * 1600
    content = f"## Summary\n{long_sentence}. Trailing sentence.\n\n## Details\n**Market Snapshot**\n- noop\n"
    summary, _ = parser.split_summary_paragraph(content)
    assert summary is not None
    assert len(summary) <= 1500


def test_split_summary_paragraph_preserves_v45_adaptive_length() -> None:
    """A v4.5 ~150-word adaptive Summary (≈1000 chars) passes through untrimmed.

    PLAN-0103 W11: the 300-char cap from v4.4 would truncate the new
    large-portfolio / active-day Summary at the first ~50 words; the 1500-
    char cap MUST let a realistic 1000-char summary survive intact.
    """
    parser = _make_parser()
    # ~1000-char single-paragraph summary (well above old 300 cap, well
    # below new 1500 cap). Sentence-terminated so no truncation would alter it.
    sentence = (
        "AI-infrastructure rally extends overnight and tilts the book constructive: "
        "top-3 by impact MSFT AAPL NVDA should add to a strong open while CPI at "
        "08:30 ET risks re-pricing the duration leg and amplifying drawdown given "
        "top-3 concentration at 38% of the book.  "
    )
    body = (sentence * 4).strip()
    assert 900 < len(body) < 1500  # sanity-check the test data shape
    content = f"## Summary\n{body}\n\n## Details\n**Market Snapshot**\n- noop\n"
    summary, _ = parser.split_summary_paragraph(content)
    assert summary is not None
    # The parser collapses consecutive whitespace, so the result is ~3 chars
    # shorter than the raw input — what matters is that the cap did NOT fire
    # (i.e. the summary is well above 300 chars and below 1500).
    assert 900 < len(summary) <= 1500
    # And the last sentence must still be present (no mid-sentence truncation).
    assert summary.endswith("of the book.")


def test_check_section_completeness_all_present() -> None:
    """When all 6 v4.2 sections are present → empty missing list."""
    parser = _make_parser()
    content = (
        "## Summary\nFoo.\n\n## Details\n"
        "**Market Snapshot**\n- a [N1]\n"
        "**Your Portfolio Today**\n- b [N1]\n"
        "**Macro Today**\n- c [N1]\n"
        "**News That Matters To You**\n- d [N1]\n"
        "**Risks + Opportunities**\n- e\n"
        "**Bonus context**\n- f\n"
    )
    missing = parser.check_section_completeness(content)
    assert missing == []


def test_check_section_completeness_flags_fqa01_pattern() -> None:
    """FQA-01 reproduction: 4 of 6 sections → Risks + Bonus flagged missing."""
    parser = _make_parser()
    fqa01_sample = (
        "**Market Snapshot**\n- a\n"
        "**Your Portfolio Today**\n- b\n"
        "**Macro Today**\n- c\n"
        "**News That Matters To You**\n- d\n"
    )
    missing = parser.check_section_completeness(fqa01_sample)
    assert "Risks + Opportunities" in missing
    assert "Bonus context" in missing
    assert "Market Snapshot" not in missing


def test_check_section_completeness_empty_content() -> None:
    """Empty content → all 6 sections reported missing (defensive)."""
    parser = _make_parser()
    missing = parser.check_section_completeness("")
    assert len(missing) == 6


def test_split_summary_paragraph_handles_bold_section_heading() -> None:
    """``**Section Name**`` heading terminates the Summary block (no ``## Details`` needed)."""
    parser = _make_parser()
    content = "## Summary\n" "Macro tape mixed but constructive.\n" "\n" "**Market Snapshot**\n" "- SPY [N1]\n"
    summary, remainder = parser.split_summary_paragraph(content)
    assert summary is not None
    assert "Macro tape mixed" in summary
    assert "**Market Snapshot**" in remainder


# ── 14. PLAN-0103 W6 (v4.3): defensive section + summary injection ───────────
# These tests cover ``inject_missing_sections`` (appends placeholder lines
# for missing sections in canonical order) and ``inject_missing_summary``
# (synthesises a short lead from the first portfolio/news bullet when LLM
# omits the ``## Summary`` block). Both guarantee the structural contract
# regardless of LLM compliance.


def test_inject_missing_sections_appends_in_canonical_order() -> None:
    """Missing sections are appended in V42_EXPECTED_SECTIONS order — not in `missing` order."""
    parser = _make_parser()
    # LLM only emitted 4 of 6 sections (FQA-01 pattern).
    narrative = (
        "**Market Snapshot**\n- SPY +0.2% [N1]\n"
        "**Your Portfolio Today**\n- AAPL flat [N1]\n"
        "**Macro Today**\n- No prints [N1]\n"
        "**News That Matters To You**\n- Dell up 40% [N1]\n"
    )
    # Deliberately reverse the missing list to prove canonical ordering wins.
    missing = ["Bonus context", "Risks + Opportunities"]
    augmented = parser.inject_missing_sections(narrative, missing)
    # Both placeholders must be present.
    assert "**Risks + Opportunities**" in augmented
    assert "**Bonus context**" in augmented
    assert "No specific items today" in augmented
    # Risks + Opportunities must appear BEFORE Bonus context (canonical order)
    # even though `missing` listed them in reverse.
    risks_idx = augmented.index("**Risks + Opportunities**")
    bonus_idx = augmented.index("**Bonus context**")
    assert risks_idx < bonus_idx, "canonical V4.2 order must win over `missing` order"


def test_inject_missing_sections_no_op_when_all_present() -> None:
    """Empty `missing` list → narrative returned unchanged."""
    parser = _make_parser()
    narrative = "**Market Snapshot**\n- SPY +0.2% [N1]\n"
    out = parser.inject_missing_sections(narrative, [])
    assert out == narrative


def test_inject_missing_summary_extracts_lead_when_omitted() -> None:
    """When LLM omits ``## Summary``, synthesise from the FIRST portfolio bullet."""
    parser = _make_parser()
    # Build a sections payload that mirrors what the citation-aware parser
    # would produce — BriefSection with BriefBullet children.
    cite = _make_citation(1)
    sections = [
        BriefSection(
            title="Your Portfolio Today",
            bullets=[
                BriefBullet(text="AAPL +0.8% pre-mkt on Vision Pro shipment beat", citations=[cite]),
                BriefBullet(text="MSFT flat", citations=[cite]),
            ],
        ),
        BriefSection(
            title="News That Matters To You",
            bullets=[BriefBullet(text="Dell up 40% [N1]", citations=[cite])],
        ),
    ]
    narrative_in = "**Your Portfolio Today**\n- AAPL +0.8% pre-mkt on Vision Pro shipment beat [N1]\n"

    narrative_out, summary = parser.inject_missing_summary(narrative_in, sections, summary_paragraph=None)
    # Narrative passes through unchanged (we never inject into markdown).
    assert narrative_out == narrative_in
    assert summary is not None
    assert summary.startswith("Lead headline: ")
    # The synthesised summary quotes the first portfolio bullet verbatim.
    assert "AAPL" in summary
    assert "Vision Pro" in summary
    # Citation markers must be stripped from the collapsed summary.
    assert "[N1]" not in summary


def test_inject_missing_summary_preserves_existing_summary() -> None:
    """When LLM already emitted a summary, return it untouched."""
    parser = _make_parser()
    cite = _make_citation(1)
    sections = [
        BriefSection(
            title="Your Portfolio Today",
            bullets=[BriefBullet(text="AAPL flat", citations=[cite])],
        ),
    ]
    existing = "Tech rally continues into open."
    _, out = parser.inject_missing_summary("narrative", sections, summary_paragraph=existing)
    assert out == existing


def test_inject_missing_summary_returns_none_when_no_bullets() -> None:
    """No populated sections → cannot synthesise → (narrative, None)."""
    parser = _make_parser()
    _, out = parser.inject_missing_summary("narrative", [], summary_paragraph=None)
    assert out is None


# ── Brief-quality eval 2026-06-14 regression tests ────────────────────────────


def _instrument_ctx_many_events(
    *,
    n_news: int = 7,
    n_events: int = 20,
    with_fundamentals: bool = True,
    narrative_generated_at: str | None = None,
) -> object:
    """Build a REAL instrument BriefingContext (not a MagicMock) with many events.

    The KG/fundamentals citation paths in materialize_brief_citations are
    isinstance-gated on the real dataclasses, so these tests must use the
    concrete models (a MagicMock would skip those branches entirely).
    """
    from datetime import UTC, datetime
    from uuid import uuid4

    from rag_chat.application.models.briefing_context import (
        BriefingContext,
        EntityGraphSnapshot,
        EventSummary,
        FundamentalsSummary,
        NewsArticleSummary,
    )

    eid = "11111111-1111-1111-1111-111111111111"
    news = [
        NewsArticleSummary(
            article_id=uuid4(),
            title=f"Distinct headline number {i}",
            display_relevance_score=0.5,
        )
        for i in range(n_news)
    ]
    events = [
        EventSummary(
            event_id=uuid4(),
            event_type="EVENT",
            subject_entity_id=uuid4(),
            event_text=f"Event body {i}",
            extraction_confidence=0.9,
        )
        for i in range(n_events)
    ]
    eg = EntityGraphSnapshot(
        entity_id=eid,
        canonical_name="Apple Inc.",
        entity_type="company",
        ticker="AAPL",
        description="Apple Inc. designs and markets smartphones and computers.",
        relationships=[],
    )
    fundamentals = (
        FundamentalsSummary(instrument_id="AAPL", data={"MarketCapitalization": 4_310_000_000_000, "PERatio": 35.4})
        if with_fundamentals
        else None
    )
    return BriefingContext.for_instrument(
        entity_id=eid,
        entity_graph=eg,
        fundamentals=fundamentals,
        news_articles=news,
        active_alerts=[],
        quotes={},
        recent_events=events,
        entity_narrative="Apple is a leading consumer-electronics and AI-platform company.",
        entity_narrative_generated_at=narrative_generated_at,
        gathered_at=datetime.now(tz=UTC),
    )


def test_bug1_kg_offset_advertised_equals_resolved_with_many_events() -> None:
    """BUG 1: with 20 events the advertised KG [cN] index == the resolved index.

    Before the fix kg_description_offset capped events at 6 while format_events
    showed up to get_events_limit() (10), so the KG definition marker collided
    with a real event citation. Now both use get_events_limit(), so the KG
    definition/narrative markers the formatter advertises resolve to the KG
    citations in materialize_brief_citations.
    """
    from rag_chat.application.use_cases.brief_context_formatter import (
        BriefContextFormatter,
        get_events_limit,
    )

    parser = _make_parser()
    formatter = BriefContextFormatter()
    ctx = _instrument_ctx_many_events(n_news=7, n_events=20)

    # The formatter advertises the KG definition at offset+1, narrative at +2.
    offset = formatter.kg_description_offset(ctx)
    assert offset == 7 + get_events_limit()  # news + capped events (no alerts)
    entity_text = formatter.format_entity_context(ctx)
    # Extract the [cN] the formatter put on the Definition line.
    import re

    def_marker = re.search(r"\[c(\d+)\] Definition", entity_text)
    narr_marker = re.search(r"\[c(\d+)\] Background thematic", entity_text)
    assert def_marker is not None and narr_marker is not None
    def_idx = int(def_marker.group(1))
    narr_idx = int(narr_marker.group(1))

    # The parser's citation list must resolve those exact indices to the KG items.
    citations = parser.materialize_brief_citations(ctx)
    assert citations[def_idx - 1].title == BriefContextFormatter._KG_DEFINITION_LABEL
    assert citations[narr_idx - 1].title == BriefContextFormatter._KG_NARRATIVE_LABEL


def test_bug1_kg_definition_bullet_resolves_in_full_pipeline() -> None:
    """BUG 1: an Entity Overview bullet citing the KG definition resolves to it."""
    from rag_chat.application.use_cases.brief_context_formatter import (
        BriefContextFormatter,
    )

    parser = _make_parser()
    formatter = BriefContextFormatter()
    ctx = _instrument_ctx_many_events(n_news=7, n_events=20)
    citations = parser.materialize_brief_citations(ctx)
    offset = formatter.kg_description_offset(ctx)
    def_cn = offset + 1  # definition is appended first after news/events/alerts

    markdown = (
        "## LEAD\nApple update [c1]\n\n---\n\n## DETAILS\n"
        "### Entity Overview\n"
        f"- Apple Inc. designs smartphones and computers [c{def_cn}]\n"
        f"- It is a leading AI-platform company [c{def_cn + 1}]\n"
    )
    _, _, sections = parser.parse_sections_with_citations(markdown, citations)
    sections = parser.backfill_uncited_bullets(sections, citations)
    overview = next(s for s in sections if s.title == "Entity Overview")
    titles = {c.title for b in overview.bullets for c in b.citations}
    assert BriefContextFormatter._KG_DEFINITION_LABEL in titles
    assert BriefContextFormatter._KG_NARRATIVE_LABEL in titles


def test_bug2_price_and_fundamentals_section_survives_parsing() -> None:
    """BUG 2: a Price & Fundamentals bullet survives even without a numeric [cN].

    The LLM used to emit the literal [fundamentals_context] token (stripped by
    the parser), leaving the bullet uncited → the whole section was dropped.
    The fundamentals snapshot is now a citable structured-data source, and a
    fundamentals-section bullet with no numeric marker is backed by it rather
    than dropped.
    """
    parser = _make_parser()
    ctx = _instrument_ctx_many_events(with_fundamentals=True)
    citations = parser.materialize_brief_citations(ctx)

    # LLM echoed the placeholder token (the failure mode) on the fundamentals bullet.
    markdown = (
        "## LEAD\nApple update [c1]\n\n---\n\n## DETAILS\n"
        "### Recent Developments\n"
        "- Apple shipped a record quarter [c1]\n"
        "### Price & Fundamentals\n"
        "- Market cap stands at $4.31T; P/E TTM is 35.4 [fundamentals_context]\n"
    )
    _, _, sections = parser.parse_sections_with_citations(markdown, citations)
    sections = parser.backfill_uncited_bullets(sections, citations)
    titles = [s.title for s in sections]
    assert "Price & Fundamentals" in titles
    pf = next(s for s in sections if s.title == "Price & Fundamentals")
    assert len(pf.bullets) == 1
    assert pf.bullets[0].citations  # backed by the fundamentals citation
    assert "fundamentals_context" not in pf.bullets[0].text


def test_bug2_fundamentals_bullet_with_real_cn_marker_resolves() -> None:
    """BUG 2: when the LLM cites the advertised fundamentals [cN] it resolves."""
    from rag_chat.application.use_cases.brief_context_formatter import (
        BriefContextFormatter,
    )

    parser = _make_parser()
    formatter = BriefContextFormatter()
    ctx = _instrument_ctx_many_events(with_fundamentals=True)
    citations = parser.materialize_brief_citations(ctx)
    cn = formatter.fundamentals_citation_index(ctx)
    assert cn is not None
    assert citations[cn - 1].title == BriefContextFormatter._FUNDAMENTALS_LABEL

    markdown = (
        "## LEAD\nApple update [c1]\n\n---\n\n## DETAILS\n"
        "### Recent Developments\n"
        "- Apple shipped a record quarter [c1]\n"
        "### Price & Fundamentals\n"
        f"- Market cap stands at $4.31T [c{cn}]\n"
    )
    _, _, sections = parser.parse_sections_with_citations(markdown, citations)
    sections = parser.backfill_uncited_bullets(sections, citations)
    pf = next(s for s in sections if s.title == "Price & Fundamentals")
    assert pf.bullets[0].citations[0].title == BriefContextFormatter._FUNDAMENTALS_LABEL


def test_bug5_range_marker_stripped_and_not_resolved() -> None:
    """BUG 5: a [cA-cB] range marker is stripped and never leaks as a token."""
    parser = _make_parser()
    citations = [_make_citation(i) for i in range(1, 21)]
    markdown = (
        "## LEAD\nMarket update [c1]\n\n---\n\n## DETAILS\n"
        "### News That Matters To You\n"
        "- Multiple GRAPH_CHANGE alerts fired overnight [c13-c20]\n"
        "- A clean single-cited bullet [c2]\n"
        "### Risks + Opportunities\n"
        "- Concentration risk remains elevated [c3]\n"
        "- Watch the macro print today [c4]\n"
    )
    _, _, sections = parser.parse_sections_with_citations(markdown, citations)
    sections = parser.backfill_uncited_bullets(sections, citations)
    all_text = " ".join(b.text for s in sections for b in s.bullets)
    # The range marker must NOT appear in any rendered bullet text.
    assert "c13-c20" not in all_text
    assert "[c" not in all_text  # all singular markers stripped from display text too
    # The range-marker bullet had no resolvable singular cite → dropped (no
    # fabricated citation); the clean [c2] bullet survives.
    news = next(s for s in sections if s.title == "News That Matters To You")
    assert any("clean single-cited" in b.text for b in news.bullets)
    assert not any("GRAPH_CHANGE" in b.text for b in news.bullets)


def test_bug5_range_regex_strips_ascii_and_unicode_dashes() -> None:
    """BUG 5: the range-marker regex removes [cA-cB] with ASCII and unicode dashes.

    The displayed morning-brief narrative (no ``---`` divider) renders this raw
    text, so the regex (applied in generate_briefing) must catch every dash form
    the model emits while leaving singular [cN] markers untouched.
    """
    from rag_chat.application.use_cases.brief_parser import _CN_RANGE_MARKER_RE

    samples = [
        "Multiple alerts [c13-c20] fired",
        "Multiple alerts [c13–c20] fired",  # en dash  # noqa: RUF001
        "Multiple alerts [c13—c20] fired",  # em dash
        "Bare numbers [c13-20] fired",
    ]
    for s in samples:
        assert "c13" not in _CN_RANGE_MARKER_RE.sub("", s), s
    # Singular markers must NOT be touched by the range regex.
    keep = "A clean bullet [c2] and [c7] here"
    assert _CN_RANGE_MARKER_RE.sub("", keep) == keep
