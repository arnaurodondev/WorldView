"""PLAN-0104 W32 — unified query_fundamentals handler tests.

Covers:
  * happy path: snapshot + period table rendered with coverage line
  * missing inputs degrade to None (R9 safe degradation)
  * upstream timeout → None, no fabricated row
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: Any) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


@pytest.mark.asyncio
async def test_query_fundamentals_renders_coverage_and_snapshot() -> None:
    """Happy path: coverage line, period table, snapshot block all present."""
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [
                {
                    "period_end": "2026-03-31",
                    "period_label": "Q2 FY2026",
                    "period_type": "QUARTERLY",
                    "gross_margin": 0.44,
                }
            ],
            "snapshot": {
                "forward_pe": 27.8,
                "peg_ratio": 2.15,
                "as_of": "2026-06-01",
                "source": "highlights",
            },
            "coverage": {"gross_margin": "ok", "forward_pe": "ok", "peg_ratio": "ok"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="AAPL",
        metrics=["gross_margin", "forward_pe", "peg_ratio"],
        periods=1,
    )
    assert result is not None
    text = result.text
    assert "AAPL fundamentals query" in text
    assert "Coverage:" in text
    assert "gross_margin=ok" in text
    assert "forward_pe=ok" in text
    # Margin rendered as percentage.
    assert "44.00%" in text
    # Snapshot block.
    assert "Snapshot" in text
    assert "27.80x" in text  # forward_pe
    assert "2.15" in text  # peg_ratio


@pytest.mark.asyncio
async def test_query_fundamentals_returns_none_on_missing_inputs() -> None:
    """Empty ticker or metric list → None (no fabricated row)."""
    s3 = AsyncMock()
    handler = _make_handler(s3)
    assert await handler._handle_query_fundamentals(ticker="", metrics=["revenue"]) is None
    assert await handler._handle_query_fundamentals(ticker="AAPL", metrics=[]) is None
    assert await handler._handle_query_fundamentals(ticker="AAPL", metrics=None) is None
    # Upstream MUST NOT have been called for any of these.
    s3.query_fundamentals.assert_not_called()


@pytest.mark.asyncio
async def test_query_fundamentals_returns_none_on_upstream_timeout() -> None:
    """asyncio.TimeoutError → None, no partial row."""
    s3 = AsyncMock()

    async def _raises(**_: Any) -> dict:
        raise TimeoutError

    s3.query_fundamentals = _raises
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="AAPL",
        metrics=["forward_pe"],
        periods=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_query_fundamentals_flags_missing_metric_in_coverage_line() -> None:
    """Missing-coverage metric is surfaced in the rendered text."""
    s3 = AsyncMock()
    s3.query_fundamentals = AsyncMock(
        return_value={
            "metrics_by_period": [],
            "snapshot": {"forward_pe": 27.8, "as_of": "2026-06-01", "source": "highlights"},
            "coverage": {"forward_pe": "ok", "consensus_eps_next_year": "missing"},
        }
    )
    handler = _make_handler(s3)
    result = await handler._handle_query_fundamentals(
        ticker="NVDA",
        metrics=["forward_pe", "consensus_eps_next_year"],
        periods=0,
    )
    assert result is not None
    assert "consensus_eps_next_year=missing" in result.text
    assert "forward_pe=ok" in result.text
