"""Unit tests for BriefCitation + BriefBullet + updated BriefSection (PLAN-0062-W4).

WHY THESE TESTS: Wave A adds two new Pydantic models and modifies BriefSection.bullets
from list[str] to list[BriefBullet].  These tests pin the schema contracts so any
accidental regression (e.g. reverting min_length, swapping field types) trips CI
immediately rather than silently shipping a broken response shape.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from rag_chat.api.schemas import BriefBullet, BriefCitation, BriefSection, PublicBriefingResponse

pytestmark = pytest.mark.unit

# ── BriefCitation tests ───────────────────────────────────────────────────────


@pytest.mark.unit
class TestBriefCitation:
    def test_minimal_valid_citation(self) -> None:
        """BriefCitation accepts minimum required fields."""
        c = BriefCitation(document_id="doc-1", snippet="Apple Q4 revenue hit $120B.")
        assert c.document_id == "doc-1"
        assert c.snippet == "Apple Q4 revenue hit $120B."
        # WHY check defaults: confirming optional fields don't require explicit values.
        assert c.url is None
        assert c.source_type == "article"
        assert c.title is None

    def test_full_citation_all_fields(self) -> None:
        """BriefCitation accepts all optional fields populated."""
        c = BriefCitation(
            document_id="doc-2",
            snippet="Fed raised rates by 25bps — first hike this cycle.",
            url="https://reuters.com/fed-hike",
            source_type="article",
            title="Fed Hikes Rates",
        )
        assert c.url == "https://reuters.com/fed-hike"
        assert c.title == "Fed Hikes Rates"

    def test_source_type_literals(self) -> None:
        """source_type must be one of article | event | alert."""
        for valid_type in ("article", "event", "alert"):
            c = BriefCitation(document_id="x", snippet="snippet", source_type=valid_type)  # type: ignore[arg-type]
            assert c.source_type == valid_type

        # WHY ValueError (not ValidationError): PLAN-0083 — BriefCitation is now
        # a frozen dataclass; constraints raised via __post_init__ as ValueError.
        with pytest.raises(ValueError):
            BriefCitation(document_id="x", snippet="snippet", source_type="unknown")  # type: ignore[arg-type]

    def test_snippet_max_length_400(self) -> None:
        """snippet is capped at 400 chars."""
        long_snip = "x" * 401
        # WHY ValueError: see test_source_type_literals (PLAN-0083).
        with pytest.raises(ValueError):
            BriefCitation(document_id="x", snippet=long_snip)

    def test_snippet_at_exactly_400_chars(self) -> None:
        """snippet of exactly 400 chars is accepted (boundary condition)."""
        c = BriefCitation(document_id="x", snippet="A" * 400)
        assert len(c.snippet) == 400


# ── BriefBullet tests ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestBriefBullet:
    def _citation(self, doc_id: str = "doc-1") -> BriefCitation:
        return BriefCitation(document_id=doc_id, snippet="Some evidence.")

    def test_valid_bullet(self) -> None:
        """BriefBullet with text and one citation is valid."""
        b = BriefBullet(text="Tech sector rallied 2%.", citations=[self._citation()])
        assert b.text == "Tech sector rallied 2%."
        assert len(b.citations) == 1

    def test_empty_citations_rejected(self) -> None:
        """citations list with zero entries must be rejected (100% citation gate)."""
        # WHY ValueError: PLAN-0083 — BriefBullet is now a frozen dataclass.
        with pytest.raises(ValueError, match="citations"):
            BriefBullet(text="Some text.", citations=[])

    def test_multiple_citations_allowed(self) -> None:
        """A bullet may reference multiple citations."""
        b = BriefBullet(
            text="Growth driven by cloud and AI demand.",
            citations=[self._citation("doc-1"), self._citation("doc-2")],
        )
        assert len(b.citations) == 2

    def test_text_min_length_1(self) -> None:
        """Empty text string is rejected."""
        # WHY ValueError: PLAN-0083 — BriefBullet is now a frozen dataclass.
        with pytest.raises(ValueError):
            BriefBullet(text="", citations=[self._citation()])

    def test_text_max_length_400(self) -> None:
        """Text capped at 400 chars."""
        # WHY ValueError: PLAN-0083 — BriefBullet is now a frozen dataclass.
        with pytest.raises(ValueError):
            BriefBullet(text="x" * 401, citations=[self._citation()])


# ── BriefSection updated contract ────────────────────────────────────────────


@pytest.mark.unit
class TestBriefSectionWithBullets:
    def _bullet(self) -> BriefBullet:
        return BriefBullet(
            text="Markets rose on strong jobs data.",
            citations=[BriefCitation(document_id="d1", snippet="Jobs data: +250k.")],
        )

    def test_section_with_brief_bullets(self) -> None:
        """BriefSection now requires list[BriefBullet] for its bullets field."""
        sec = BriefSection(title="Market Overview", bullets=[self._bullet()])
        assert sec.title == "Market Overview"
        assert len(sec.bullets) == 1
        assert isinstance(sec.bullets[0], BriefBullet)

    def test_section_with_zero_bullets_allowed(self) -> None:
        """min_length=0 on bullets enables backfill pattern — empty sections are
        constructed and then dropped by _backfill_uncited_bullets()."""
        sec = BriefSection(title="Risks", bullets=[])
        assert sec.bullets == []

    def test_bullets_cap_at_8(self) -> None:
        """bullets list is capped at max_length=8."""
        bullets = [self._bullet() for _ in range(9)]
        # WHY ValueError: PLAN-0083 — BriefSection is now a frozen dataclass.
        with pytest.raises(ValueError):
            BriefSection(title="Risks", bullets=bullets)

    def test_bullets_at_exactly_8_accepted(self) -> None:
        """Boundary acceptance: 8 bullets (the max) must be accepted."""
        # WHY pin the upper boundary: QA-PLAN-0083 F-002 — without this assertion a
        # future off-by-one tightening of the cap (e.g. >= 8 instead of > 8) would
        # silently break legitimate 8-bullet sections.
        bullets = [self._bullet() for _ in range(8)]
        sec = BriefSection(title="Risks", bullets=bullets)
        assert len(sec.bullets) == 8

    def test_section_title_at_exactly_120_chars_accepted(self) -> None:
        """Boundary acceptance: title of exactly max_length=120 must be accepted."""
        # WHY this test exists: QA-PLAN-0083 F-002 found that the title max_length=120
        # constraint had ZERO test coverage after the Pydantic→dataclass migration.
        # Both boundary directions are now pinned.
        title = "x" * 120
        sec = BriefSection(title=title, bullets=[self._bullet()])
        assert len(sec.title) == 120

    def test_section_title_above_120_chars_rejected(self) -> None:
        """title of length 121 must raise ValueError (max_length=120 enforced in __post_init__)."""
        # WHY ValueError (not ValidationError): PLAN-0083 — BriefSection is now a
        # frozen dataclass; constraint enforcement moved from Pydantic Field to
        # __post_init__.
        with pytest.raises(ValueError):
            BriefSection(title="x" * 121, bullets=[self._bullet()])


# ── PublicBriefingResponse new additive fields ────────────────────────────────


@pytest.mark.unit
class TestPublicBriefingResponseAdditions:
    def test_confidence_default_one(self) -> None:
        """confidence defaults to 1.0 (safe fallback — no warning badge shown)."""
        r = PublicBriefingResponse(narrative="ok", risk_summary={}, generated_at="2026-05-03T00:00:00Z")
        assert r.confidence == 1.0

    def test_confidence_clamps_to_range(self) -> None:
        """confidence must be in [0.0, 1.0]."""
        with pytest.raises(ValidationError):
            PublicBriefingResponse(narrative="ok", risk_summary={}, generated_at="t", confidence=1.5)
        with pytest.raises(ValidationError):
            PublicBriefingResponse(narrative="ok", risk_summary={}, generated_at="t", confidence=-0.1)

    def test_lead_default_none(self) -> None:
        """lead defaults to None — instrument briefs and legacy briefs omit it."""
        r = PublicBriefingResponse(narrative="ok", risk_summary={}, generated_at="t")
        assert r.lead is None

    def test_lead_max_length_1000(self) -> None:
        """lead is capped at 1000 chars (allows up to 3 dense sentences)."""
        with pytest.raises(ValidationError):
            PublicBriefingResponse(narrative="ok", risk_summary={}, generated_at="t", lead="x" * 1001)

    def test_lead_accepts_three_sentences(self) -> None:
        """A 3-sentence lead under 1000 chars must be accepted without error."""
        long_lead = (
            "Meta's increased capex to $145B signals aggressive AI infrastructure expansion "
            "across data centers and silicon, compressing near-term free cash flow. "
            "Analysts expect margin pressure in H1 before hyperscale deployments begin monetizing "
            "in H2, with MSFT and GOOGL likely to follow suit. "
            "Portfolio exposure to cloud infrastructure, energy, and cooling suppliers is elevated."
        )
        assert len(long_lead) < 1000
        r = PublicBriefingResponse(narrative="ok", risk_summary={}, generated_at="t", lead=long_lead)
        assert r.lead == long_lead


# ── from_dict / to_dict round-trip surface (PLAN-0083 Wave A I-1) ─────────────


@pytest.mark.unit
class TestFromDictToDict:
    """Cover the new ``from_dict``/``to_dict`` surface introduced when the
    Brief* value objects migrated from Pydantic to frozen dataclasses
    (PLAN-0083 Wave A). These tests pin the legacy ``source_id`` alias path,
    ensure the write side never re-emits the legacy key, and verify deep
    nested round-trip identity through BriefSection.
    """

    # ── BriefCitation ────────────────────────────────────────────────────────

    def test_citation_from_dict_canonical_key(self) -> None:
        """Canonical 'document_id' input is accepted."""
        c = BriefCitation.from_dict({"document_id": "x", "snippet": "s"})
        assert c.document_id == "x"
        assert c.snippet == "s"

    def test_citation_from_dict_legacy_source_id_alias(self) -> None:
        """Legacy 'source_id' input is mapped to document_id (read-path tolerance)."""
        # WHY: cached payloads written before PLAN-0083 used the old key. The
        # Pydantic ``populate_by_name`` semantics must survive the dataclass
        # migration so old caches keep deserialising.
        c = BriefCitation.from_dict({"source_id": "legacy-x", "snippet": "s"})
        assert c.document_id == "legacy-x"

    def test_citation_from_dict_document_id_wins_over_source_id(self) -> None:
        """When both keys are present, document_id takes precedence."""
        # WHY: the `or` precedence in from_dict means truthy document_id wins;
        # this pins that ordering so a future refactor can't silently flip it.
        c = BriefCitation.from_dict({"document_id": "primary", "source_id": "ignored", "snippet": "s"})
        assert c.document_id == "primary"

    def test_citation_from_dict_missing_id_raises(self) -> None:
        """Neither key present -> ValueError."""
        with pytest.raises(ValueError, match="document_id"):
            BriefCitation.from_dict({"snippet": "s"})

    def test_citation_to_dict_emits_document_id_only(self) -> None:
        """to_dict must emit document_id and never the legacy source_id key."""
        c = BriefCitation(document_id="doc-1", snippet="snip")
        d = c.to_dict()
        assert d["document_id"] == "doc-1"
        # WHY explicit absence check: the alias is read-only by design — emitting
        # source_id on the write path would re-introduce the legacy field name.
        assert "source_id" not in d

    def test_citation_round_trip_equality(self) -> None:
        """from_dict(c.to_dict()) == c — frozen dataclass equality holds."""
        # WHY: frozen=True dataclasses get __eq__ by default (compares all
        # fields). Round-trip identity is the contract the cache layer relies on.
        c = BriefCitation(
            document_id="doc-1",
            snippet="snip",
            url="https://example.com",
            source_type="event",
            title="t",
        )
        assert BriefCitation.from_dict(c.to_dict()) == c

    # ── BriefBullet ──────────────────────────────────────────────────────────

    def test_bullet_from_dict_reconstructs_nested_citations(self) -> None:
        """BriefBullet.from_dict turns raw nested citation dicts into BriefCitation."""
        raw = {
            "text": "Tech rallied.",
            "citations": [{"document_id": "d1", "snippet": "s1"}],
        }
        b = BriefBullet.from_dict(raw)
        assert isinstance(b.citations[0], BriefCitation)
        assert b.citations[0].document_id == "d1"

    def test_bullet_to_dict_serializes_citations_as_dicts(self) -> None:
        """to_dict must call to_dict() on each citation (no dataclass leakage)."""
        # WHY: if the bullet returned BriefCitation instances, JSON serialisation
        # downstream (Pydantic / json.dumps in the cache writer) would fail.
        b = BriefBullet(
            text="t",
            citations=[BriefCitation(document_id="d1", snippet="s1")],
        )
        out = b.to_dict()
        assert isinstance(out["citations"], list)
        assert isinstance(out["citations"][0], dict)
        assert out["citations"][0]["document_id"] == "d1"

    def test_bullet_round_trip_equality(self) -> None:
        """from_dict(b.to_dict()) == b — full nested equality."""
        b = BriefBullet(
            text="t",
            citations=[BriefCitation(document_id="d1", snippet="s1")],
        )
        assert BriefBullet.from_dict(b.to_dict()) == b

    # ── BriefSection ─────────────────────────────────────────────────────────

    def test_section_from_dict_round_trip(self) -> None:
        """BriefSection round-trips with nested bullets and citations preserved."""
        s = BriefSection(
            title="Market",
            bullets=[
                BriefBullet(
                    text="Tech up.",
                    citations=[BriefCitation(document_id="d1", snippet="s1")],
                ),
                BriefBullet(
                    text="Energy down.",
                    citations=[BriefCitation(document_id="d2", snippet="s2")],
                ),
            ],
        )
        assert BriefSection.from_dict(s.to_dict()) == s

    def test_section_to_dict_deep_converts(self) -> None:
        """to_dict produces a fully-dict tree (no dataclass instances anywhere)."""
        # WHY: the production cache path (model_dump_json) needs the entire tree
        # to be JSON-native. A single missed conversion would crash serialisation.
        s = BriefSection(
            title="Market",
            bullets=[
                BriefBullet(
                    text="Tech up.",
                    citations=[BriefCitation(document_id="d1", snippet="s1")],
                ),
            ],
        )
        out = s.to_dict()
        assert isinstance(out["bullets"], list)
        assert isinstance(out["bullets"][0], dict)
        assert isinstance(out["bullets"][0]["citations"], list)
        assert isinstance(out["bullets"][0]["citations"][0], dict)

    # ── /fix-bug additions: close deferred QA-PLAN-0083 MINOR findings ───────

    def test_bullet_text_at_exactly_1_char_accepted(self) -> None:
        """Boundary acceptance: BriefBullet.text len==1 is the min and must be accepted.

        WHY (QA-PLAN-0083 F-001 QA): the rejection of len==0 is tested in
        ``test_text_min_length_1`` but the at-boundary acceptance was untested,
        leaving a symmetric gap. A future tightening to ``len <= 1`` would
        silently break legitimate one-char bullets without this assertion.
        """
        b = BriefBullet(text="x", citations=[BriefCitation(document_id="d1", snippet="s")])
        assert b.text == "x"

    def test_bullet_post_init_rejects_raw_dict_in_citations(self) -> None:
        """Passing a raw dict (not a BriefCitation) in citations raises ValueError.

        WHY (QA-PLAN-0083 F-003): __post_init__ has an isinstance(c, BriefCitation)
        guard that rejects the legacy v1 cache shape. Test it directly so the
        guard isn't only exercised indirectly via the section-level analog.
        """
        with pytest.raises(ValueError, match="BriefCitation instances"):
            BriefBullet(text="t", citations=[{"document_id": "d1", "snippet": "s"}])  # type: ignore[list-item]

    def test_bullet_from_dict_missing_text_raises_value_error(self) -> None:
        """Missing required 'text' key raises ValueError (not KeyError).

        WHY (QA-PLAN-0083 F-004): BriefCitation.from_dict raises ValueError for
        missing required keys; harmonized to ValueError across all from_dict
        classmethods so callers can use a single ``except ValueError`` for any
        malformed cached payload.
        """
        with pytest.raises(ValueError, match="text"):
            BriefBullet.from_dict({"citations": [{"document_id": "d1", "snippet": "s"}]})

    def test_section_from_dict_missing_title_raises_value_error(self) -> None:
        """Missing required 'title' key raises ValueError (not KeyError).

        WHY (QA-PLAN-0083 F-004): consistency with the other from_dict methods.
        """
        with pytest.raises(ValueError, match="title"):
            BriefSection.from_dict({"bullets": []})

    def test_citation_from_dict_missing_snippet_raises_value_error(self) -> None:
        """Missing required 'snippet' key raises ValueError (not implicit KeyError).

        WHY (QA-PLAN-0083 F-004): we previously let ``data["snippet"]`` raise
        KeyError; now we raise ValueError explicitly for consistency.
        """
        with pytest.raises(ValueError, match="snippet"):
            BriefCitation.from_dict({"document_id": "d1"})

    def test_citation_from_dict_extra_keys_silently_ignored(self) -> None:
        """Unknown keys in the input dict are silently ignored.

        WHY (QA-PLAN-0083 F-005): forward-compatibility contract — a future
        cache blob with extra fields must not break older readers. This pins
        the current behaviour so a future strict-construction refactor can't
        silently break old caches.
        """
        c = BriefCitation.from_dict(
            {
                "document_id": "d1",
                "snippet": "s",
                "future_field": 42,
                "another": "ignored",
            }
        )
        assert c.document_id == "d1"
        assert c.snippet == "s"

    def test_citation_from_dict_empty_string_document_id_does_not_fall_through(self) -> None:
        """Explicit document_id='' is rejected — does NOT silently fall back to source_id.

        WHY (QA-PLAN-0083 F-006): the previous truthiness-based ``or`` fallback
        meant ``{"document_id": "", "source_id": "real"}`` would silently use
        ``source_id``, masking data corruption where the canonical key was
        present but blank. Explicit-key precedence + non-empty validation
        rejects this.
        """
        with pytest.raises(ValueError, match="non-empty document_id"):
            BriefCitation.from_dict({"document_id": "", "source_id": "real", "snippet": "s"})

    def test_citation_from_dict_falls_through_to_source_id_only_when_key_absent(self) -> None:
        """Falls back to source_id only when document_id key is absent (not present-but-empty).

        WHY (QA-PLAN-0083 F-006): explicit-key precedence — ``"document_id"
        in data`` decides whether the fallback applies. This is the path
        legitimate legacy callers depend on (no document_id key at all).
        """
        c = BriefCitation.from_dict({"source_id": "legacy-d1", "snippet": "s"})
        assert c.document_id == "legacy-d1"
