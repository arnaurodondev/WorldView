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

        # Exactly one batch call, with both tickers and periods=4
        # (PLAN-0103 W14 bumped from 1 → 4 so the handler can pick the
        # latest fully-populated common period rather than blindly trusting
        # the freshest row that might be NULL on one ticker but not another).
        assert s3.get_fundamentals_history_batch.await_count == 1
        kwargs = s3.get_fundamentals_history_batch.await_args.kwargs
        assert sorted(kwargs["tickers"]) == ["AMD", "NVDA"]
        assert kwargs["periods"] == 4

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


def _q_period(period: str, *, revenue: float | None, eps: float | None, gross: float | None) -> dict:
    """Build a period row with explicit period label so the selection helper has data to choose from.

    Used by the FQA-04 carry tests below to construct multi-period batch
    payloads where some periods are fully populated and others are not.
    """
    # Map the quarter prefix to its calendar end-date suffix. Kept on its own
    # line so the dict literal below stays within the 120-char line cap.
    _end_suffix = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}.get(period[:2], "12-31")
    return {
        "period": period,
        "period_end_date": f"{period[-4:]}-{_end_suffix}",
        "period_type": "QUARTERLY",
        "revenue": revenue,
        "gross_profit": gross,
        "net_income": None,
        "eps": eps,
        "pe_ratio": 65.0,
        "market_cap": 1_000_000_000_000,
    }


class TestCompareEntitiesPicksLatestFullyPopulatedCommonPeriod:
    """PLAN-0103 W14 / FQA-04 carry — period filter must align across tickers.

    Failure mode being prevented: ticker A has Q1 2026 reported but ticker B's
    Q1 2026 row is still pending (revenue/EPS NULL). The old ``periods=1``
    window forced the renderer to use B's latest = Q1 NULL, so the comparison
    table showed empty cells for B even though B's Q4 2025 row had the data.
    The new selector picks the LATEST period that is fully populated for BOTH
    tickers and renders that quarter for both.
    """

    @pytest.mark.asyncio
    async def test_picks_latest_common_fully_populated_period(self) -> None:
        """A's Q1 populated, B's Q1 NULL → both tickers render Q4 (the common populated period)."""
        # NVDA: Q4 2025 fully populated + Q1 2026 fully populated.
        # AMD:  Q4 2025 fully populated + Q1 2026 PENDING (NULL eps).
        # The intersection of fully-populated sets is {Q4 2025} → Q4 wins.
        batch = {
            "NVDA": {
                "status": "ok",
                "periods": [
                    _q_period("Q4 2025", revenue=40_000_000_000, eps=4.80, gross=30_000_000_000),
                    _q_period("Q1 2026", revenue=44_100_000_000, eps=5.16, gross=33_400_000_000),
                ],
            },
            "AMD": {
                "status": "ok",
                "periods": [
                    _q_period("Q4 2025", revenue=7_440_000_000, eps=0.78, gross=3_900_000_000),
                    # Pending Q1 2026 report — eps NULL is the signal it's not yet finalised.
                    _q_period("Q1 2026", revenue=7_500_000_000, eps=None, gross=3_950_000_000),
                ],
            },
        }
        s3 = _make_s3(batch)
        handler = _make_handler(s3)

        items = await handler._handle_compare_entities(entity_tickers=["NVDA", "AMD"])
        text = items[0].text

        # Both tickers must report the SAME period — the common fully-
        # populated one (Q4 2025), NOT each ticker's own latest.
        assert (
            text.count("Period: Q4 2025") == 2
        ), f"expected both tickers to render Q4 2025 (the common fully-populated period); got:\n{text}"
        assert "Period: Q1 2026" not in text, "Q1 2026 must NOT be picked because AMD's Q1 EPS is NULL"

        # And revenue + EPS + gross_profit MUST be present for BOTH tickers
        # (the user-visible symptom of the original bug was NULL cells).
        # EPS is rendered via Python's default float repr — "Eps: 4.8" not
        # "Eps: 4.80" — so we anchor on the labelled line to avoid string
        # collisions with bytes appearing elsewhere in the raw integers.
        assert "Eps: 4.8" in text  # NVDA Q4 EPS
        assert "Eps: 0.78" in text  # AMD Q4 EPS
        assert "40000000000" in text  # NVDA Q4 revenue raw
        assert "7440000000" in text  # AMD Q4 revenue raw

    @pytest.mark.asyncio
    async def test_falls_back_to_per_ticker_latest_when_no_common_period(self) -> None:
        """No common fully-populated period → preserve old per-ticker-latest behaviour.

        Defensive: a true data-pipeline gap (e.g. one ticker only reports
        annually, the other only quarterly) should still render SOMETHING
        rather than an empty table. The selector returns None in that case
        and the renderer falls back to ``periods_data[-1]`` per ticker.
        """
        batch = {
            "NVDA": {
                "status": "ok",
                "periods": [_q_period("Q1 2026", revenue=44_100_000_000, eps=5.16, gross=33_400_000_000)],
            },
            "AMD": {
                "status": "ok",
                # Different period set with no overlap to NVDA's populated periods.
                "periods": [_q_period("Q3 2025", revenue=6_800_000_000, eps=0.55, gross=3_400_000_000)],
            },
        }
        s3 = _make_s3(batch)
        handler = _make_handler(s3)

        items = await handler._handle_compare_entities(entity_tickers=["NVDA", "AMD"])
        text = items[0].text

        # Each ticker rendered its own latest period (the fallback path).
        assert "Period: Q1 2026" in text
        assert "Period: Q3 2025" in text


class TestSelectLatestFullyPopulatedPeriod:
    """Pure-helper unit tests for ``_select_latest_fully_populated_period``."""

    def test_returns_latest_common_period(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _select_latest_fully_populated_period

        batch = {
            "NVDA": {
                "status": "ok",
                "periods": [
                    _q_period("Q4 2025", revenue=1.0, eps=1.0, gross=1.0),
                    _q_period("Q1 2026", revenue=1.0, eps=1.0, gross=1.0),
                ],
            },
            "AMD": {
                "status": "ok",
                "periods": [
                    _q_period("Q4 2025", revenue=1.0, eps=1.0, gross=1.0),
                    _q_period("Q1 2026", revenue=1.0, eps=None, gross=1.0),  # not fully populated
                ],
            },
        }
        assert _select_latest_fully_populated_period(["NVDA", "AMD"], batch) == "Q4 2025"

    def test_returns_none_when_no_intersection(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _select_latest_fully_populated_period

        batch = {
            "A": {"status": "ok", "periods": [_q_period("Q1 2026", revenue=1.0, eps=1.0, gross=1.0)]},
            "B": {"status": "ok", "periods": [_q_period("Q3 2025", revenue=1.0, eps=1.0, gross=1.0)]},
        }
        assert _select_latest_fully_populated_period(["A", "B"], batch) is None

    def test_returns_none_when_ticker_status_not_ok(self) -> None:
        from rag_chat.application.pipeline.handlers.market import _select_latest_fully_populated_period

        batch = {
            "A": {"status": "ok", "periods": [_q_period("Q1 2026", revenue=1.0, eps=1.0, gross=1.0)]},
            "B": {"status": "error", "reason": "no_quarterly_history"},
        }
        assert _select_latest_fully_populated_period(["A", "B"], batch) is None


class TestCompareEntitiesNonUsCoverageSignal:
    """D8 (2026-07-06): non-US / unresolvable tickers (Samsung / Huawei / Xiaomi
    are not on our US universe) must yield an EXPLICIT not-covered / not-US-listed
    signal so synthesis says so, instead of the bare "data unavailable" line that
    let the model back-fill a WRONG entity (iter3_apple_competitors_spanish →
    hallucinated "Estée Lauder")."""

    @pytest.mark.asyncio
    async def test_non_us_ticker_renders_not_covered_signal(self) -> None:
        s3 = AsyncMock()
        # AAPL resolves (US-listed); SAMSUNG does not (non-US) → None.
        s3.find_instrument_by_ticker.side_effect = lambda ticker: {
            "AAPL": _NVDA_ID,
        }.get(ticker)
        s3.get_quote.return_value = {"price": 210.0}
        s3.get_fundamentals_highlights.return_value = {}
        s3.get_fundamentals_history_batch.return_value = {
            "AAPL": {"status": "ok", "periods": [_batch_period(revenue=90e9, eps=1.5, gross=40e9, market_cap=3e12)]},
        }
        handler = _make_handler(s3)
        results = await handler._handle_compare_entities(entity_tickers=["AAPL", "SAMSUNG"])
        assert len(results) == 1
        text = results[0].text
        # The unresolvable ticker is explicitly flagged not-covered / not-US-listed.
        assert "SAMSUNG" in text
        assert "not covered" in text.lower()
        assert "not us-listed" in text.lower() or "not us listed" in text.lower()

    @pytest.mark.asyncio
    async def test_all_non_us_emits_anti_fabrication_note(self) -> None:
        """When NO requested entity resolves, an explicit anti-fabrication coverage
        note is emitted so synthesis refuses rather than substituting a company."""
        s3 = AsyncMock()
        s3.find_instrument_by_ticker.side_effect = lambda ticker: None  # nothing US-listed
        s3.get_fundamentals_history_batch.return_value = {}
        handler = _make_handler(s3)
        results = await handler._handle_compare_entities(entity_tickers=["SAMSUNG", "HUAWEI"])
        assert len(results) == 1
        text = results[0].text.lower()
        assert "do not fabricate" in text
        assert "not available" in text
        # No grounding numbers were invented for the uncovered entities.
        assert results[0].grounding_fields == ()
