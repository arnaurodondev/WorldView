"""Unit tests for PolymarketClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket.client import GammaMarketsPage, PolymarketClient

pytestmark = pytest.mark.unit


def _make_settings(base_url: str = "https://gamma-api.polymarket.com/markets") -> object:
    cfg = MagicMock()
    cfg.base_url = base_url
    return cfg


def _make_response(body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


class TestPolymarketClient:
    async def test_client_parses_markets_page(self) -> None:
        """Valid JSON response → GammaMarketsPage fields populated."""
        markets = [{"conditionId": "abc", "question": "Will X happen?"}]
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response({"markets": markets, "next_cursor": "cursor123"}))
        client = PolymarketClient(http_client=http, settings=_make_settings())  # type: ignore[arg-type]

        page = await client.fetch_markets_page(limit=10)

        assert page.markets == markets
        assert page.next_cursor == "cursor123"

    async def test_client_next_cursor_absent(self) -> None:
        """Response without next_cursor → GammaMarketsPage.next_cursor is None."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response({"markets": []}))
        client = PolymarketClient(http_client=http, settings=_make_settings())  # type: ignore[arg-type]

        page = await client.fetch_markets_page()

        assert isinstance(page, GammaMarketsPage)
        assert page.next_cursor is None

    async def test_client_http_error_raises_adapter_error(self) -> None:
        """Non-200 HTTP status → AdapterError raised."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response({}, status_code=429))
        client = PolymarketClient(http_client=http, settings=_make_settings())  # type: ignore[arg-type]

        with pytest.raises(AdapterError, match="Gamma API HTTP 429"):
            await client.fetch_markets_page()
