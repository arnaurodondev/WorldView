"""Cat-A FIX 3 (2026-06-28) — fundamentals table carries period_end + un-rounded values.

The LLM-visible fundamentals markdown table must let the model bind a quoted
figure to the EXACT period the user asked for, and answer a 3-decimal-precision
question without padding digits. Two rendering invariants
(docs/audits/2026-06-28-cat-a-period-selection.md):

  * every row renders an explicit ``Period End`` ISO-date column ALONGSIDE the
    fiscal ``Period`` label, so a question keyed on the period-end date ("fiscal
    Q4 2024 ending Sep 28 2024") can be matched by date, not just a fiscal label
    the model may mis-anchor (the Apple two-Sep-28-Q4s trap).
  * Revenue / Net Income are rendered UN-ROUNDED (full precision, "raw: <int>")
    next to the human-readable ``$X.XXXB`` form — the prior ``$X.1f B`` rounding
    made a 3-decimal answer impossible from the cell, so the model padded digits.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _make_handler() -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=None, s3_brief=None, timeout=5.0)


def test_table_renders_period_end_column_alongside_label() -> None:
    """The fiscal label AND the ISO period-end date both appear in the row."""
    handler = _make_handler()
    periods = [
        {
            "period": "Q4 FY2024",
            "period_end_date": "2024-09-28",
            "period_type": "QUARTERLY",
            "revenue": 94_930_000_000,
            "net_income": 14_736_000_000,
            "eps": 0.97,
        }
    ]
    table = handler._format_fundamentals_table("AAPL", periods)

    # Header advertises the new Period End column.
    assert "Period End" in table
    # The row binds the fiscal label to its unambiguous period-end date.
    assert "Q4 FY2024" in table
    assert "2024-09-28" in table


def test_table_renders_un_rounded_revenue_for_precision_questions() -> None:
    """Revenue cell carries BOTH the 3-decimal billions form and the raw integer.

    A "$94.930B" precision answer must be supportable from the cell, and the raw
    integer (94930000000) is what the matcher substantiates — so the displayed
    raw must equal the un-rounded value, not a padded ``$X.1f`` rounding.
    """
    handler = _make_handler()
    periods = [
        {
            "period": "Q4 FY2024",
            "period_end_date": "2024-09-28",
            "period_type": "QUARTERLY",
            "revenue": 94_930_000_000,
            "net_income": 14_736_000_000,
        }
    ]
    table = handler._format_fundamentals_table("AAPL", periods)

    # 3-decimal billions form (NOT the old $94.9B single-decimal rounding).
    assert "$94.930B" in table
    # Full-precision raw integer for the matcher / a precise answer.
    assert "raw: 94930000000" in table
    # Net income likewise un-rounded.
    assert "raw: 14736000000" in table


def test_table_tolerates_query_fundamentals_period_end_key() -> None:
    """``query_fundamentals`` rows key the date as ``period_end`` (no ``_date``)."""
    handler = _make_handler()
    periods = [
        {
            "period_label": "Q2 FY2026",
            "period": "Q2 FY2026",
            "period_end": "2026-03-31",
            "revenue": 81_600_000_000,
        }
    ]
    table = handler._format_fundamentals_table("AAPL", periods)
    assert "2026-03-31" in table


def test_table_missing_period_end_falls_back_to_dash() -> None:
    """A row with no period-end key still renders the column (as "—")."""
    handler = _make_handler()
    periods = [{"period": "Q2 FY2026", "revenue": 81_600_000_000}]
    table = handler._format_fundamentals_table("AAPL", periods)
    # Column present; the date cell degrades to a dash rather than vanishing.
    assert "Period End" in table
    assert "| Q2 FY2026 | — |" in table
