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
        "**Tape**\n"
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
    legacy = "**Tape**\n" "- SPY +0.2% [N1]\n" "**Your Portfolio Today**\n" "- AAPL flat [N2]\n"
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
        "**Tape**\n"
        "- SPY [N1]\n"
    )
    summary, _ = parser.split_summary_paragraph(content)
    assert summary is not None
    assert "[N1]" not in summary
    assert "[c3]" not in summary
    # The substantive content must survive.
    assert "Dell rally" in summary


def test_split_summary_paragraph_caps_at_300_chars() -> None:
    """Long summary blocks are truncated at sentence boundary ≤300 chars."""
    parser = _make_parser()
    long_sentence = "X" * 350
    content = f"## Summary\n{long_sentence}. Trailing sentence.\n\n## Details\n**Tape**\n- noop\n"
    summary, _ = parser.split_summary_paragraph(content)
    assert summary is not None
    assert len(summary) <= 300


def test_check_section_completeness_all_present() -> None:
    """When all 6 v4.2 sections are present → empty missing list."""
    parser = _make_parser()
    content = (
        "## Summary\nFoo.\n\n## Details\n"
        "**Tape**\n- a [N1]\n"
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
        "**Tape**\n- a\n"
        "**Your Portfolio Today**\n- b\n"
        "**Macro Today**\n- c\n"
        "**News That Matters To You**\n- d\n"
    )
    missing = parser.check_section_completeness(fqa01_sample)
    assert "Risks + Opportunities" in missing
    assert "Bonus context" in missing
    assert "Tape" not in missing


def test_check_section_completeness_empty_content() -> None:
    """Empty content → all 6 sections reported missing (defensive)."""
    parser = _make_parser()
    missing = parser.check_section_completeness("")
    assert len(missing) == 6


def test_split_summary_paragraph_handles_bold_section_heading() -> None:
    """``**Section Name**`` heading terminates the Summary block (no ``## Details`` needed)."""
    parser = _make_parser()
    content = "## Summary\n" "Macro tape mixed but constructive.\n" "\n" "**Tape**\n" "- SPY [N1]\n"
    summary, remainder = parser.split_summary_paragraph(content)
    assert summary is not None
    assert "Macro tape mixed" in summary
    assert "**Tape**" in remainder


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
        "**Tape**\n- SPY +0.2% [N1]\n"
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
    narrative = "**Tape**\n- SPY +0.2% [N1]\n"
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
