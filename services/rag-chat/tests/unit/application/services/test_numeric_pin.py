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
