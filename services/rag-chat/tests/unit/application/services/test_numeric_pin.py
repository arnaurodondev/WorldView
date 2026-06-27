"""Tests for ``pin_numbers_to_tool_values`` (C1 #1 — FINAL-67 numeric fidelity).

The answer LLM rounds a tool figure it has in hand ($111.184B -> $111.200B).
This deterministic pin replaces a number that DRIFTED within 1% of an
entity-scoped same-kind tool value with the EXACT tool value, in the same
format. It is conservative: it never invents/removes numbers, only corrects
drift toward a value the tool actually returned, and only within a 1% band.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from rag_chat.application.services.numeric_grounding import (
    NumericPinResult,
    detect_fabricated_series,
    pin_numbers_to_tool_values,
)

from contracts.numeric_grounding import FieldKind

pytestmark = pytest.mark.unit


@dataclass
class _ToolRow:
    text: str = ""
    value: float | None = None
    field_kind: FieldKind | None = None
    item_id: str = ""


def _val(value: float, kind: FieldKind, item_id: str = "") -> _ToolRow:
    return _ToolRow(value=value, field_kind=kind, item_id=item_id)


# ── Core rounding-drift correction ────────────────────────────────────────────


def test_rounded_revenue_pinned_to_exact() -> None:
    """$111.200B (rounded) -> $111.184B (exact tool value). The canonical case."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    out = pin_numbers_to_tool_values("Apple revenue was $111.200B last quarter.", rows)
    assert isinstance(out, NumericPinResult)
    assert out.pin_count == 1
    assert "$111.184B" in out.text
    assert "$111.200B" not in out.text


def test_exact_value_is_noop() -> None:
    """An already-exact figure is left untouched (no pin)."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "Apple revenue was $111.184B last quarter."
    out = pin_numbers_to_tool_values(text, rows)
    assert out.pin_count == 0
    assert out.text == text


# ── Spelled-out magnitude words (billion / million / trillion) ────────────────


def test_spelled_out_billion_pinned() -> None:
    """'111.180 billion' (drifted) -> '111.184 billion' (exact). The dominant form."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    out = pin_numbers_to_tool_values("Apple revenue was 111.180 billion last quarter.", rows)
    assert out.pin_count == 1
    assert "111.184 billion" in out.text
    assert "111.180" not in out.text


def test_spelled_out_billion_with_currency() -> None:
    """'$111.180 billion' pins to the exact value, preserving '$' and ' billion'."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    out = pin_numbers_to_tool_values("Revenue was $111.180 billion.", rows)
    assert out.pin_count == 1
    assert "$111.184 billion" in out.text


def test_spelled_out_million() -> None:
    """A 'million' word token scales + pins correctly."""
    rows = [_val(54_781_000.0, FieldKind.REVENUE)]
    out = pin_numbers_to_tool_values("Net income was 54.780 million.", rows)
    assert out.pin_count == 1
    assert "54.781 million" in out.text


def test_spelled_out_exact_is_noop() -> None:
    """An exact spelled-out figure is left untouched."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "Apple revenue was 111.184 billion."
    out = pin_numbers_to_tool_values(text, rows)
    assert out.pin_count == 0
    assert out.text == text


def test_spelled_out_far_off_not_pinned() -> None:
    """'95.0 billion' is >1% off 111.184B → a different claim, not pinned."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "Apple revenue was 95.0 billion."
    out = pin_numbers_to_tool_values(text, rows)
    assert out.pin_count == 0
    assert out.text == text


def test_far_off_number_not_pinned() -> None:
    """A number >1% off is a DIFFERENT claim, not a transcription slip — left alone."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "Apple revenue was $90.000B last quarter."  # ~19% off
    out = pin_numbers_to_tool_values(text, rows)
    assert out.pin_count == 0
    assert out.text == text


def test_decimal_precision_preserved() -> None:
    """The pin mirrors the token's decimal places (1 dp stays 1 dp)."""
    rows = [_val(489.73, FieldKind.PRICE)]
    out = pin_numbers_to_tool_values("MSFT high was $489.7 this year.", rows)
    # 489.7 vs 489.73 is within 1%; pinned but kept to 1 dp -> 489.7 (no change)
    # so this is effectively exact at the rendered precision: no spurious churn.
    assert "$489.7" in out.text


def test_no_pin_without_tool_values() -> None:
    """Empty tool results → never touch the text."""
    out = pin_numbers_to_tool_values("Revenue was $111.200B.", [])
    assert out.pin_count == 0
    assert out.text == "Revenue was $111.200B."


def test_sign_flip_not_pinned() -> None:
    """A loss reported as a gain (sign flip) is a real error, never silently pinned."""
    rows = [_val(-5_000_000_000.0, FieldKind.REVENUE)]
    text = "Net income was $5.000B."
    out = pin_numbers_to_tool_values(text, rows)
    assert out.pin_count == 0
    assert out.text == text


# ── Entity scoping ────────────────────────────────────────────────────────────


def test_entity_scoped_pin_does_not_cross_entities() -> None:
    """An NVDA-attributed number drifts toward NVDA's value, never AMD's.

    The text says 'NVDA ... $81.500B'; NVDA's tool value is 81.6B (within 1%),
    AMD's is 10.3B. The pin must choose NVDA's exact value, not AMD's.
    """
    rows = [
        _val(81_600_000_000.0, FieldKind.REVENUE, item_id="NVDA_2026Q1"),
        _val(10_300_000_000.0, FieldKind.REVENUE, item_id="AMD_2026Q1"),
    ]
    out = pin_numbers_to_tool_values("NVDA revenue was $81.500B.", rows)
    assert out.pin_count == 1
    assert "$81.600B" in out.text
    assert "10.3" not in out.text


def test_multiple_numbers_each_pinned_independently() -> None:
    """Two drifted figures both get corrected in one pass."""
    rows = [
        _val(81_600_000_000.0, FieldKind.REVENUE, item_id="NVDA_2026Q1"),
        _val(10_300_000_000.0, FieldKind.REVENUE, item_id="AMD_2026Q1"),
    ]
    text = "NVDA revenue was $81.500B and AMD revenue was $10.250B."
    out = pin_numbers_to_tool_values(text, rows)
    assert out.pin_count == 2
    assert "$81.600B" in out.text
    assert "$10.300B" in out.text


def test_citation_marker_digit_not_treated_as_claim() -> None:
    """A [N1] citation marker digit must not be pinned."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "Apple revenue was $111.184B [N1]."
    out = pin_numbers_to_tool_values(text, rows)
    # Exact value + only a marker digit present → no pin, marker untouched.
    assert out.pin_count == 0
    assert "[N1]" in out.text


# ── C1 #2: fabricated-series detector ─────────────────────────────────────────

# Mirrors da_apple_revenue_fy2024q4_precision: tool returned ONE period; the
# answer fabricated a multi-quarter table.
_FABRICATED_TABLE_ANSWER = (
    "Apple revenue by quarter:\n\n"
    "| Period | Revenue (B USD) |\n"
    "|--------|------------------|\n"
    "| Q1 FY2025 | 124.300 |\n"
    "| Q2 FY2025 | 95.400 |\n"
    "| Q3 FY2025 | 94.000 |\n"
    "| Q4 FY2024 | 102.500 |\n"
)


def test_fabricated_multirow_table_detected() -> None:
    """Tool has 1 value but the answer presents a 4-row invented table → fires."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    assert detect_fabricated_series(_FABRICATED_TABLE_ANSWER, rows) is True


def test_table_matching_tool_values_not_flagged() -> None:
    """A multi-row table whose numbers ALL come from tool values is legitimate."""
    rows = [
        _val(124_300_000_000.0, FieldKind.REVENUE),
        _val(95_400_000_000.0, FieldKind.REVENUE),
        _val(94_000_000_000.0, FieldKind.REVENUE),
        _val(102_500_000_000.0, FieldKind.REVENUE),
    ]
    assert detect_fabricated_series(_FABRICATED_TABLE_ANSWER, rows) is False


def test_prose_answer_never_flagged() -> None:
    """A plain prose answer (no Markdown table) is never a fabricated series."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "Apple revenue for the quarter was $111.184B, up year over year."
    assert detect_fabricated_series(text, rows) is False


def test_single_extra_row_below_threshold_not_flagged() -> None:
    """A 2-row table is below the 3-row minimum — too small to call fabricated."""
    rows = [_val(111_184_000_000.0, FieldKind.REVENUE)]
    text = "| Period | Revenue |\n|--|--|\n| Q4 FY2024 | 102.500 |\n| Q1 FY2025 | 124.300 |\n"
    assert detect_fabricated_series(text, rows) is False


def test_no_tool_values_does_not_fire() -> None:
    """Empty pool is handled elsewhere; the detector must not also fire."""
    assert detect_fabricated_series(_FABRICATED_TABLE_ANSWER, []) is False


def test_table_within_tool_row_count_not_flagged() -> None:
    """When the tool returned >= as many values as table rows, no over-claim."""
    rows = [_val(float(900 + i), FieldKind.REVENUE) for i in range(10)]
    # 10 tool values, 4 table rows → answer does not claim MORE than the tool.
    assert detect_fabricated_series(_FABRICATED_TABLE_ANSWER, rows) is False
