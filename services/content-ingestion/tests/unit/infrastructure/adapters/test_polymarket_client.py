"""Unit tests for PolymarketClient offset pagination (fix/polymarket-pagination).

The Gamma ``/markets`` endpoint paginates via ``offset``/``limit`` and returns a
bare JSON array — there is no response-body ``next_cursor``. These tests pin the
offset-pagination contract: the request carries ``offset``, the synthetic cursor
advances by ``limit``, and a short/empty page terminates the loop (cursor None).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.config import PolymarketProviderSettings
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket.client import GammaMarketsPage, PolymarketClient

pytestmark = pytest.mark.unit


def _make_settings(order: str = "", ascending: bool = False) -> PolymarketProviderSettings:
    # Real settings object so config defaults/validation are exercised. ``order``
    # defaults to "" here to keep param assertions focused on offset/limit; the
    # order-param behaviour has its own dedicated test.
    return PolymarketProviderSettings(order=order, ascending=ascending)


def _make_response(body: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


class TestPolymarketClientPagination:
    async def test_first_page_request_carries_offset_zero(self) -> None:
        """A cursor-less first call must send ``offset=0`` (not omit it)."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([]))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        await client.fetch_markets_page(limit=500)

        _, kwargs = http.get.call_args
        assert kwargs["params"]["offset"] == 0
        assert kwargs["params"]["limit"] == 500
        assert kwargs["params"]["closed"] == "false"
        assert kwargs["params"]["active"] == "true"

    async def test_synthetic_cursor_advances_by_limit(self) -> None:
        """A full page (len == limit) yields next_cursor == str(offset + limit)."""
        http = AsyncMock()
        markets = [{"conditionId": f"c{i}"} for i in range(3)]
        http.get = AsyncMock(return_value=_make_response(markets))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=3)

        assert isinstance(page, GammaMarketsPage)
        assert page.markets == markets
        assert page.next_cursor == "3"

    async def test_request_uses_offset_decoded_from_cursor(self) -> None:
        """The opaque cursor string is decoded back into the ``offset`` param."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([{"conditionId": "c"}] * 2))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=2, next_cursor="500")

        _, kwargs = http.get.call_args
        assert kwargs["params"]["offset"] == 500
        assert page.next_cursor == "502"

    async def test_stop_on_short_page(self) -> None:
        """A page shorter than ``limit`` is the last page → next_cursor None."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([{"conditionId": "only"}]))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=500, next_cursor="1000")

        assert page.next_cursor is None
        assert len(page.markets) == 1

    async def test_stop_on_empty_page(self) -> None:
        """An empty page terminates the loop (next_cursor None)."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([]))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=500, next_cursor="2000")

        assert page.markets == []
        assert page.next_cursor is None

    async def test_order_param_included_when_configured(self) -> None:
        """A non-empty ``order`` adds order + ascending params for stable paging."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([]))
        client = PolymarketClient(http_client=http, settings=_make_settings(order="volume24hr", ascending=False))

        await client.fetch_markets_page(limit=500)

        _, kwargs = http.get.call_args
        assert kwargs["params"]["order"] == "volume24hr"
        assert kwargs["params"]["ascending"] == "false"

    async def test_order_param_omitted_when_empty(self) -> None:
        """Empty ``order`` (safe fallback) omits both order and ascending params."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([]))
        client = PolymarketClient(http_client=http, settings=_make_settings(order=""))

        await client.fetch_markets_page(limit=500)

        _, kwargs = http.get.call_args
        assert "order" not in kwargs["params"]
        assert "ascending" not in kwargs["params"]

    async def test_bare_array_response_parsed(self) -> None:
        """The live bare-array response shape is parsed into markets."""
        markets = [{"conditionId": "abc", "question": "Will X happen?"}]
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response(markets))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=500)

        assert page.markets == markets
        assert page.next_cursor is None  # 1 < 500 → last page

    async def test_dict_wrapped_response_parsed(self) -> None:
        """Defensive: an object wrapping the array under ``markets`` is accepted."""
        markets = [{"conditionId": "x"}]
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response({"markets": markets}))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=500)

        assert page.markets == markets

    async def test_non_list_body_yields_empty_page(self) -> None:
        """A malformed (non-list/non-dict) body must not crash the loop."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response("boom"))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        page = await client.fetch_markets_page(limit=500)

        assert page.markets == []
        assert page.next_cursor is None

    async def test_http_error_raises_adapter_error(self) -> None:
        """Non-200 HTTP status → AdapterError raised (retryable upstream)."""
        http = AsyncMock()
        http.get = AsyncMock(return_value=_make_response([], status_code=429))
        client = PolymarketClient(http_client=http, settings=_make_settings())

        with pytest.raises(AdapterError, match="Gamma API HTTP 429"):
            await client.fetch_markets_page()
