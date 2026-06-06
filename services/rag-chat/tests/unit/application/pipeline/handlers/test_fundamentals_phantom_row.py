"""PLAN-0103 W24 / BP-639 regression — phantom-row guard on singular
``_handle_get_fundamentals_history`` path.

Background:
    EODHD pre-emits a future-dated row in ``EARNINGS_HISTORY`` whose every
    flow metric is null. Market-data filters these (PLAN-0103 W22), but the
    rag-chat handler must also drop any phantom row that slips through —
    otherwise a single all-null row triggers ``item_count=1`` and the LLM
    fabricates values from training knowledge (audit
    ``docs/audits/2026-06-01-chat-quality-aapl-pe-investigation.md``).

    This is the singular-path analogue of the batch-path guard landed as
    BP-626 / PLAN-0103 W4.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: AsyncMock) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


@pytest.mark.asyncio
async def test_singular_handler_drops_all_phantom_rows_and_returns_none() -> None:
    """When every row is a phantom (all flow metrics null), return None.

    The orchestrator interprets None as "no item" so item_count stays 0 and
    the LLM follows the FORBIDDEN-fabrication rule rather than quoting the
    placeholder.
    """
    s3 = AsyncMock()
    # One row, every flow metric null — the EODHD future-dated placeholder
    # pattern that motivated this fix.
    s3.get_fundamentals_history.return_value = [
        {
            "period": "Q3 FY2026",
            "period_end_date": "2026-06-30",
            "period_type": "QUARTERLY",
            "revenue": None,
            "gross_profit": None,
            "net_income": None,
            "eps": None,
            "ebitda": None,
            # Snapshot fields are intentionally non-null — they're not flow
            # metrics so they must NOT save the row from the phantom filter.
            "pe_ratio": 37.7,
            "market_cap": 3_000_000_000_000,
        }
    ]

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)

    assert result is None, "phantom row leaked through — LLM will fabricate values"


@pytest.mark.asyncio
async def test_singular_handler_keeps_rows_with_at_least_one_flow_metric() -> None:
    """A row with a single populated flow metric (e.g. eps only) must survive.

    The phantom guard predicate is "ALL flow metrics null" — partial-fill
    rows are legitimate and must reach the renderer.
    """
    s3 = AsyncMock()
    s3.get_fundamentals_history.return_value = [
        {
            "period": "Q2 FY2026",
            "period_end_date": "2026-03-31",
            "period_type": "QUARTERLY",
            "revenue": None,
            "gross_profit": None,
            "net_income": None,
            "eps": 2.01,
            "ebitda": None,
            "pe_ratio": 32.5,
            "market_cap": 3_000_000_000_000,
        }
    ]

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)

    assert result is not None, "legitimate partial-fill row was incorrectly dropped"
    # The renderer output must include the surviving EPS value.
    assert "2.01" in result.text


@pytest.mark.asyncio
async def test_singular_handler_filters_phantom_and_keeps_real_row() -> None:
    """Mixed input: 1 real row + 1 phantom row → only the real row renders."""
    s3 = AsyncMock()
    s3.get_fundamentals_history.return_value = [
        {
            "period": "Q2 FY2026",
            "period_end_date": "2026-03-31",
            "period_type": "QUARTERLY",
            "revenue": 95_000_000_000.0,
            "gross_profit": 42_000_000_000.0,
            "net_income": 23_000_000_000.0,
            "eps": 2.01,
            "ebitda": 30_000_000_000.0,
            "pe_ratio": 32.5,
            "market_cap": 3_000_000_000_000,
        },
        {
            "period": "Q3 FY2026",
            "period_end_date": "2026-06-30",
            "period_type": "QUARTERLY",
            "revenue": None,
            "gross_profit": None,
            "net_income": None,
            "eps": None,
            "ebitda": None,
            "pe_ratio": 37.7,
            "market_cap": 3_000_000_000_000,
        },
    ]

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=2)

    assert result is not None
    # The real row's revenue must be in the rendered table.
    assert "95.0B" in result.text
    # The phantom row's period must NOT be rendered (the entire row was dropped).
    assert "Q3 FY2026" not in result.text
