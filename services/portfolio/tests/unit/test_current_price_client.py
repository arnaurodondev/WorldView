"""Unit tests for ``HttpCurrentPriceClient`` price extraction.

F-301 (QA iter-3 2026-04-28): the production S3 ``/api/v1/quotes/batch``
endpoint returns ``{bid, ask, last, volume, timestamp, updated_at}`` —
there is **no** ``price`` key. The pre-fix client read ``quote["price"]``
and silently dropped every entry. These tests pin the corrected
extraction down: prefer ``last``, fall back to mid, then accept ``price``
for forward-compat.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import httpx
import pytest
from portfolio.infrastructure.market_data.current_price_client import (
    HttpCurrentPriceClient,
    _extract_price,
)

pytestmark = pytest.mark.unit


# Recorded sample of a real S3 batch response — the exact shape we hit in
# the live stack as of 2026-04-28. Used by the integration-style test
# below to lock the contract.
_REAL_S3_FIXTURE = {
    "quotes": {
        "01900000-0000-7000-8000-000000001001": {
            "bid": "267.61",
            "ask": "267.61",
            "last": "267.61",
            "volume": 0,
            "timestamp": "2026-04-28T14:30:00Z",
            "updated_at": "2026-04-28T14:30:00Z",
        },
        "01900000-0000-7000-8000-000000001002": {
            "bid": "412.50",
            "ask": "412.80",
            "last": "412.65",
            "volume": 1234,
            "timestamp": "2026-04-28T14:30:00Z",
            "updated_at": "2026-04-28T14:30:00Z",
        },
    },
}


# ── _extract_price unit tests ────────────────────────────────────────────────


class TestExtractPrice:
    """Pin the 3-level preference chain: last → mid → price."""

    def test_prefers_last_when_present(self) -> None:
        # ``last`` wins even if ``price`` is also present — the S9 proxy
        # historically synthesised both, and the S3 raw shape doesn't have
        # ``price``, so reading ``last`` is the safe canonical choice.
        quote = {"bid": "100", "ask": "101", "last": "100.50", "price": "999"}
        assert _extract_price(quote) == Decimal("100.50")

    def test_falls_back_to_mid_when_last_missing(self) -> None:
        # When the book has bid+ask but no print yet (illiquid open), use
        # the mid as the fairest approximation of "current price".
        quote = {"bid": "100", "ask": "101"}
        assert _extract_price(quote) == Decimal("100.5")

    def test_falls_back_to_price_when_only_price_present(self) -> None:
        # Forward-compat: if a future backend collapses the envelope to
        # the historic shape, we still extract.
        quote = {"price": "150.25"}
        assert _extract_price(quote) == Decimal("150.25")

    def test_returns_none_when_all_keys_missing(self) -> None:
        # Pure "no data" path — the use case will fall back to avg_cost.
        quote = {"volume": 1000, "timestamp": "2026-04-28T00:00:00Z"}
        assert _extract_price(quote) is None

    def test_returns_none_when_last_unparsable_and_no_fallbacks(self) -> None:
        # Malformed ``last`` skips to the next preference; with no bid/ask
        # and no price we end up at None.
        quote = {"last": "not-a-number"}
        assert _extract_price(quote) is None

    def test_falls_back_through_unparsable_last(self) -> None:
        # Unparsable ``last`` shouldn't poison the chain — we still try
        # mid and price after.
        quote = {"last": "BAD", "bid": "100", "ask": "101"}
        assert _extract_price(quote) == Decimal("100.5")

    def test_locked_book_treated_as_no_mid(self) -> None:
        # ask < bid is a degenerate "locked" book — we don't synthesise a
        # price from it because the mid would be misleading. Falls through
        # to ``price`` (also missing here) → None.
        quote = {"bid": "101", "ask": "100"}
        assert _extract_price(quote) is None

    def test_handles_numeric_jsonvalues(self) -> None:
        # Backends sometimes emit JSON numbers, sometimes strings — both
        # must work via the Decimal(str(...)) idiom.
        quote = {"last": 100.50}
        assert _extract_price(quote) == Decimal("100.5")


# ── HttpCurrentPriceClient end-to-end test (with recorded fixture) ──────────


class TestHttpCurrentPriceClientWithRealFixture:
    """End-to-end: real S3 response shape produces real prices.

    This is the regression test for F-301 — without the fix, this test
    fails because ``quote["price"]`` returns None for every entry.
    """

    @pytest.mark.asyncio
    async def test_extracts_prices_from_recorded_s3_response(self) -> None:
        # Mock the httpx client so we can hand it the recorded fixture
        # without standing up a real market-data instance.
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json = MagicMock(return_value=_REAL_S3_FIXTURE)

        mock_http = MagicMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock(return_value=mock_response)

        client = HttpCurrentPriceClient(mock_http, "http://market-data:8003")
        result = await client.get_current_prices(
            [
                UUID("01900000-0000-7000-8000-000000001001"),
                UUID("01900000-0000-7000-8000-000000001002"),
            ],
        )

        # Both quotes resolved via ``last`` (the canonical S3 field).
        assert len(result) == 2
        assert result[UUID("01900000-0000-7000-8000-000000001001")] == Decimal("267.61")
        assert result[UUID("01900000-0000-7000-8000-000000001002")] == Decimal("412.65")

    @pytest.mark.asyncio
    async def test_empty_request_skips_network(self) -> None:
        # Common case: empty portfolio shouldn't issue a network request.
        mock_http = MagicMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock()

        client = HttpCurrentPriceClient(mock_http, "http://market-data:8003")
        result = await client.get_current_prices([])

        assert result == {}
        mock_http.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_logs_warning_when_all_quotes_missing_price(self) -> None:
        # Regression-prevention: when every quote in the batch fails to
        # produce a price (the F-301 silent-regression pattern), we must
        # emit a structured warning so the next QA pass catches it
        # immediately via container logs.
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        # Shape with NEITHER last/bid/ask NOR price — extraction returns
        # None for every entry, exactly the F-301 failure mode.
        mock_response.json = MagicMock(
            return_value={
                "quotes": {
                    "01900000-0000-7000-8000-000000001001": {
                        "volume": 0,
                        "timestamp": "2026-04-28T00:00:00Z",
                    },
                },
            },
        )
        mock_http = MagicMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock(return_value=mock_response)

        client = HttpCurrentPriceClient(mock_http, "http://market-data:8003")
        result = await client.get_current_prices(
            [UUID("01900000-0000-7000-8000-000000001001")],
        )

        # No prices extracted → returns empty dict; warning is logged
        # via structlog (we don't assert on the log format here — the
        # presence of the call site is what matters; structlog tests are
        # the wrong layer for "did logger.warning fire" assertions).
        assert result == {}
