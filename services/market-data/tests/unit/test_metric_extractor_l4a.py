"""Wave L-4a unit tests for the snapshot writer's analyst / ownership / short fields.

WHY THIS FILE:
  PLAN-0089 Wave L-4a adds four screener-surfaceable fields sourced from the
  EODHD ``analyst_consensus`` and ``share_statistics`` JSONB sections. The
  extraction lives in ``derive_fundamentals_snapshot`` (the snapshot writer),
  not the section-level ``metric_extractor.py``, because the four targets
  are columns on ``instrument_fundamentals_snapshot`` rather than rows in
  ``fundamental_metrics``. The file name keeps the "metric_extractor_l4a"
  label per the task spec but the unit under test is the writer.

UNIT CONVENTION (verified by every test below):
  * ``institutional_ownership_pct``  stored as decimal fraction (÷ 100 from EODHD)
  * ``short_percent``                stored as decimal fraction (passthrough)
  * ``analyst_consensus_rating``     1-5 scale (higher = more bullish for TEXT;
                                     numeric raw values pass through unchanged)
  * ``analyst_target_price``         USD passthrough

Refs: docs/audits/2026-05-28-wave-l4-scope-investigation.md §3, §7.
"""

from __future__ import annotations

import pytest
from market_data.infrastructure.db.fundamentals_snapshot_writer import (
    _CONSENSUS_RATING_MAP,
    _consensus_rating,
    derive_fundamentals_snapshot,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test fixtures — realistic EODHD payload fragments
# ---------------------------------------------------------------------------


def _full_l4a_sections() -> dict[str, dict[str, object]]:
    """Return a complete set of L-4a-relevant section payloads (AAPL-shaped)."""
    return {
        "analyst_consensus": {
            # EODHD AnalystRatings keys — numeric Rating exercises the
            # numeric-passthrough branch.
            "TargetPrice": 245.5,
            "Rating": 2.0,
            "StrongBuy": 12,
            "Buy": 20,
            "Hold": 8,
            "Sell": 1,
            "StrongSell": 0,
        },
        "share_statistics": {
            # SharesStats keys — note the unit divergence intentionally
            # exercised by the writer: PercentInstitutions is a percent
            # while ShortPercentOfFloat is a fraction.
            "PercentInstitutions": 74.3,
            "ShortPercentOfFloat": 0.034,
            "SharesOutstanding": 15_700_000_000,
        },
    }


# ---------------------------------------------------------------------------
# All-fields-populated path
# ---------------------------------------------------------------------------


def test_derive_populates_all_four_l4a_fields_from_full_payload() -> None:
    """When both source sections are present, all four columns are set."""
    sections = _full_l4a_sections()
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus=sections["analyst_consensus"],
        share_statistics=sections["share_statistics"],
    )

    # target price is a USD passthrough
    assert snap["analyst_target_price"] == pytest.approx(245.5)
    # Raw numeric Rating 2.0 (EODHD "Buy") flips to bullish-up 4.0 per QA
    # finding #1 (storage convention: higher = more bullish, matches text mapping).
    assert snap["analyst_consensus_rating"] == pytest.approx(4.0)
    # PercentInstitutions 74.3 → 0.743 fraction (audit §7 risk addressed)
    assert snap["institutional_ownership_pct"] == pytest.approx(0.743, abs=1e-9)
    # ShortPercentOfFloat 0.034 already a fraction — passthrough
    assert snap["short_percent"] == pytest.approx(0.034)


# ---------------------------------------------------------------------------
# Unit normalisation — institutional ownership ÷ 100
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_percent", "expected_fraction"),
    [
        (74.3, 0.743),
        (100.0, 1.0),
        (0.0, 0.0),
        (5.5, 0.055),
    ],
)
def test_institutional_ownership_pct_normalised_to_fraction(raw_percent: float, expected_fraction: float) -> None:
    """EODHD reports as percent; writer must divide by 100 → decimal fraction."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus=None,
        share_statistics={"PercentInstitutions": raw_percent},
    )
    assert snap["institutional_ownership_pct"] == pytest.approx(expected_fraction, abs=1e-9)


def test_short_percent_passthrough_as_fraction() -> None:
    """EODHD ShortPercentOfFloat is already a fraction; writer must NOT divide."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus=None,
        share_statistics={"ShortPercentOfFloat": 0.034},
    )
    assert snap["short_percent"] == pytest.approx(0.034)


def test_short_percent_live_eodhd_key_short_percent_float() -> None:
    """Regression (backend-gaps wave 3, 2026-06-11): the LIVE EODHD payload key.

    The real SharesStats section uses ``ShortPercentFloat`` (verified against
    /api/fundamentals/AAPL.US?filter=SharesStats). The original probe list only
    tried ``ShortPercentOfFloat`` variants, so short_percent stayed NULL for
    every snapshot row (649/649 NULL in the dev DB).
    """
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus=None,
        share_statistics={"ShortPercentFloat": 0.0106, "ShortPercentOutstanding": None},
    )
    assert snap["short_percent"] == pytest.approx(0.0106)


def test_short_percent_falls_back_to_outstanding_when_float_missing() -> None:
    """ShortPercentOutstanding is the last-resort key (same fraction unit)."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus=None,
        share_statistics={"ShortPercentOutstanding": 0.009},
    )
    assert snap["short_percent"] == pytest.approx(0.009)


# ---------------------------------------------------------------------------
# Missing / null source fields → column stays None
# ---------------------------------------------------------------------------


def test_missing_section_leaves_columns_none() -> None:
    """When both sections are absent (None), all four L-4a columns are None."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus=None,
        share_statistics=None,
    )
    assert snap["analyst_target_price"] is None
    assert snap["analyst_consensus_rating"] is None
    assert snap["institutional_ownership_pct"] is None
    assert snap["short_percent"] is None


def test_empty_section_leaves_columns_none() -> None:
    """Empty-dict sections behave the same as missing — all None."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus={},
        share_statistics={},
    )
    assert snap["analyst_target_price"] is None
    assert snap["analyst_consensus_rating"] is None
    assert snap["institutional_ownership_pct"] is None
    assert snap["short_percent"] is None


def test_partial_section_leaves_missing_keys_none() -> None:
    """When only one of the two keys is present, the other stays None."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus={"TargetPrice": 100.0},  # no Rating
        share_statistics={"PercentInstitutions": 50.0},  # no ShortPercentOfFloat
    )
    assert snap["analyst_target_price"] == pytest.approx(100.0)
    assert snap["analyst_consensus_rating"] is None
    assert snap["institutional_ownership_pct"] == pytest.approx(0.5, abs=1e-9)
    assert snap["short_percent"] is None


# ---------------------------------------------------------------------------
# Consensus rating text → numeric mapping (per task spec)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text_value", "expected_numeric"),
    [
        ("Buy", 4.0),
        ("Hold", 3.0),
        ("Sell", 2.0),
        ("Strong Buy", 5.0),
        ("Strong Sell", 1.0),
        # Case-insensitivity guard
        ("buy", 4.0),
        ("STRONG BUY", 5.0),
        # Internal whitespace tolerance
        ("Strong  Buy", 5.0),
    ],
)
def test_consensus_rating_text_to_numeric_mapping(text_value: str, expected_numeric: float) -> None:
    """Text labels must map to the WL-4a 1-5 scale defined by the task spec."""
    assert _consensus_rating(text_value) == expected_numeric


def test_consensus_rating_unknown_text_returns_none() -> None:
    """Labels outside the documented mapping return None (no silent fallback)."""
    assert _consensus_rating("Overweight") is None
    assert _consensus_rating("???") is None


@pytest.mark.parametrize(
    ("numeric_value", "expected_stored"),
    [
        # EODHD native scale is inverted (1 = Strong Buy, 5 = Strong Sell).
        # Storage convention is bullish-up (5 = Strong Buy). Each EODHD
        # numeric is flipped via ``6 - x`` so the stored value matches the
        # text mapping above.
        (1.0, 5.0),  # EODHD "Strong Buy" numeric → bullish 5
        (2.0, 4.0),  # EODHD "Buy" numeric → bullish 4
        (3.0, 3.0),  # EODHD "Hold" → 3 (midpoint, invariant under 6 - x)
        (4.0, 2.0),  # EODHD "Sell" numeric → bearish 2
        (5.0, 1.0),  # EODHD "Strong Sell" numeric → bearish 1
        (2, 4.0),  # int coercion path
        ("3.5", 2.5),  # numeric-string coercion path
    ],
)
def test_consensus_rating_numeric_unified_scale(numeric_value: object, expected_stored: float) -> None:
    """Numeric inputs on EODHD's 1-5 scale are flipped to bullish-up storage (QA finding #1)."""
    assert _consensus_rating(numeric_value) == pytest.approx(expected_stored)


@pytest.mark.parametrize("out_of_range", [0.5, 0.0, 5.5, 6.0, -1.0, 10.0])
def test_consensus_rating_numeric_out_of_range_returns_none(out_of_range: float) -> None:
    """Numeric values outside the documented EODHD 1-5 band are dropped (QA finding #1)."""
    assert _consensus_rating(out_of_range) is None


def test_consensus_rating_map_covers_documented_labels() -> None:
    """Sanity guard: the static mapping has exactly the five documented labels."""
    assert set(_CONSENSUS_RATING_MAP) == {
        "strong buy",
        "buy",
        "hold",
        "sell",
        "strong sell",
    }


def test_derive_with_text_rating_uses_mapping() -> None:
    """Integration: a text-rating payload produces the mapped numeric value."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        analyst_consensus={"TargetPrice": 150.0, "Rating": "Buy"},
        share_statistics=None,
    )
    # "Buy" → 4.0 per task spec mapping
    assert snap["analyst_consensus_rating"] == pytest.approx(4.0)
    assert snap["analyst_target_price"] == pytest.approx(150.0)


# ---------------------------------------------------------------------------
# Forward-compat — pre-WL-4a callers (no new kwargs) still work
# ---------------------------------------------------------------------------


def test_derive_without_new_kwargs_returns_none_for_l4a_fields() -> None:
    """Callers that do NOT supply the new kwargs still get a complete dict.

    Guards R11 forward-compat: any consumer constructed before WL-4a must
    keep working with no code change. The four new keys appear in the
    returned dict with ``None`` values.
    """
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
    )
    for key in (
        "analyst_target_price",
        "analyst_consensus_rating",
        "institutional_ownership_pct",
        "short_percent",
    ):
        assert key in snap, f"L-4a key '{key}' missing from snapshot dict"
        assert snap[key] is None
