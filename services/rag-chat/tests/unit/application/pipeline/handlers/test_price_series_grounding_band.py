"""Cat-C C1 (2026-06-28) — price-series grounding emits summary stats + a per-bar band.

A SERIES answer ("plot NVDA last 90 days") cites N individual daily closes, but
the grounding bag emitted only 3 aggregate scalars (high/low/last-close), so the
judge could verify almost none of the series and floored it
(docs/audits/2026-06-28-cat-c-priceseries-judgenoise.md). The emission side now:

  * keeps the period-spanning summary stats (ticker/high/low/last-close), AND
  * emits a DOWN-SAMPLED band of per-bar ``(close, date)`` pairs — first / last /
    evenly-spaced interior — suffixed (``close_2``/``period_2`` …) so a
    representative subset of the series and its endpoints substantiate, capped at
    ``_PRICE_BAR_GROUNDING_MAX_ROWS`` to stay under the emission field cap.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _bar(date_str: str, *, high: float, low: float, close: float) -> dict[str, Any]:
    return {"date": date_str, "open": close, "high": high, "low": low, "close": close, "volume": 100}


def test_band_keeps_summary_and_adds_per_bar_closes() -> None:
    """Summary scalars survive; a band of suffixed per-bar closes is appended."""
    from rag_chat.application.pipeline.handlers.market import (
        _PRICE_BAR_GROUNDING_MAX_ROWS,
        _grounding_fields_from_bars,
    )

    # 10 bars: closes 100,110,...,190. ASC by date.
    bars = [
        _bar(f"2026-03-{i:02d}", high=c + 5, low=c - 5, close=c) for i, c in enumerate(range(100, 200, 10), start=1)
    ]
    gf = dict(_grounding_fields_from_bars(bars, ticker="NVDA"))

    # Summary stats unchanged.
    assert gf["ticker"] == "NVDA"
    assert gf["high"] == "195"  # max bar high (190 + 5)
    assert gf["low"] == "95"  # min bar low (100 - 5)
    assert gf["close"] == "190"  # latest bar close

    # A down-sampled band of per-bar closes is present (suffixed from _2).
    band_closes = {v for k, v in gf.items() if k.startswith("close_")}
    assert "100" in band_closes  # FIRST bar (endpoint)
    assert "190" in band_closes  # LAST bar (endpoint)
    # Band is capped — at most _PRICE_BAR_GROUNDING_MAX_ROWS per-bar closes.
    assert len([k for k in gf if k.startswith("close_")]) <= _PRICE_BAR_GROUNDING_MAX_ROWS


def test_band_emits_dates_for_specific_bar_citations() -> None:
    """Each band bar carries its date under a ``period`` key (allow-listed)."""
    from rag_chat.application.pipeline.handlers.market import _grounding_fields_from_bars

    bars = [
        _bar("2026-05-01", high=210, low=200, close=205),
        _bar("2026-05-12", high=220, low=210, close=215.20),
        _bar("2026-05-20", high=230, low=220, close=225),
    ]
    gf = dict(_grounding_fields_from_bars(bars, ticker="NVDA"))

    # The dates ride under period_* so "$215.20 on 2026-05-12" can bind to a bar.
    dates = {v for k, v in gf.items() if k.startswith("period")}
    assert "2026-05-01" in dates
    assert "2026-05-20" in dates
    # The interior close is verifiable too.
    closes = {gf["close"]} | {v for k, v in gf.items() if k.startswith("close_")}
    assert "215.2" in closes


def test_band_caps_long_series_with_endpoints() -> None:
    """A long (90-bar) series is down-sampled to the cap, retaining endpoints."""
    from rag_chat.application.pipeline.handlers.market import (
        _PRICE_BAR_GROUNDING_MAX_ROWS,
        _grounding_fields_from_bars,
    )

    bars = [
        _bar(f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}", high=i + 1, low=i - 1, close=float(i)) for i in range(90)
    ]
    gf = dict(_grounding_fields_from_bars(bars, ticker="NVDA"))

    n_band = len([k for k in gf if k.startswith("close_")])
    assert n_band <= _PRICE_BAR_GROUNDING_MAX_ROWS
    band_closes = {v for k, v in gf.items() if k.startswith("close_")}
    assert "0" in band_closes  # first bar (close 0.0 -> "0")
    assert "89" in band_closes  # last bar


def test_band_skips_bars_without_close() -> None:
    """A bar missing ``close`` never emits a phantom band entry."""
    from rag_chat.application.pipeline.handlers.market import _grounding_fields_from_bars

    bars = [
        {"date": "2026-06-10", "high": 10, "low": 9},  # no close
        _bar("2026-06-11", high=12, low=11, close=11.5),
    ]
    gf = dict(_grounding_fields_from_bars(bars, ticker="AAPL"))
    # Only the bar WITH a close contributes a band close.
    band_closes = [v for k, v in gf.items() if k.startswith("close_")]
    assert band_closes == ["11.5"]
