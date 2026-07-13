"""D-b + D-h regression — batch fundamentals date-anchoring and margin/yield units.

D-b: ``get_fundamentals_history_batch`` must honour an explicit [from_date,
to_date] window (over-fetch + window-filter, same as the singular tool) so a
multi-entity historical question ("compare NVDA vs AMD FY2024 Q3 revenue") gets
the RIGHT quarter — not the latest N. A ticker with rows but none in the window
must surface an explicit per-entity "not covered" line (no numbers) so the model
cannot fabricate / cross-attribute a figure for it (the AMD empty-2nd-entity
case, ru_nvda_amd_compare).

D-h: margins render x100 with a magnitude sanity-gate that never emits an
implausible (>100%) yield.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: AsyncMock) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


def _row(period: str, period_end: str, revenue: float) -> dict[str, Any]:
    return {
        "period": period,
        "period_end_date": period_end,
        "period_type": "QUARTERLY",
        "revenue": revenue,
        "gross_profit": None,
        "net_income": None,
        "eps": None,
        "ebitda": None,
        "pe_ratio": 30.0,
        "market_cap": 1_000_000_000_000,
    }


_NVDA_ROWS = [
    _row("Q1 2026", "2026-03-31", 44_100_000_000.0),
    _row("Q4 2025", "2025-12-31", 39_300_000_000.0),
    _row("Q3 2024", "2024-09-30", 18_120_000_000.0),
    _row("Q2 2024", "2024-06-30", 13_500_000_000.0),
]


class TestBatchDateAnchoring:
    @pytest.mark.asyncio
    async def test_batch_window_keeps_only_in_window_rows(self) -> None:
        """A 2024 window renders ONLY 2024 rows for each ticker — not the latest N."""
        s3 = AsyncMock()
        s3.get_fundamentals_history_batch.return_value = {
            "NVDA": {"status": "ok", "periods": list(_NVDA_ROWS)},
        }
        handler = _make_handler(s3)
        items = await handler._handle_get_fundamentals_history_batch(
            tickers=["NVDA"],
            periods=4,
            from_date="2024-01-01",
            to_date="2024-12-31",
        )
        assert len(items) == 1
        text = items[0].text
        assert "Q3 2024" in text and "Q2 2024" in text
        # The latest (wrong-year) quarters must not leak.
        assert "Q1 2026" not in text and "Q4 2025" not in text

    @pytest.mark.asyncio
    async def test_batch_window_widens_the_upstream_fetch(self) -> None:
        """With a historical window the batch over-fetches past the caller's periods."""
        s3 = AsyncMock()
        s3.get_fundamentals_history_batch.return_value = {"NVDA": {"status": "ok", "periods": list(_NVDA_ROWS)}}
        handler = _make_handler(s3)
        await handler._handle_get_fundamentals_history_batch(
            tickers=["NVDA"],
            periods=4,
            from_date="2024-01-01",
            to_date="2024-12-31",
        )
        called = s3.get_fundamentals_history_batch.call_args.kwargs["periods"]
        assert 4 < called <= 20, f"fetch was not widened to reach the window: {called}"

    @pytest.mark.asyncio
    async def test_batch_empty_second_entity_surfaces_not_covered(self) -> None:
        """AMD has no rows in the 2024 window → explicit per-entity 'not covered'.

        The model must not be able to fabricate or cross-attribute a figure for
        the empty entity (ru_nvda_amd_compare).
        """
        s3 = AsyncMock()
        s3.get_fundamentals_history_batch.return_value = {
            "NVDA": {"status": "ok", "periods": list(_NVDA_ROWS)},
            # AMD only has 2026 rows — nothing in the 2024 window.
            "AMD": {"status": "ok", "periods": [_row("Q1 2026", "2026-03-31", 7_440_000_000.0)]},
        }
        handler = _make_handler(s3)
        items = await handler._handle_get_fundamentals_history_batch(
            tickers=["NVDA", "AMD"],
            periods=4,
            from_date="2024-01-01",
            to_date="2024-12-31",
        )
        by_ticker = {it.citation_meta.entity_name: it for it in items}
        assert "NVDA" in by_ticker and "AMD" in by_ticker
        amd = by_ticker["AMD"]
        assert "not covered" in amd.text.lower()
        # AMD's out-of-window figure must NOT appear, and it carries no grounding
        # numbers to hallucinate from.
        assert "7.44" not in amd.text and "7440000000" not in amd.text
        assert amd.grounding_fields == ()

    @pytest.mark.asyncio
    async def test_batch_no_window_preserves_latest_n(self) -> None:
        """Without a window the batch is unchanged — latest rows render, no widening."""
        s3 = AsyncMock()
        s3.get_fundamentals_history_batch.return_value = {"NVDA": {"status": "ok", "periods": list(_NVDA_ROWS)}}
        handler = _make_handler(s3)
        items = await handler._handle_get_fundamentals_history_batch(tickers=["NVDA"], periods=4)
        assert "Q1 2026" in items[0].text
        assert s3.get_fundamentals_history_batch.call_args.kwargs["periods"] == 4


class TestMarginYieldUnits:
    def test_fraction_margin_scaled_to_percent(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _format_ratio_as_percent

        # 0.7493 gross margin → 74.93% (the ru_nvda_amd "0.7%" bug is x100 now).
        assert _format_ratio_as_percent(0.7493) == "74.93%"
        # A tiny ratio still scales correctly.
        assert _format_ratio_as_percent(0.0268) == "2.68%"

    def test_already_percent_value_not_double_scaled(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _format_ratio_as_percent

        # 2.68 (already a percent, EODHD dividend-yield shape) stays 2.68% — NOT 268%.
        assert _format_ratio_as_percent(2.68) == "2.68%"

    def test_implausible_yield_suppressed(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _format_ratio_as_percent

        # A value whose percent exceeds 100% is not meaningful for a margin/yield
        # → suppressed (the XLU 268% / XLE 265% bug can never be emitted).
        assert _format_ratio_as_percent(268.0) is None
        assert _format_ratio_as_percent(2.68 * 100) is None  # 268 → None

    def test_negative_margin_preserved(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _format_ratio_as_percent

        assert _format_ratio_as_percent(-0.15) == "-15.00%"

    def test_non_numeric_returns_none(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _format_ratio_as_percent

        assert _format_ratio_as_percent(None) is None
        assert _format_ratio_as_percent("n/a") is None
