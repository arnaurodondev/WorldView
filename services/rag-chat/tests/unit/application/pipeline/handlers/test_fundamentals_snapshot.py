"""PLAN-0103 W25 / BP-640 regression — snapshot block surfacing in tool output.

The rag-chat singular handler must:
  * read ``current_snapshot`` from the new ``S3Port.get_fundamentals_history_
    with_snapshot`` adapter when available (production path),
  * render a "Current Snapshot (as-of YYYY-MM-DD, source: highlights)" block
    AFTER the period table so the LLM cannot conflate the two,
  * bind ``citation_meta.entity_name=<ticker>`` on the RetrievedItem so the
    BP-605 entity-grounding guard (chat_orchestrator) does not false-
    positive on single-ticker fundamentals queries (BP-644 carry).
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
async def test_singular_handler_emits_snapshot_block_after_period_table() -> None:
    """When the upstream returns a snapshot, the rendered text includes it.

    The block format is intentionally bounded: header line names the ticker,
    as-of date, and source; each populated field renders as one indented
    line. Missing fields are omitted rather than rendered as "—" so the v1.5
    prompt's "refuse rather than fabricate" rule remains the LLM's only path.
    """
    s3 = AsyncMock()
    s3.get_fundamentals_history_with_snapshot.return_value = {
        "periods": [
            {
                "period": "Q2 FY2026",
                "period_end_date": "2026-03-31",
                "period_type": "QUARTERLY",
                "revenue": 95_000_000_000.0,
                "gross_profit": 42_000_000_000.0,
                "net_income": 23_000_000_000.0,
                "eps": 2.01,
                "ebitda": 30_000_000_000.0,
                # PLAN-0103 W25: per-row P/E is now ALWAYS None (snapshot
                # leak is closed at the use case layer).
                "pe_ratio": None,
                "market_cap": None,
            }
        ],
        "current_snapshot": {
            "pe_ratio": 30.4,
            "ev_ebitda": 22.5,
            "market_cap_usd": 3_000_000_000_000,
            "price_to_book": 45.6,
            "dividend_yield": 0.0054,
            "as_of": "2026-06-01",
            "source": "highlights",
        },
    }

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)

    assert result is not None
    text = result.text
    # Period table is still rendered. Cat-A FIX 3 (2026-06-28) renders revenue
    # at 3-decimal precision (was $X.1f).
    assert "Q2 FY2026" in text
    assert "95.000B" in text
    # Snapshot block is appended below.
    assert "Current Snapshot" in text
    assert "as-of 2026-06-01" in text
    assert "source: highlights" in text
    assert "30.40x" in text  # P/E
    assert "22.50x" in text  # EV/EBITDA
    # Market cap is pre-formatted ($3.00T) plus the raw integer for the
    # numeric-grounding validator.
    assert "$3.00T" in text
    # BP-644 / PLAN-0103 W26: citation_meta.entity_name must be set so the
    # BP-605 grounding guard recognises this item as TSLA/AAPL/etc.
    assert result.citation_meta is not None
    assert result.citation_meta.entity_name == "AAPL"


@pytest.mark.asyncio
async def test_singular_handler_omits_block_when_snapshot_is_none() -> None:
    """No snapshot from upstream → no snapshot block in the rendered text."""
    s3 = AsyncMock()
    s3.get_fundamentals_history_with_snapshot.return_value = {
        "periods": [
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
        ],
        "current_snapshot": None,
    }

    handler = _make_handler(s3)
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)

    assert result is not None
    assert "Current Snapshot" not in result.text


@pytest.mark.asyncio
async def test_singular_handler_falls_back_to_legacy_method_when_snapshot_unavailable() -> None:
    """Test doubles that only implement the legacy adapter still work.

    Many existing AsyncMock fixtures predate the snapshot field. The
    handler must not blow up on them — it should fall back to the legacy
    ``get_fundamentals_history`` shape and skip the snapshot block.
    """

    # Build a hand-rolled mock without ``get_fundamentals_history_with_snapshot``
    # so the ``hasattr`` check in the handler falls through cleanly.
    class _LegacyS3:
        async def get_fundamentals_history(self, **_kwargs: Any) -> list[dict]:
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

    handler = _make_handler(_LegacyS3())
    result = await handler._handle_get_fundamentals_history(ticker="AAPL", periods=1)
    assert result is not None
    assert "Q2 FY2026" in result.text
    assert "Current Snapshot" not in result.text
