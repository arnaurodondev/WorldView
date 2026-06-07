"""Tests for ``NumericGroundingValidator`` (PLAN-0093 Wave E-2 T-E-2-01).

Covers the per-FieldKind tolerance table described in the plan slice
(plan lines 1745-1758): different tolerances for PRICE / EPS / RATIO /
REVENUE / HEADCOUNT / YEAR / QUARTER. The canonical AMD QA failure
(response "$34.6B" vs tool 10.253e9) is encoded as the
``test_invented_revenue_fails`` regression guard.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from rag_chat.application.services.numeric_grounding import (
    NumericGroundingValidator,
    classify_number,
)

from contracts.numeric_grounding import FieldKind

pytestmark = pytest.mark.unit


# Lightweight tool-result row stub — duck-typed for the validator.
@dataclass
class _ToolRow:
    text: str = ""
    value: float | None = None
    field_kind: FieldKind | None = None


def _row_with_text(text: str) -> _ToolRow:
    return _ToolRow(text=text)


def _row_with_value(value: float, kind: FieldKind) -> _ToolRow:
    return _ToolRow(value=value, field_kind=kind)


class TestNumericGroundingValidator:
    def setup_method(self) -> None:
        self.v = NumericGroundingValidator()

    # ── Revenue tolerance (0.5%) ──────────────────────────────────────────
    def test_exact_revenue_match_passes(self) -> None:
        """Response '$10.253B' + tool 10.253e9 → REVENUE, passes (0% diff)."""
        rows = [_row_with_value(10.253e9, FieldKind.REVENUE)]
        result = self.v.validate("Reported revenue of $10.253B last quarter.", rows)
        assert result.passed, result.unsupported

    def test_invented_revenue_fails(self) -> None:
        """The AMD QA regression: '$34.6B' vs tool 10.253B → REVENUE fails."""
        rows = [_row_with_value(10.253e9, FieldKind.REVENUE)]
        result = self.v.validate("Q2 revenue was $34.6B according to filings.", rows)
        assert not result.passed
        assert any(u.field_kind is FieldKind.REVENUE for u in result.unsupported)

    def test_rounded_revenue_within_tolerance(self) -> None:
        """Response '$68.1B' + tool 68.127B → REVENUE passes (0.04% < 0.5%)."""
        rows = [_row_with_value(68.127e9, FieldKind.REVENUE)]
        result = self.v.validate("Apple's revenue of $68.1B exceeded estimates.", rows)
        assert result.passed, result.unsupported

    # ── EPS tolerance (2%) ────────────────────────────────────────────────
    def test_eps_tighter_tolerance_catches_wrong_cents(self) -> None:
        """Response EPS $0.50 + tool $0.40 → EPS fails (25% > 2%)."""
        rows = [_row_with_value(0.40, FieldKind.EPS)]
        result = self.v.validate("EPS of $0.50 beat the consensus.", rows)
        assert not result.passed

    def test_eps_within_2pct_passes(self) -> None:
        """Response EPS $0.45 + tool $0.456 → passes (1.3% ≤ 2%)."""
        rows = [_row_with_value(0.456, FieldKind.EPS)]
        result = self.v.validate("Diluted EPS came in at $0.45.", rows)
        assert result.passed, result.unsupported

    # ── Ratio tolerance (2%) ──────────────────────────────────────────────
    def test_pe_ratio_fails_on_4pt_drift(self) -> None:
        """Response P/E 28 + tool P/E 23.7 → RATIO fails (18% > 2%)."""
        rows = [_row_with_value(23.7, FieldKind.RATIO)]
        result = self.v.validate("Apple now trades at a P/E ratio of 28.", rows)
        assert not result.passed

    # ── Headcount tolerance (5%) ──────────────────────────────────────────
    def test_headcount_5pct_tolerance(self) -> None:
        """Headcount 161,000 vs 161,400 → passes; 150,000 vs 161,400 → fails."""
        rows = [_row_with_value(161_400, FieldKind.HEADCOUNT)]
        ok = self.v.validate("Apple employs 161,000 employees worldwide.", rows)
        assert ok.passed, ok.unsupported

        bad = self.v.validate("Apple employs 150,000 employees worldwide.", rows)
        assert not bad.passed

    # ── Year + Quarter tolerance (0%) ────────────────────────────────────
    def test_year_must_match_exactly(self) -> None:
        """Response '2025' + tool says '2026' → YEAR fails."""
        rows = [_row_with_text("Fiscal year 2026 saw strong growth.")]
        result = self.v.validate("In fiscal year 2025 the company doubled.", rows)
        # 2025 in response must be matched against year tokens in the tool text.
        kinds = {u.field_kind for u in result.unsupported}
        assert FieldKind.YEAR in kinds

    def test_quarter_must_match_exactly(self) -> None:
        """Response 'Q1 2026' + tool 'Q4 2025' → QUARTER fails."""
        rows = [_row_with_text("Q4 2025 results were strong.")]
        result = self.v.validate("Q1 2026 revenue exceeded analyst estimates.", rows)
        assert not result.passed
        assert any(u.field_kind is FieldKind.QUARTER and u.snippet == "Q1 2026" for u in result.unsupported)

    def test_invented_quarter_for_unreported_period(self) -> None:
        """Response 'Q2 2026 revenue $10.3B' but tools have no Q2 2026 → fails."""
        # Tool only knows Q1 2026.
        rows = [_row_with_text("Q1 2026 revenue was $9.8B per the filing.")]
        result = self.v.validate("Q2 2026 revenue $10.3B beat estimates.", rows)
        assert not result.passed
        kinds = {u.field_kind for u in result.unsupported}
        # Either QUARTER label failure or REVENUE failure surfaces.
        assert FieldKind.QUARTER in kinds or FieldKind.REVENUE in kinds

    # ── Classifier tests ─────────────────────────────────────────────────
    def test_classifier_revenue_from_context(self) -> None:
        """Same number 10.0 classified differently by context."""
        assert classify_number(10.0e9, "$10.0B", "revenue of $10.0b in q3 2025") is FieldKind.REVENUE
        assert classify_number(10.0, "$10.0", "eps of $10.0 per share") is FieldKind.EPS
        assert classify_number(10.0, "10.0", "p/e ratio of 10.0 for the stock") is FieldKind.RATIO

    def test_classifier_falls_back_to_unknown_safely(self) -> None:
        """Unclassifiable context with no useful magnitude → UNKNOWN."""
        # 7 by itself with no context keyword + no currency + no suffix.
        kind = classify_number(7.0, "7", "the company has 7 of those.")
        assert kind in (FieldKind.UNKNOWN, FieldKind.HEADCOUNT)  # accept either fallback

    # ── Skip-kinds + override ─────────────────────────────────────────────
    def test_year_numbers_ignored_when_skipped(self) -> None:
        """skip_kinds={YEAR} → response year numbers are not validated."""
        v = NumericGroundingValidator(skip_kinds={FieldKind.YEAR})
        rows = [_row_with_text("Fiscal year 2026 saw strong growth.")]
        result = v.validate("In fiscal year 2025 the company doubled.", rows)
        # YEAR was the only mismatch and it is now skipped.
        kinds = {u.field_kind for u in result.unsupported}
        assert FieldKind.YEAR not in kinds

    def test_settings_override_applies(self) -> None:
        """Tolerance override → '150K' vs '161K' headcount now passes at 10%."""
        from contracts.numeric_grounding import DEFAULT_TOLERANCES

        overrides = dict(DEFAULT_TOLERANCES)
        overrides[FieldKind.HEADCOUNT] = 0.10  # was 0.05
        v = NumericGroundingValidator(tolerances=overrides)
        rows = [_row_with_value(161_000, FieldKind.HEADCOUNT)]
        # 150K vs 161K is 6.8% off — under 10% but over the default 5%.
        result = v.validate("The workforce includes 150,000 employees.", rows)
        assert result.passed, result.unsupported

    # ── Percentage handling ───────────────────────────────────────────────
    def test_percentage_to_fraction_match(self) -> None:
        """Response '50%' matches '0.5' within tolerance.

        The validator normalises '50%' → 0.5 so a tool emitting fractions
        and an LLM emitting percents both compare on the same scale.
        """
        rows = [_row_with_value(0.50, FieldKind.RATIO)]
        result = self.v.validate("Gross margin holds at 50% this quarter.", rows)
        assert result.passed, result.unsupported

    # ── Citation markers ──────────────────────────────────────────────────
    def test_citation_markers_ignored(self) -> None:
        """[N7] in the response is NOT extracted as the number 7."""
        # No tool results at all — but [N7] should not surface as a number.
        rows: list[_ToolRow] = []
        result = self.v.validate("This claim is well documented [N7].", rows)
        assert result.total_numbers == 0
        assert result.passed

    # ── Qualitative + empty cases ─────────────────────────────────────────
    def test_no_numbers_response_passes(self) -> None:
        """A qualitative response with no numbers always passes."""
        result = self.v.validate("Apple has strong product loyalty.", [])
        assert result.passed
        assert result.total_numbers == 0

    def test_empty_tool_results_fails_any_number(self) -> None:
        """Numeric response + no tools → every number is unsupported."""
        result = self.v.validate("Apple reported revenue of $10B last quarter.", [])
        assert not result.passed
        assert len(result.unsupported) >= 1

    # ── Sign sensitivity ──────────────────────────────────────────────────
    def test_sign_must_match_loss_vs_gain(self) -> None:
        """Response 'earned $1.5B' + tool 'lost $1.5B' → fails on sign."""
        # Tool emits a negative value (loss).
        rows = [_row_with_value(-1.5e9, FieldKind.REVENUE)]
        result = self.v.validate("The segment earned $1.5B in the quarter.", rows)
        assert not result.passed
        # The closest tool value is -1.5B but the response asserts +1.5B.
        assert any(u.value > 0 for u in result.unsupported)

    # ── per-kind stats ────────────────────────────────────────────────────
    def test_per_kind_stats_in_result(self) -> None:
        """``GroundingResult.per_kind_stats`` records (passed, failed) per kind."""
        rows = [
            _row_with_value(0.456, FieldKind.EPS),  # close to 0.45
            _row_with_value(10.253e9, FieldKind.REVENUE),  # close to 10.253
        ]
        result = self.v.validate(
            "EPS came in at $0.45 and revenue was $34.6B.",
            rows,
        )
        # EPS passed, REVENUE failed.
        eps_passed, eps_failed = result.per_kind_stats.get(FieldKind.EPS, (0, 0))
        rev_passed, rev_failed = result.per_kind_stats.get(FieldKind.REVENUE, (0, 0))
        assert eps_passed >= 1
        assert rev_failed >= 1


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0093 Phase 5 QA-2 Gap 2 — broadened quarter-label regex.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _TaggedRow:
    """Tool row with an explicit item_id to test entity-scope behaviour."""

    text: str = ""
    value: float | None = None
    field_kind: FieldKind | None = None
    item_id: str = ""
    entity_id: str | None = None


class TestQuarterLabelVariants:
    """Confirm the canonicalising regex accepts FY/fiscal forms + 2-digit years."""

    def setup_method(self) -> None:
        self.v = NumericGroundingValidator()

    def test_q1_fy26_matches_q1_2026_in_tools(self) -> None:
        """LLM writes "Q1 FY26" — tool says "Q1 2026" — must pass (same period)."""
        rows = [_row_with_text("Q1 2026 revenue was $10B.")]
        result = self.v.validate("Q1 FY26 results were strong.", rows)
        # No QUARTER unsupported entries — "Q1 FY26" normalises to "Q1 2026".
        kinds = {u.field_kind for u in result.unsupported}
        assert FieldKind.QUARTER not in kinds, result.unsupported

    def test_q1_fiscal_year_2026_matches_q1_2026(self) -> None:
        """Long-form "Q1 of fiscal year 2026" → matches "Q1 2026"."""
        rows = [_row_with_text("Q1 2026 revenue was $10B.")]
        result = self.v.validate("Q1 of fiscal year 2026 saw growth.", rows)
        kinds = {u.field_kind for u in result.unsupported}
        assert FieldKind.QUARTER not in kinds, result.unsupported

    def test_q1_fiscal_2027_mismatch_caught(self) -> None:
        """LLM writes "Q1 fiscal 2027" — tool only has "Q1 2026" — must fail."""
        rows = [_row_with_text("Q1 2026 revenue was $10B.")]
        result = self.v.validate("Q1 fiscal 2027 will be even bigger.", rows)
        quarter_snippets = {u.snippet for u in result.unsupported if u.field_kind is FieldKind.QUARTER}
        assert "Q1 2027" in quarter_snippets, quarter_snippets

    def test_bare_q3_revenue_flagged(self) -> None:
        """Bare "Q3 revenue" with no year → surfaced as "Q3 (no year)" failure."""
        rows = [_row_with_text("Q1 2026 results were positive.")]
        result = self.v.validate("Q3 revenue surged this period.", rows)
        bare_snippets = {u.snippet for u in result.unsupported if u.field_kind is FieldKind.QUARTER}
        assert "Q3 (no year)" in bare_snippets, bare_snippets

    def test_bare_q4_chip_launch_not_flagged(self) -> None:
        """Bare "Q4 chip launch" — no financial keyword nearby → no failure."""
        rows = [_row_with_text("Q1 2026 results were positive.")]
        result = self.v.validate("Q4 chip launch is on track.", rows)
        bare_snippets = {u.snippet for u in result.unsupported if u.field_kind is FieldKind.QUARTER}
        # "Q4" appears alone; no financial keyword (revenue/earnings/etc.)
        # within the 60-char window → must not be surfaced.
        assert "Q4 (no year)" not in bare_snippets, bare_snippets


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0093 Phase 5 QA-2 Gap 3 — entity-scoped candidate pool.
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossEntityLeakage:
    """Confirm the validator does not let NVDA values ground AMD claims."""

    def setup_method(self) -> None:
        self.v = NumericGroundingValidator()

    def test_amd_revenue_grounded_only_by_amd_rows(self) -> None:
        """Mixed AMD+NVDA corpus — AMD's claim ($10B) matches AMD's tool row."""
        rows = [
            _TaggedRow(value=10.0e9, field_kind=FieldKind.REVENUE, item_id="AMD_2026Q1"),
            _TaggedRow(value=68.0e9, field_kind=FieldKind.REVENUE, item_id="NVDA_2026Q1"),
        ]
        # AMD's name appears just before the number.
        result = self.v.validate("AMD reported revenue of $10B last quarter.", rows)
        # No REVENUE failures — AMD's $10B matches AMD's tool row.
        rev_failures = [u for u in result.unsupported if u.field_kind is FieldKind.REVENUE]
        assert not rev_failures, rev_failures

    def test_amd_claim_using_nvda_value_rejected(self) -> None:
        """The canonical leak: 'AMD revenue $68B' must NOT pass on NVDA's $68B row."""
        rows = [
            _TaggedRow(value=10.0e9, field_kind=FieldKind.REVENUE, item_id="AMD_2026Q1"),
            _TaggedRow(value=68.0e9, field_kind=FieldKind.REVENUE, item_id="NVDA_2026Q1"),
        ]
        result = self.v.validate("AMD reported revenue of $68B last quarter.", rows)
        rev_failures = [u for u in result.unsupported if u.field_kind is FieldKind.REVENUE]
        # AMD scope contains only $10B → $68B is unsupported.
        assert rev_failures, result.unsupported
        assert any(abs(u.value - 68e9) < 1 for u in rev_failures), rev_failures

    def test_no_entity_context_falls_back_to_exact_match(self) -> None:
        """When the response mentions no ticker, any-kind pool is exact-match only.

        Tool row has $10.0B; response says $10.1B with no entity context.
        Previously this would pass at REVENUE 0.5% tolerance; now the
        any-kind fallback is exact-match only → must fail.
        """
        # No entity_id / item_id on the row → entity_tag = "".
        # Response also has no ticker before the number.
        rows = [_TaggedRow(value=10.0e9, field_kind=FieldKind.UNKNOWN)]  # kind mismatch forces any-kind path
        result = self.v.validate("The company reported revenue of $10.1B.", rows)
        # 10.1B vs 10.0B at exact-match tolerance → fails.
        rev_failures = [u for u in result.unsupported if u.field_kind is FieldKind.REVENUE]
        assert rev_failures, result.unsupported


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0093 Phase 5c F-LIVE-008-RATIONALISATION — orphan rationalisation prose.
# ─────────────────────────────────────────────────────────────────────────────


class TestRationalisationDetection:
    """Validator must surface orphan rationalisation phrases as PROSE failures.

    The Q4 v1 cached pre-FIX answer contained "may reflect", "potential
    volatility", and "one-time event" with NO citation markers. The
    number-based validator passed it (the prose has no numbers). The
    rewrite pipeline never saw the issue. These tests pin the new
    behaviour: orphan rationalisations → UnsupportedNumber(PROSE);
    cited rationalisations → no entry.
    """

    def setup_method(self) -> None:
        self.v = NumericGroundingValidator()

    def test_orphan_may_reflect_flagged(self) -> None:
        """'may reflect' without a [Nk] citation within 100 chars → flagged."""
        result = self.v.validate("Q4 results may reflect changing market conditions.", [])
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        assert len(prose_failures) == 1, result.unsupported
        assert "may reflect" in prose_failures[0].snippet.lower()

    def test_cited_may_reflect_not_flagged(self) -> None:
        """'may reflect [N1]' — citation within 100 chars → not flagged."""
        result = self.v.validate("Q4 results may reflect [N1] guidance updates.", [])
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        assert not prose_failures, prose_failures

    def test_cited_one_time_event_not_flagged(self) -> None:
        """'one-time event [N2]' — citation present → not flagged."""
        result = self.v.validate("Revenue declined due to one-time event [N2] in Q3.", [])
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        assert not prose_failures, prose_failures

    def test_plain_numeric_answer_no_rationalisation(self) -> None:
        """Number-only answer with no rationalisation prose → no PROSE failures."""
        rows = [_row_with_value(10.253e9, FieldKind.REVENUE)]
        result = self.v.validate("Reported revenue of $10.253B last quarter.", rows)
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        assert not prose_failures, prose_failures

    def test_multiple_orphan_phrases_each_flagged(self) -> None:
        """Three orphan phrases in one answer → three PROSE entries."""
        text = "Results may reflect headwinds. Potential volatility ahead. Likely due to inflation."
        result = self.v.validate(text, [])
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        # 3 distinct phrases — "may reflect", "potential volatility", "likely due"
        assert len(prose_failures) == 3, prose_failures

    def test_orphan_potential_volatility_flagged(self) -> None:
        """'potential volatility' without citation → flagged."""
        result = self.v.validate("Investors should expect potential volatility this quarter.", [])
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        assert len(prose_failures) == 1, prose_failures

    def test_citation_beyond_100_char_window_still_flagged(self) -> None:
        """A citation > 100 chars after the phrase does NOT rescue the orphan."""
        # 100+ chars of filler before the citation → orphan.
        filler = "x" * 120
        text = f"Q4 may reflect {filler} [N1]"
        result = self.v.validate(text, [])
        prose_failures = [u for u in result.unsupported if u.field_kind is FieldKind.PROSE]
        assert len(prose_failures) == 1, prose_failures


# ── PLAN-0104 W28-3/W28-4 regression tests ────────────────────────────────────


class TestEntityTagForToolPrefix:
    """W28-3 / BP-646 — `tool:<name>:<TICKER>` item_ids must yield a ticker tag."""

    def test_tool_prefix_extracts_ticker(self) -> None:
        from rag_chat.application.services.numeric_grounding import _entity_tag_for

        @dataclass
        class _Row:
            item_id: str

        assert _entity_tag_for(_Row(item_id="tool:fundamentals:AMZN")) == "amzn"
        assert _entity_tag_for(_Row(item_id="tool:price_history:NVDA")) == "nvda"

    def test_bare_ticker_underscore_still_works(self) -> None:
        from rag_chat.application.services.numeric_grounding import _entity_tag_for

        @dataclass
        class _Row:
            item_id: str

        assert _entity_tag_for(_Row(item_id="AAPL_2026Q1")) == "aapl"

    def test_unknown_form_returns_empty(self) -> None:
        from rag_chat.application.services.numeric_grounding import _entity_tag_for

        @dataclass
        class _Row:
            item_id: str

        assert _entity_tag_for(_Row(item_id="random-id-9999")) == ""


class TestClassifyNumberQuarterGuard:
    """W28-4 / BP-647 — bare "Q2" / "Q3" digits must NOT classify as REVENUE."""

    def test_quarter_digit_with_revenue_context_returns_unknown(self) -> None:
        # Context as it would be seen by the classifier (already lower-cased).
        # "Q2 2026 revenue" → token "2", value=2.
        kind = classify_number(2.0, "2", "q2 2026 revenue: $10b")
        assert kind is FieldKind.UNKNOWN

    def test_q3_label_returns_unknown(self) -> None:
        kind = classify_number(3.0, "3", "q3 2026 revenue rose")
        assert kind is FieldKind.UNKNOWN

    def test_real_revenue_still_revenue(self) -> None:
        # No Q-prefix: a value of 10B with revenue context still classifies.
        kind = classify_number(10.0e9, "$10B", "revenue of $10b last quarter")
        assert kind is FieldKind.REVENUE

    def test_quarter_only_triggers_with_matching_q_digit(self) -> None:
        # Context mentions Q1 but token is "3" — guard should NOT fire,
        # so context-keyword routing still classifies as REVENUE.
        kind = classify_number(3.0, "3", "q1 2026 revenue: 3 billion")
        assert kind is FieldKind.REVENUE


# ── PLAN-0104 W35 / BP-NEW: query_fundamentals envelope alignment ────────────


class TestQueryFundamentalsEnvelopeEndToEnd:
    """End-to-end regression: ``query_fundamentals`` row + AAPL P/E claim → PASS.

    Reproduces the AAPL Q1 path that previously failed under W28's
    defeatist-rewrite guards: the LLM's structured answer cited
    ``[query_fundamentals row 0]``, the validator could not pair the
    quoted ``37.73x`` against the snapshot block because the envelope
    (``item_id`` + ``citation_meta.entity_name``) used a different
    pattern from ``get_fundamentals_history``. W35 aligns the two so
    the entity tag resolves to ``"aapl"`` for both and the snapshot
    value is matched.
    """

    def setup_method(self) -> None:
        self.v = NumericGroundingValidator()

    def test_aapl_pe_ratio_matches_snapshot_via_query_fundamentals(self) -> None:
        # Tool result text mirrors what ``_handle_query_fundamentals``
        # renders after W35: ``tool:fundamentals:<TICKER>`` item id and
        # a snapshot block exposing ``pe_ratio: 37.73x``.
        snapshot_text = (
            "## AAPL fundamentals query\n"
            "Coverage: pe_ratio=ok, forward_pe=ok\n"
            "\n### AAPL Snapshot (as-of 2026-06-01, source: highlights)\n"
            "  pe_ratio: 37.73x\n"
            "  forward_pe: 27.80x\n"
        )
        row = _TaggedRow(text=snapshot_text, item_id="tool:fundamentals:AAPL")
        # LLM response using the canonical ``[N1]`` citation marker
        # (which the validator strips). The defeatist-rewrite-triggering
        # ``[query_fundamentals row 0]`` form is a presentation concern;
        # what matters here is that the 37.73x in the response matches
        # the 37.73 in the snapshot and the entity tag is "aapl" on
        # both sides.
        response = "Apple (AAPL) trades at a P/E ratio of 37.73x [N1]."
        result = self.v.validate(response, [row])
        # The 37.73 number must NOT appear in unsupported.
        ratio_failures = [
            u for u in result.unsupported if u.field_kind is FieldKind.RATIO and abs(u.value - 37.73) < 0.5
        ]
        assert not ratio_failures, f"Expected 37.73 to be grounded, got: {result.unsupported}"

    def test_get_fundamentals_history_pattern_still_works(self) -> None:
        """Sibling tool uses the same ``tool:fundamentals:<TICKER>`` pattern.

        Don't regress ``_handle_get_fundamentals_history`` — same id
        shape must continue to ground a P/E ratio against a tool row.
        """
        snapshot_text = "AAPL pe_ratio: 37.73x"
        row = _TaggedRow(text=snapshot_text, item_id="tool:fundamentals:AAPL")
        result = self.v.validate("AAPL P/E is 37.73x.", [row])
        ratio_failures = [
            u for u in result.unsupported if u.field_kind is FieldKind.RATIO and abs(u.value - 37.73) < 0.5
        ]
        assert not ratio_failures, result.unsupported


# ── Bug 3 fix (PLAN-0099 W4) — unit normalisation + prose citations ─────────


from decimal import Decimal  # (deliberately late import — section-scoped)

from rag_chat.application.services.numeric_grounding import (
    _has_grounding_citation,
    _normalize_numeric,
)


class TestNormalizeNumeric:
    """``_normalize_numeric`` must convert every common financial token shape
    into a single :class:`Decimal` so cross-format comparisons (``$24.7B``
    vs raw ``24700000000``) collapse to equality."""

    def test_dollar_with_billion_suffix(self) -> None:
        assert _normalize_numeric("$24.7B") == Decimal("24700000000.0")

    def test_dollar_with_trillion_suffix(self) -> None:
        # Mega-cap market cap (Apple etc.) — exact-equality matters.
        assert _normalize_numeric("$4.97T") == Decimal("4970000000000.00")

    def test_dollar_with_million_suffix(self) -> None:
        assert _normalize_numeric("$845.2M") == Decimal("845200000.0")

    def test_thousands_separators(self) -> None:
        assert _normalize_numeric("24,700,000,000") == Decimal("24700000000")

    def test_ratio_x_suffix_unchanged_magnitude(self) -> None:
        # P/E ratios: 31.5x means "31.5 multiplier", no scaling applied.
        assert _normalize_numeric("31.5x") == Decimal("31.5")

    def test_parenthesised_negative(self) -> None:
        # GAAP convention: (45.2) = -45.2.
        assert _normalize_numeric("(45.2)") == Decimal("-45.2")

    def test_explicit_negative_sign(self) -> None:
        assert _normalize_numeric("-1.5B") == Decimal("-1500000000.0")

    def test_percent_unchanged(self) -> None:
        # Tools that emit percents emit them as percents — no /100.
        assert _normalize_numeric("50%") == Decimal("50")

    def test_non_numeric_returns_none(self) -> None:
        assert _normalize_numeric("hello") is None

    def test_empty_returns_none(self) -> None:
        assert _normalize_numeric("") is None
        assert _normalize_numeric("   ") is None

    def test_none_returns_none(self) -> None:
        assert _normalize_numeric(None) is None  # type: ignore[arg-type]

    def test_lowercase_suffix(self) -> None:
        # LLMs are inconsistent — accept lowercase too.
        assert _normalize_numeric("24.7b") == Decimal("24700000000.0")

    def test_cross_format_equality(self) -> None:
        # The whole point of the helper: '$24.7B' compares equal to raw.
        a = _normalize_numeric("$24.7B")
        b = _normalize_numeric("24,700,000,000")
        assert a == b


class TestProseCitationRecognition:
    """``_has_grounding_citation`` must accept bracket AND prose forms so
    answers that cite their tools as ``(source: query_fundamentals row 0)``
    or ``per get_fundamentals_history`` do not falsely trip the banner."""

    def test_bracket_citation_recognised(self) -> None:
        text = "Revenue was $24.7B [query_fundamentals row 0]."
        # Token "$24.7B" starts at position 13, ends at 18.
        assert _has_grounding_citation(text, 13, 18, frozenset({"query_fundamentals"}))

    def test_source_paren_citation_recognised(self) -> None:
        text = "Revenue was $24.7B (source: query_fundamentals row 0)."
        assert _has_grounding_citation(text, 13, 18, frozenset({"query_fundamentals"}))

    def test_per_citation_recognised(self) -> None:
        text = "Revenue was $24.7B per query_fundamentals row 0."
        assert _has_grounding_citation(text, 13, 18, frozenset({"query_fundamentals"}))

    def test_according_to_citation_recognised(self) -> None:
        text = "Revenue was $24.7B according to query_fundamentals."
        assert _has_grounding_citation(text, 13, 18, frozenset({"query_fundamentals"}))

    def test_citation_outside_window_rejected(self) -> None:
        # Citation 200 chars away — far outside the 50-char window.
        filler = "x" * 200
        text = f"Revenue was $24.7B{filler} [query_fundamentals row 0]."
        assert not _has_grounding_citation(text, 13, 18, frozenset({"query_fundamentals"}))

    def test_cited_tool_not_called_rejected(self) -> None:
        # The cited tool wasn't in the called set → reject (defence
        # against LLM-invented tool names).
        text = "Revenue was $24.7B [made_up_tool row 0]."
        assert not _has_grounding_citation(text, 13, 18, frozenset({"query_fundamentals"}))

    def test_empty_called_tools_is_permissive_for_brackets(self) -> None:
        # Bracket form is unambiguous (emitted by the tool layer), so it
        # always suppresses even without a called-tools set.
        text = "Revenue was $24.7B [anything row 0]."
        assert _has_grounding_citation(text, 13, 18, frozenset())

    def test_empty_called_tools_rejects_prose_form(self) -> None:
        # Prose form requires cross-validation: ``according to filings``
        # must NOT suppress when no called-tools context is available,
        # otherwise the AMD-style hallucination regression returns.
        text = "Q2 revenue was $34.6B according to filings."
        assert not _has_grounding_citation(text, 16, 21, frozenset())


class TestValidatorIntegrationBug3:
    """End-to-end validator behaviour after Bug 3 fixes — the high-level
    contract that closes the user-facing issue."""

    def setup_method(self) -> None:
        self.v = NumericGroundingValidator()

    def test_unit_suffix_vs_raw_value_matches(self) -> None:
        """Answer says ``$24.7B``; tool row carries raw ``24700000000``
        as REVENUE — the validator must accept this (it already does via
        ``_decode_token``, but this is the regression guard for Bug 3)."""
        rows = [_row_with_value(24_700_000_000, FieldKind.REVENUE)]
        result = self.v.validate("Revenue was $24.7B last quarter.", rows)
        assert result.passed, result.unsupported

    def test_prose_cited_unsupported_number_is_suppressed(self) -> None:
        """A number the validator can't match against any tool row but
        with a prose citation to a real tool → NOT flagged. This is the
        exact false-positive the Bug 3 banner was firing on."""
        # No matching tool value, but the prose citation points at a tool
        # that was actually called.
        rows = [_row_with_value(1_000_000, FieldKind.REVENUE)]
        result = self.v.validate(
            "Q3 revenue was $24.7B per query_fundamentals row 0.",
            rows,
            called_tool_names=["query_fundamentals"],
        )
        # Citation suppression kicks in → no unsupported entry for $24.7B.
        revenue_failures = [u for u in result.unsupported if u.field_kind is FieldKind.REVENUE]
        assert not revenue_failures, result.unsupported

    def test_uncited_unsupported_number_still_flagged(self) -> None:
        """Negative-space check: a fabricated number with NO citation
        still trips the validator (no false negatives)."""
        rows = [_row_with_value(10_253_000_000, FieldKind.REVENUE)]
        result = self.v.validate(
            "Q2 revenue was $34.6B according to filings.",
            rows,
            called_tool_names=["query_fundamentals"],
        )
        assert not result.passed
        assert any(u.field_kind is FieldKind.REVENUE for u in result.unsupported)

    def test_normalisation_plus_citation_together(self) -> None:
        """Both fixes active: answer uses ``$24.7B`` (normalised form),
        tool returns raw ``24700000000``, and the answer also has a
        prose citation. Validator must pass cleanly."""
        rows = [_row_with_value(24_700_000_000, FieldKind.REVENUE)]
        result = self.v.validate(
            "Revenue was $24.7B (source: query_fundamentals row 0).",
            rows,
            called_tool_names=["query_fundamentals"],
        )
        assert result.passed, result.unsupported
