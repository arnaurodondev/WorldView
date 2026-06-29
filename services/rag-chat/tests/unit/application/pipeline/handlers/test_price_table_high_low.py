"""Cat-B B2 (2026-06-28) — price table renders High/Low + a window-summary line.

The window high/low were computed into ``grounding_fields`` (the eval wire) but
NEVER into ``item.text`` (the LLM context), so the model truthfully reported
"the data does not contain daily high and low" for a YTD-range question — a
split-brain that floored ``tc_price_history_msft_ytd_range``
(docs/audits/2026-06-28-cat-b-screener-missingness.md). The fix renders:

  * per-bar ``High`` / ``Low`` columns in the markdown table, and
  * a prepended aggregated ``Window summary`` line (high / low / range /
    first-close / last-close / N-bars) so a "high and low so far this year"
    question can copy the aggregate rather than fold ~120 bars itself.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _make_handler() -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=None, s3_brief=None, timeout=5.0)


def _bar(date_str: str, *, high: float, low: float, close: float) -> dict[str, Any]:
    return {"date": date_str, "open": close, "high": high, "low": low, "close": close, "volume": 1_000}


def test_table_has_high_low_columns_and_values() -> None:
    """Per-bar high/low are now visible in the LLM-facing table text."""
    handler = _make_handler()
    bars = [
        _bar("2026-01-05", high=400.00, low=344.79, close=360.00),
        _bar("2026-06-12", high=489.70, low=455.00, close=365.46),
    ]
    table = handler._format_price_table("MSFT", "2026-01-01", "2026-06-29", "day", bars)

    # Header carries the two new columns.
    assert "High" in table
    assert "Low" in table
    # Per-bar extrema are rendered (not just the close).
    assert "$489.70" in table
    assert "$344.79" in table


def test_table_prepends_window_summary_aggregate() -> None:
    """The aggregated window high/low/range/last-close are on one summary line."""
    handler = _make_handler()
    bars = [
        _bar("2026-01-05", high=400.00, low=344.79, close=360.00),
        _bar("2026-03-10", high=489.70, low=420.00, close=470.00),
        _bar("2026-06-12", high=465.00, low=455.00, close=365.46),
    ]
    table = handler._format_price_table("MSFT", "2026-01-01", "2026-06-29", "day", bars)

    assert "Window summary:" in table
    assert "high $489.70" in table  # max across the window
    assert "low $344.79" in table  # min across the window
    assert "range $144.91" in table  # 489.70 - 344.79
    assert "first close $360.00" in table
    assert "last close $365.46" in table
    assert "3 bars" in table


def test_table_tolerates_bars_without_extrema() -> None:
    """A close-only bar renders "—" for high/low and never poisons the summary."""
    handler = _make_handler()
    bars = [
        {"date": "2026-06-11", "close": 100.0, "volume": 1},  # no high/low
        _bar("2026-06-12", high=110.0, low=95.0, close=105.0),
    ]
    table = handler._format_price_table("AAPL", "2026-06-11", "2026-06-12", "day", bars)

    # The close-only bar shows a dash in its high/low cells (no fabricated 0).
    assert "| 2026-06-11 | — | — | $100.00 |" in table
    # The summary uses only the bar that HAS extrema.
    assert "high $110.00" in table
    assert "low $95.00" in table
