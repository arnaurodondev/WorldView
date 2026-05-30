"""FQA-04 / BP-626 regression — ``compare_entities`` must use the same
fundamentals data path as ``get_fundamentals_history_batch``.

Background:
    The original handler called ``S3Port.get_fundamentals_highlights`` which
    returns an EODHD-shaped dict (``RevenueTTM``, ``EarningsShare``,
    ``MarketCapitalization``...).  The renderer then looked up snake_case keys
    (``revenue``/``eps``/``gross_profit``) that are *not* present in that
    payload, so every fundamentals cell silently rendered as nothing.  The
    LLM filled the visible gaps with ``—`` placeholders and refused to
    fabricate numbers (audit ``docs/audits/2026-05-29-plan-0103-final-qa.md``
    §FQA-04).  Meanwhile the parallel ``get_fundamentals_history_batch`` path
    returned clean numeric values for the SAME tickers.

These tests assert the new contract:
    * The handler invokes ``get_fundamentals_history_batch`` exactly once
      for the whole ticker list.
    * Rendered output includes the latest-quarter Revenue/EPS/Gross Profit
      numbers (with formatted magnitudes) when batch data is present.
    * Highlights are used as a fallback ONLY for tickers whose batch row
      came back error/empty.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# Fixed UUIDs so the test is fully deterministic.
_NVDA_ID = UUID("018f0000-0000-7000-8000-00000000aa01")
_AMD_ID = UUID("018f0000-0000-7000-8000-00000000aa02")


def _make_s3(batch_results: dict, *, highlights: dict | None = None) -> AsyncMock:
    """Build an S3Port mock pre-wired for the new compare_entities contract."""
    mock = AsyncMock()
    # find_instrument_by_ticker is awaited per-ticker; return distinct UUIDs
    # so the mock call assertions can pin each ticker to its instrument.
    mock.find_instrument_by_ticker.side_effect = lambda ticker: {
        "NVDA": _NVDA_ID,
        "AMD": _AMD_ID,
    }.get(ticker)
    mock.get_quote.return_value = {"price": 425.10}
    # Highlights fallback — only used when batch entry is missing/empty.
    mock.get_fundamentals_highlights.return_value = highlights or {
        "MarketCapitalization": 800_000_000_000,
        "PERatio": 60.0,
        "RevenueTTM": 60_000_000_000,
        "DilutedEpsTTM": 3.02,
        "GrossProfitTTM": 22_000_000_000,
    }
    mock.get_fundamentals_history_batch.return_value = batch_results
    return mock


def _make_handler(s3: AsyncMock) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


def _batch_period(*, revenue: float, eps: float, gross: float, market_cap: float) -> dict:
    """Build one FundamentalsHistoryPeriod-shaped dict (as the adapter returns)."""
    return {
        "period": "Q1 2026",
        "period_end_date": "2026-03-31",
        "period_type": "QUARTERLY",
        "revenue": revenue,
        "gross_profit": gross,
        "net_income": None,
        "eps": eps,
        "pe_ratio": 65.0,
        "market_cap": market_cap,
    }


class TestCompareEntitiesUsesBatchPath:
    """The handler must route revenue/EPS/gross-profit through the batch."""

    @pytest.mark.asyncio
    async def test_renders_latest_quarter_numbers_from_batch(self) -> None:
        """Latest-quarter revenue/EPS/gross-profit MUST be non-empty when batch is healthy."""
        batch = {
            "NVDA": {
                "status": "ok",
                "periods": [
                    _batch_period(
                        revenue=44_100_000_000,
                        eps=5.16,
                        gross=33_400_000_000,
                        market_cap=4_500_000_000_000,
                    ),
                ],
            },
            "AMD": {
                "status": "ok",
                "periods": [
                    _batch_period(
                        revenue=7_440_000_000,
                        eps=0.78,
                        gross=3_900_000_000,
                        market_cap=820_000_000_000,
                    ),
                ],
            },
        }
        s3 = _make_s3(batch)
        handler = _make_handler(s3)

        items = await handler._handle_compare_entities(entity_tickers=["NVDA", "AMD"])

        # One RetrievedItem combining both tickers
        assert len(items) == 1
        text = items[0].text

        # Both tickers headlined
        assert "### NVDA" in text
        assert "### AMD" in text

        # Latest-quarter numbers must appear (raw values present so the
        # numeric-grounding validator can still match on tolerance).
        assert "44100000000" in text  # NVDA revenue raw
        assert "5.16" in text  # NVDA EPS
        assert "33400000000" in text  # NVDA gross profit raw

        assert "7440000000" in text  # AMD revenue raw
        assert "0.78" in text  # AMD EPS

        # Formatted magnitudes present (FIX-LIVE-DD requirement)
        assert "$44.10B" in text
        assert "$4.50T" in text  # NVDA market cap

        # And no "data unavailable" line — fundamentals path succeeded
        assert "data unavailable" not in text

    @pytest.mark.asyncio
    async def test_batch_called_once_for_whole_ticker_list(self) -> None:
        """A single batch HTTP call must cover all tickers (no N-fanout)."""
        batch = {
            t: {
                "status": "ok",
                "periods": [
                    _batch_period(
                        revenue=1_000_000_000,
                        eps=1.0,
                        gross=500_000_000,
                        market_cap=10_000_000_000,
                    ),
                ],
            }
            for t in ("NVDA", "AMD")
        }
        s3 = _make_s3(batch)
        handler = _make_handler(s3)

        await handler._handle_compare_entities(entity_tickers=["NVDA", "AMD"])

        # Exactly one batch call, with both tickers and periods=1
        assert s3.get_fundamentals_history_batch.await_count == 1
        kwargs = s3.get_fundamentals_history_batch.await_args.kwargs
        assert sorted(kwargs["tickers"]) == ["AMD", "NVDA"]
        assert kwargs["periods"] == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_highlights_when_batch_row_missing(self) -> None:
        """Batch error for one ticker → that ticker uses the highlights fallback."""
        batch = {
            "NVDA": {
                "status": "ok",
                "periods": [
                    _batch_period(
                        revenue=44_100_000_000,
                        eps=5.16,
                        gross=33_400_000_000,
                        market_cap=4_500_000_000_000,
                    ),
                ],
            },
            "AMD": {"status": "error", "reason": "no_quarterly_history"},
        }
        s3 = _make_s3(
            batch,
            highlights={
                "MarketCapitalization": 820_000_000_000,
                "PERatio": 60.0,
                "RevenueTTM": 37_400_000_000,
                "EarningsShare": 3.02,
                "GrossProfitTTM": 19_800_000_000,
            },
        )
        handler = _make_handler(s3)

        items = await handler._handle_compare_entities(entity_tickers=["NVDA", "AMD"])
        text = items[0].text

        # NVDA uses batch path
        assert "44100000000" in text  # batch revenue
        # AMD uses highlights path
        assert "37400000000" in text  # RevenueTTM via highlights fallback
        assert "3.02" in text  # EarningsShare via highlights fallback

        # Highlights is fetched ONLY for AMD (NVDA had a healthy batch row)
        called_for = [c.args[0] for c in s3.get_fundamentals_highlights.await_args_list]
        assert _AMD_ID in called_for
        assert _NVDA_ID not in called_for
