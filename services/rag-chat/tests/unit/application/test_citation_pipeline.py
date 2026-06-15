"""Unit tests for PLAN-0062-W4 citation pipeline helpers in generate_briefing.py.

Covers: T-W4-B-02 (_parse_sections_with_citations), T-W4-B-03
(_materialize_brief_citations + _backfill_uncited_bullets), and T-W4-B-04
(_compute_confidence).

WHY SEPARATE FILE: these are module-level helpers, not GenerateBriefingUseCase
methods. Grouping them in a single test file keeps the coverage for the new
citation contract together and makes it easy to find if the pipeline breaks.
"""

from __future__ import annotations

import pytest
from rag_chat.api.schemas import BriefBullet, BriefCitation, BriefSection
from rag_chat.application.use_cases.generate_briefing import (
    _backfill_uncited_bullets,
    _compute_confidence,
    _materialize_brief_citations,
    _parse_sections_with_citations,
    _truncate_at_sentence,
)

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _cit(doc_id: str, snippet: str = "Some evidence.") -> BriefCitation:
    """Convenience builder for BriefCitation objects."""
    return BriefCitation(document_id=doc_id, snippet=snippet)


def _make_context_citations(n: int = 5) -> list[BriefCitation]:
    """Build a list of n test BriefCitation objects (c1..cN)."""
    return [_cit(f"doc-{i + 1}", f"Snippet for item {i + 1}.") for i in range(n)]


# ── _parse_sections_with_citations ────────────────────────────────────────────


class TestParseSectionsWithCitations:
    def test_parses_lead_and_details(self) -> None:
        """Happy path: LEAD block + --- + DETAILS block parsed correctly."""
        md = """## LEAD
Tech rallied 2% on strong jobs data. [c1]

---

## DETAILS
### Market Overview
- S&P 500 rose 1.5% in early trading [c1]
- 10Y Treasury yield fell 5bp [c2]

### Key Drivers
- Apple up 3% on analyst upgrade [c1]
- Bond market rally continued [c2]
"""
        ctx_cits = _make_context_citations(5)
        lead, lead_cits, sections = _parse_sections_with_citations(md, ctx_cits)

        # Lead must be non-None and contain the text
        assert lead is not None
        assert "Tech rallied" in lead
        # Lead citations resolved from [c1]
        assert len(lead_cits) == 1
        assert lead_cits[0].document_id == "doc-1"
        # Two sections parsed
        assert len(sections) == 2
        assert sections[0].title == "Market Overview"

    def test_lead_without_valid_citations_returns_none_lead(self) -> None:
        """Lead with only out-of-range [cN] → lead=None (no evidence for lead)."""
        md = """## LEAD
Some claim without valid source. [c99]

---

## DETAILS
### Drivers
- Bullet A [c1]
- Bullet B [c2]
"""
        ctx_cits = _make_context_citations(3)
        lead, lead_cits, _sections = _parse_sections_with_citations(md, ctx_cits)
        # [c99] is out of range (only 3 citations available) → lead=None
        assert lead is None
        assert lead_cits == []

    def test_no_divider_returns_empty(self) -> None:
        """No --- divider → all three outputs are empty/None (legacy single-block)."""
        md = "### Some Section\n- A bullet\n- Another bullet\n"
        ctx_cits = _make_context_citations(3)
        lead, lead_cits, sections = _parse_sections_with_citations(md, ctx_cits)
        assert lead is None
        assert lead_cits == []
        assert sections == []

    def test_empty_markdown_returns_empty(self) -> None:
        """Empty or whitespace-only input returns empty outputs."""
        for md in ("", "   \n  \n"):
            lead, _lead_cits, sections = _parse_sections_with_citations(md, [])
            assert lead is None
            assert sections == []

    def test_bullet_cn_markers_stripped_from_display_text(self) -> None:
        """[cN] markers are stripped from bullet display text."""
        md = """## LEAD
Lead text. [c1]

---

## DETAILS
### Section A
- Bullet text with citation [c1]
- Another bullet [c2]
"""
        ctx_cits = _make_context_citations(3)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        assert sections
        first_bullet = sections[0].bullets[0]
        # Display text must NOT contain [c1]
        assert "[c1]" not in first_bullet.text
        assert first_bullet.text.strip() == "Bullet text with citation"

    def test_template_placeholder_leak_stripped_d_r4_002(self) -> None:
        """D-R4-002: Jinja template variable names occasionally echoed by the LLM
        as bracketed tokens (e.g. [relationships_context]) must be stripped from
        bullet text and lead before reaching the frontend.
        """
        md = """## LEAD
Apple's quarterly trajectory remains positive [c1] [relationships_context].

---

## DETAILS
### Strategic relationships
- TSMC supply commitment underpins iPhone margin [relationships_context] [c1]
- Microsoft Azure dependency on the Apple silicon roadmap [entity_context]
### News
- Latest earnings beat consensus by 4% [news_context] [c2]
"""
        ctx_cits = _make_context_citations(3)
        lead, _lead_cits, sections = _parse_sections_with_citations(md, ctx_cits)
        # Lead must have no bracketed template token left
        assert lead is not None
        for token in (
            "[relationships_context]",
            "[entity_context]",
            "[news_context]",
            "[fundamentals_context]",
            "[events_context]",
        ):
            assert token not in lead, f"lead leaked {token}"
        assert sections, "sections must parse"
        for section in sections:
            for bullet in section.bullets:
                for token in (
                    "[relationships_context]",
                    "[entity_context]",
                    "[news_context]",
                    "[fundamentals_context]",
                    "[events_context]",
                ):
                    assert token not in bullet.text, f"bullet leaked {token}"

    def test_bullet_citations_resolved_correctly(self) -> None:
        """[c2] marker resolves to the second context citation (1-indexed)."""
        md = """## LEAD
Lead. [c1]

---

## DETAILS
### Section X
- Uses second source [c2]
- Uses first source [c1]
"""
        ctx_cits = _make_context_citations(5)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        assert sections
        first_bullet = sections[0].bullets[0]
        assert first_bullet.citations[0].document_id == "doc-2"

    def test_out_of_range_cn_skipped_per_bullet(self) -> None:
        """An out-of-range [cN] in a bullet is skipped (not the whole bullet)."""
        md = """## LEAD
Lead. [c1]

---

## DETAILS
### Section
- Bullet with valid + invalid refs [c1][c99]
- Another valid bullet [c2]
"""
        ctx_cits = _make_context_citations(3)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        assert sections
        first_bullet = sections[0].bullets[0]
        # Only [c1] resolved (c99 out of range)
        assert len(first_bullet.citations) == 1
        assert first_bullet.citations[0].document_id == "doc-1"

    def test_section_bullets_without_citations_dropped(self) -> None:
        """Bullets with NO valid [cN] markers are dropped at construction time.

        WHY 2 sections: the single-section/single-bullet guard discards the result
        if there's only 1 section with ≤1 bullet (mis-parsed prose prevention).
        We use 2 sections to ensure the result is NOT discarded by that guard, so
        we can verify that uncited bullets are filtered within a section.
        """
        md = """## LEAD
Lead. [c1]

---

## DETAILS
### Section A
- Cited bullet [c1]
- Uncited bullet with no markers

### Section B
- Another cited bullet [c2]
- Also cited [c1]
"""
        ctx_cits = _make_context_citations(3)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        # Both sections exist; Section A has only 1 bullet (uncited dropped)
        assert sections
        assert len(sections[0].bullets) == 1
        assert "Cited bullet" in sections[0].bullets[0].text

    def test_lead_truncated_at_sentence_boundary(self) -> None:
        """Lead longer than 600 chars is truncated at a sentence boundary."""
        long_sentence = "A" * 300 + ". "
        lead_text = long_sentence * 3  # > 600 chars
        md = f"## LEAD\n{lead_text.strip()} [c1]\n\n---\n\n## DETAILS\n### S\n- B [c1]\n- B2 [c2]\n"
        ctx_cits = _make_context_citations(3)
        lead, _, _ = _parse_sections_with_citations(md, ctx_cits)
        assert lead is not None
        assert len(lead) <= 600

    def test_max_4_sections_enforced(self) -> None:
        """At most 4 sections are returned even if the LLM emits more."""
        sections_md = "\n".join(
            f"### Section {i}\n- Bullet {i} [c1]\n- Bullet {i}b [c2]\n"
            for i in range(6)  # 6 sections — should be capped at 4
        )
        md = f"## LEAD\nLead. [c1]\n\n---\n\n## DETAILS\n{sections_md}"
        ctx_cits = _make_context_citations(5)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        assert len(sections) <= 4

    def test_max_4_bullets_per_section_enforced(self) -> None:
        """At most 4 bullets per section are returned."""
        bullets_md = "\n".join(f"- Bullet {i} [c1]" for i in range(8))
        md = f"## LEAD\nLead. [c1]\n\n---\n\n## DETAILS\n### Single\n{bullets_md}\n\n### Other\n- B [c1]\n- B2 [c2]\n"
        ctx_cits = _make_context_citations(5)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        assert sections
        assert len(sections[0].bullets) <= 4

    def test_single_section_single_bullet_discarded(self) -> None:
        """Single-section / single-bullet result is discarded (mis-parsed prose guard)."""
        md = "## LEAD\nLead. [c1]\n\n---\n\n## DETAILS\n### Single\n- Only bullet [c1]\n"
        ctx_cits = _make_context_citations(3)
        _, _, sections = _parse_sections_with_citations(md, ctx_cits)
        assert sections == []

    def test_v22_summary_header_also_stripped(self) -> None:
        """## SUMMARY (v2.2 LLM output) is treated like ## LEAD for back-compat."""
        md = """## SUMMARY
Old-style summary. [c1]

---

## DETAILS
### Drivers
- Bullet A [c1]
- Bullet B [c2]
"""
        ctx_cits = _make_context_citations(3)
        lead, _lead_cits, _sections = _parse_sections_with_citations(md, ctx_cits)
        # The SUMMARY block becomes the lead
        assert lead is not None
        assert "Old-style summary" in lead


# ── _materialize_brief_citations ─────────────────────────────────────────────


class TestMaterializeBriefCitations:
    def _article(self, idx: int) -> object:
        """Mock news article object."""
        from unittest.mock import MagicMock

        a = MagicMock()
        a.article_id = f"art-{idx}"
        a.title = f"Article {idx} Title"
        a.summary = f"Summary of article {idx}."
        a.url = f"https://news.example.com/article-{idx}"
        a.published_at = None
        a.display_relevance_score = None
        return a

    def _event(self, idx: int) -> object:
        from unittest.mock import MagicMock

        ev = MagicMock()
        ev.event_id = f"evt-{idx}"
        ev.event_type = "EARNINGS"
        ev.event_text = f"Event text for event {idx}."
        ev.event_date = None
        return ev

    def _alert(self, idx: int) -> object:
        from unittest.mock import MagicMock

        al = MagicMock()
        al.alert_id = f"alt-{idx}"
        al.severity = "HIGH"
        al.alert_type = "PRICE_MOVE"
        al.payload = {"message": f"Alert message {idx}"}
        return al

    def _ctx(self, articles: int = 2, events: int = 1, alerts: int = 1) -> object:
        from unittest.mock import MagicMock

        ctx = MagicMock()
        ctx.news_articles = [self._article(i) for i in range(articles)]
        ctx.recent_events = [self._event(i) for i in range(events)]
        ctx.active_alerts = [self._alert(i) for i in range(alerts)]
        return ctx

    def test_none_context_returns_empty(self) -> None:
        """None ctx → empty list (no citations to materialize)."""
        assert _materialize_brief_citations(None) == []

    def test_articles_come_first(self) -> None:
        """News articles are indexed first (c1, c2, …) — must match format order."""
        ctx = self._ctx(articles=2, events=1, alerts=0)
        cits = _materialize_brief_citations(ctx)
        # First 2 are articles
        assert cits[0].source_type == "article"
        assert cits[1].source_type == "article"

    def test_events_come_after_articles(self) -> None:
        """Events are indexed after articles — c(N+1) where N = num articles."""
        ctx = self._ctx(articles=2, events=2, alerts=0)
        cits = _materialize_brief_citations(ctx)
        assert cits[2].source_type == "event"
        assert cits[3].source_type == "event"

    def test_alerts_come_last(self) -> None:
        """Alerts are indexed after events."""
        ctx = self._ctx(articles=1, events=1, alerts=1)
        cits = _materialize_brief_citations(ctx)
        assert cits[0].source_type == "article"
        assert cits[1].source_type == "event"
        assert cits[2].source_type == "alert"

    def test_snippet_built_from_title_and_summary(self) -> None:
        """Article snippet = title[:240] + ' — ' + summary[:160]."""
        ctx = self._ctx(articles=1, events=0, alerts=0)
        cits = _materialize_brief_citations(ctx)
        assert "Article 0 Title" in cits[0].snippet
        assert "Summary of article 0" in cits[0].snippet

    def test_snippet_capped_at_400(self) -> None:
        """All snippets respect the max_length=400 BriefCitation constraint."""
        ctx = self._ctx(articles=3, events=3, alerts=2)
        for cit in _materialize_brief_citations(ctx):
            assert len(cit.snippet) <= 400


# ── KG definition/narrative as citable sources (PLAN-0107 follow-up) ──────────


class TestKGDescriptionCitations:
    """The instrument-brief KG definition + narrative must become citable [cN].

    Root cause this guards: previously ``materialize_brief_citations`` only
    numbered news/events/alerts, so an Entity Overview bullet grounded on the
    KG definition/narrative had no valid [cN] to cite and was dropped as uncited
    by ``backfill_uncited_bullets`` — the Overview rendered with 0 bullets.
    """

    def _instrument_ctx(
        self,
        *,
        articles: int = 2,
        events: int = 1,
        description: str | None = "Apple designs and sells consumer electronics, software, and services.",
        narrative: str | None = "Competes with Samsung and Google; growing AI and services exposure.",
    ) -> object:
        """Build a REAL BriefingContext instrument ctx (not a MagicMock).

        We use real domain objects so the strict ``isinstance(EntityGraphSnapshot)``
        guard in materialize_brief_citations activates (MagicMock ctx would be
        excluded — that exclusion is the morning-brief safety property).
        """
        from datetime import UTC, datetime
        from uuid import uuid4

        from rag_chat.application.models.briefing_context import (
            BriefingContext,
            EntityGraphSnapshot,
            EventSummary,
            NewsArticleSummary,
        )
        from rag_chat.domain.enums import BriefingType

        news = [
            NewsArticleSummary(
                article_id=uuid4(),
                title=f"Apple headline {i}",
                url=f"https://news.example.com/{i}",
            )
            for i in range(articles)
        ]
        evs = [
            EventSummary(
                event_id=uuid4(),
                event_type="EARNINGS",
                subject_entity_id=uuid4(),
                event_text=f"Apple event {i}",
                extraction_confidence=0.9,
            )
            for i in range(events)
        ]
        eg = EntityGraphSnapshot(
            entity_id="ent-apple",
            canonical_name="Apple Inc.",
            entity_type="company",
            ticker="AAPL",
            description=description,
            relationships=[],
        )
        return BriefingContext(
            briefing_type=BriefingType.INSTRUMENT,
            entity_id="ent-apple",
            news_articles=news,
            active_alerts=[],
            quotes={},
            recent_events=evs,
            entity_graph=eg,
            entity_narrative=narrative,
            gathered_at=datetime.now(tz=UTC),
        )

    def test_definition_and_narrative_appended_after_news_events(self) -> None:
        """KG definition + narrative get the NEXT [cN] indices after news+events."""
        ctx = self._instrument_ctx(articles=2, events=1)
        cits = _materialize_brief_citations(ctx)
        # 2 news (c1,c2) + 1 event (c3) + definition (c4) + narrative (c5)
        assert len(cits) == 5
        assert cits[0].source_type == "article"
        assert cits[1].source_type == "article"
        assert cits[2].source_type == "event"
        # definition + narrative are last, carry the human KG labels
        assert cits[3].title == "Entity definition (KG)"
        assert "consumer electronics" in cits[3].snippet
        assert cits[4].title == "Thematic context (KG)"
        assert "Samsung" in cits[4].snippet
        # narrative snippet carries the staleness caveat
        assert "not a recent catalyst" in cits[4].snippet

    def test_formatter_advertises_same_indices_as_resolver(self) -> None:
        """The [cN] the formatter prints == the index the parser resolves (no mismatch)."""
        from rag_chat.application.use_cases.brief_context_formatter import (
            BriefContextFormatter,
        )

        ctx = self._instrument_ctx(articles=2, events=1)
        formatter = BriefContextFormatter()
        entity_text = formatter.format_entity_context(ctx)
        # Definition advertised at [c4], narrative at [c5] (after 2 news + 1 event).
        assert "[c4] Definition (business identity)" in entity_text
        assert "[c5] Background thematic context" in entity_text

        # The parser resolves those exact markers to the KG citations.
        cits = _materialize_brief_citations(ctx)
        assert cits[3].title == "Entity definition (KG)"  # index 3 == [c4]
        assert cits[4].title == "Thematic context (KG)"  # index 4 == [c5]

    def test_overview_bullet_citing_definition_is_not_dropped(self) -> None:
        """An Entity Overview bullet citing the definition [c4] survives backfill."""
        ctx = self._instrument_ctx(articles=2, events=1)
        cits = _materialize_brief_citations(ctx)
        # LLM output: Entity Overview opens from the definition [c4] + narrative [c5].
        markdown = (
            "## LEAD\n"
            "Apple is a consumer-electronics leader. [c4]\n\n"
            "---\n\n"
            "## DETAILS\n"
            "### Entity Overview\n"
            "- Apple designs and sells consumer electronics and services. [c4]\n"
            "- Strong AI and services thematic exposure versus Samsung and Google. [c5]\n"
        )
        _lead, _lead_cits, sections = _parse_sections_with_citations(markdown, cits)
        sections = _backfill_uncited_bullets(sections, cits)
        # The Entity Overview section survived with BOTH bullets (not dropped).
        assert len(sections) == 1
        assert sections[0].title == "Entity Overview"
        assert len(sections[0].bullets) == 2
        # The bullets resolved to the KG citations.
        assert sections[0].bullets[0].citations[0].title == "Entity definition (KG)"
        assert sections[0].bullets[1].citations[0].title == "Thematic context (KG)"

    def test_definition_only_when_narrative_absent(self) -> None:
        """Missing narrative → only the definition citation is appended (no gap)."""
        ctx = self._instrument_ctx(articles=1, events=0, narrative=None)
        cits = _materialize_brief_citations(ctx)
        # 1 news (c1) + definition (c2); no narrative citation.
        assert len(cits) == 2
        assert cits[1].title == "Entity definition (KG)"
        # Formatter advertises the definition at [c2] (after the single news item).
        from rag_chat.application.use_cases.brief_context_formatter import (
            BriefContextFormatter,
        )

        entity_text = BriefContextFormatter().format_entity_context(ctx)
        assert "[c2] Definition (business identity)" in entity_text
        assert "Background thematic context" not in entity_text


# ── morning-brief numbering must NOT regress ──────────────────────────────────


class TestMorningNumberingUnchanged:
    """Morning-brief contexts (no entity_graph / narrative) must be byte-identical.

    The KG-citation addition is guarded by ``isinstance(EntityGraphSnapshot)`` +
    ``isinstance(str)`` so morning ctx (and MagicMock ctx) never gain KG items.
    """

    def _morning_ctx(self) -> object:
        from unittest.mock import MagicMock

        a = MagicMock()
        a.article_id = "art-1"
        a.title = "Morning headline"
        a.summary = "Summary."
        a.url = "https://x/1"
        a.published_at = None
        a.display_relevance_score = None
        ev = MagicMock()
        ev.event_id = "evt-1"
        ev.event_type = "MACRO"
        ev.event_text = "CPI print."
        ev.event_date = None
        ctx = MagicMock()
        ctx.news_articles = [a]
        ctx.recent_events = [ev]
        ctx.active_alerts = []
        # MagicMock auto-attributes: entity_graph + entity_narrative are Mocks,
        # NOT EntityGraphSnapshot / str — so they are excluded by the guards.
        return ctx

    def test_morning_ctx_gets_no_kg_citations(self) -> None:
        """A morning-style MagicMock ctx yields ONLY news + event citations."""
        ctx = self._morning_ctx()
        cits = _materialize_brief_citations(ctx)
        assert len(cits) == 2
        assert cits[0].source_type == "article"
        assert cits[1].source_type == "event"
        # No KG label leaked in.
        assert all(c.title not in ("Entity definition (KG)", "Thematic context (KG)") for c in cits)


# ── _backfill_uncited_bullets ─────────────────────────────────────────────────


class TestBackfillUncitedBullets:
    def _section_with_bullets(self, n: int) -> BriefSection:
        cits = [BriefCitation(document_id=f"d{i}", snippet="s") for i in range(n)]
        bullets = [BriefBullet(text=f"Bullet {i}", citations=[cit]) for i, cit in enumerate(cits)]
        return BriefSection(title="Section", bullets=bullets)

    def test_sections_with_bullets_pass_through(self) -> None:
        """Sections that already have cited bullets are returned unchanged."""
        sections = [self._section_with_bullets(2)]
        result = _backfill_uncited_bullets(sections, [_cit("d1")])
        assert len(result) == 1
        assert len(result[0].bullets) == 2

    def test_empty_section_dropped(self) -> None:
        """Sections with 0 BriefBullets are dropped (all their bullets were uncited)."""
        empty_section = BriefSection(title="Empty", bullets=[])
        good_section = self._section_with_bullets(2)
        result = _backfill_uncited_bullets([empty_section, good_section], [_cit("d1")])
        assert len(result) == 1
        assert result[0].title == "Section"

    def test_no_context_citations_drops_all(self) -> None:
        """No context citations → all sections dropped (can't guarantee coverage)."""
        result = _backfill_uncited_bullets([self._section_with_bullets(2)], [])
        assert result == []

    def test_multiple_sections_some_empty(self) -> None:
        """Only sections with ≥1 bullet survive."""
        sections = [
            BriefSection(title="Empty1", bullets=[]),
            self._section_with_bullets(1),
            BriefSection(title="Empty2", bullets=[]),
        ]
        result = _backfill_uncited_bullets(sections, [_cit("d1")])
        assert len(result) == 1
        assert result[0].title == "Section"


# ── _compute_confidence ────────────────────────────────────────────────────────


class TestComputeConfidence:
    def _bullet_with_cit(self) -> BriefBullet:
        return BriefBullet(text="Bullet text.", citations=[_cit("d1")])

    def _section(self, n_bullets: int = 2) -> BriefSection:
        return BriefSection(
            title="S",
            bullets=[self._bullet_with_cit() for _ in range(n_bullets)],
        )

    def test_perfect_confidence(self) -> None:
        """All bullets cited + valid lead + ≥8 citations = confidence near 1.0."""
        # 4 sections x 4 bullets = 16 citations -> coverage_factor = 1.0
        sections = [self._section(4) for _ in range(4)]
        lead = "Great market today. [c1]"
        lead_cits = [_cit("d1")]
        conf = _compute_confidence(sections, lead, lead_cits)
        assert 0.9 <= conf <= 1.0

    def test_no_bullets_no_lead(self) -> None:
        """No bullets, no lead → confidence = 0.0."""
        conf = _compute_confidence([], None, [])
        assert conf == 0.0

    def test_lead_without_citations_reduces_score(self) -> None:
        """Lead present but no lead_citations → lead_density=0 → lower score."""
        sections = [self._section(4)]
        # lead with no cits → lead_density = 0
        conf_no_lead = _compute_confidence(sections, None, [])
        conf_with_lead = _compute_confidence(sections, "Lead text.", [_cit("d1")])
        # Having a valid lead should increase confidence
        assert conf_with_lead > conf_no_lead

    def test_confidence_is_in_0_to_1(self) -> None:
        """Confidence must always be in [0.0, 1.0]."""
        # Stress with maximal inputs
        sections = [self._section(4) for _ in range(4)]
        lead_cits = [_cit(f"d{i}") for i in range(8)]
        conf = _compute_confidence(sections, "Lead.", lead_cits)
        assert 0.0 <= conf <= 1.0

    def test_few_total_citations_reduces_coverage_factor(self) -> None:
        """Fewer than 8 total citations → coverage_factor < 1.0 → lower confidence."""
        # 2 bullets x 1 citation each = 2 total citations -> coverage = 2/8 = 0.25
        sections = [BriefSection(title="S", bullets=[self._bullet_with_cit(), self._bullet_with_cit()])]
        conf = _compute_confidence(sections, "Lead.", [_cit("d1")])
        # With coverage_factor=3/8 and composite≈1.0, expected ≈ 3/8 = 0.375
        assert conf < 0.5

    def test_confidence_rounded_to_4_decimals(self) -> None:
        """Confidence value is rounded to 4 decimal places."""
        sections = [self._section(2)]
        lead_cits = [_cit("d1")]
        conf = _compute_confidence(sections, "Lead.", lead_cits)
        # 4 decimal places → str representation has ≤4 dp
        assert conf == round(conf, 4)


# ── _truncate_at_sentence ─────────────────────────────────────────────────────


class TestTruncateAtSentence:
    def test_short_text_unchanged(self) -> None:
        assert _truncate_at_sentence("Short text.", 600) == "Short text."

    def test_truncates_at_period(self) -> None:
        text = "First sentence. " + "A" * 600 + " trailing."
        result = _truncate_at_sentence(text, 600)
        assert result.endswith("First sentence.")
        assert len(result) <= 600

    def test_hard_cut_when_no_boundary(self) -> None:
        """No sentence boundary → hard cut at max_chars."""
        text = "A" * 800  # no periods
        result = _truncate_at_sentence(text, 600)
        assert len(result) <= 601  # allow for … suffix
