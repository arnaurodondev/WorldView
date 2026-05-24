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
