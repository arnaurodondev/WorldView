"""PLAN-0104 W30 / BP-649 — Forward P/E + PEG rows in snapshot block.

Verifies the singular get_fundamentals_history handler renders the new
forward-valuation fields when the upstream snapshot provides them, and
omits them otherwise (the v1.5 prompt instructs the LLM to refuse rather
than fabricate when a snapshot field is missing).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _make_handler(s3: Any) -> Any:
    from rag_chat.application.pipeline.handlers.market import MarketHandler

    return MarketHandler(s3=s3, s3_brief=None, timeout=5.0)


def _periods() -> list[dict]:
    return [
        {
            "period": "Q2 FY2026",
            "period_end_date": "2026-03-31",
            "period_type": "QUARTERLY",
            "revenue": 95_000_000_000.0,
            "gross_profit": 42_000_000_000.0,
            "net_income": 23_000_000_000.0,
            "eps": 2.01,
            "ebitda": 30_000_000_000.0,
            "pe_ratio": None,
            "market_cap": None,
        }
    ]


@pytest.mark.asyncio
async def test_snapshot_block_renders_forward_pe_and_peg_rows_when_present() -> None:
    s3 = AsyncMock()
    s3.get_fundamentals_history_with_snapshot.return_value = {
        "periods": _periods(),
        "current_snapshot": {
            "pe_ratio": 30.4,
            "forward_pe": 27.8,
            "peg_ratio": 2.15,
            "as_of": "2026-06-01",
            "source": "highlights",
        },
    }
    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)
    assert result is not None
    text = result.text
    assert "Current Snapshot" in text
    assert "Forward P/E" in text
    assert "27.80x" in text
    assert "PEG Ratio" in text
    assert "2.15" in text


@pytest.mark.asyncio
async def test_snapshot_block_omits_forward_pe_and_peg_when_none() -> None:
    """Missing fields must not render as "—" — they are simply absent."""
    s3 = AsyncMock()
    s3.get_fundamentals_history_with_snapshot.return_value = {
        "periods": _periods(),
        "current_snapshot": {
            "pe_ratio": 30.4,
            "forward_pe": None,
            "peg_ratio": None,
            "as_of": "2026-06-01",
            "source": "highlights",
        },
    }
    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)
    assert result is not None
    assert "Forward P/E" not in result.text
    assert "PEG Ratio" not in result.text
