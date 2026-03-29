"""HTTP client tests for EODHDClient using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
from content_ingestion.config import EODHDProviderSettings
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient

pytestmark = pytest.mark.unit


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _articles(n: int = 1) -> list[dict]:
    return [{"link": f"https://example.com/{i}", "date": "2026-03-01"} for i in range(n)]


def _make_client(http: httpx.AsyncClient, api_key: str = "key", **cfg_overrides) -> EODHDClient:
    """Construct an EODHDClient with default provider settings, allowing overrides."""
    return EODHDClient(
        http_client=http,
        api_key=api_key,
        provider_cfg=EODHDProviderSettings(**cfg_overrides),
    )


class TestEODHDClient:
    async def test_fetch_news_params(self) -> None:
        """Verifies query parameter assembly."""
        captured_request = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json=_articles(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, api_key="test-key")
            result = await client.fetch_news(ticker="AAPL.US", from_date="2026-01-01", to_date="2026-03-01")

        assert len(result) == 1
        assert captured_request is not None
        url = str(captured_request.url)
        assert "api_token=test-key" in url
        assert "s=AAPL.US" in url
        assert "from=2026-01-01" in url
        assert "to=2026-03-01" in url

    async def test_fetch_news_429_raises_adapter_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(AdapterError, match="429"):
                await client.fetch_news()

    async def test_fetch_news_500_raises_adapter_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(AdapterError, match="500"):
                await client.fetch_news()

    async def test_fetch_news_non_list_returns_empty(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "invalid"})

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.fetch_news()
            assert result == []

    async def test_fetch_all_pages_pagination_stop(self) -> None:
        """Stops when page has fewer items than page_size (100)."""
        call_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            # First page: 100 items (full), second page: 3 items (stop)
            n = 100 if call_count == 1 else 3
            return httpx.Response(200, json=_articles(n))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.fetch_all_pages(ticker="AAPL")

        assert len(result) == 103
        assert call_count == 2

    async def test_eodhd_client_custom_base_url(self) -> None:
        """Constructing with a custom base_url sends requests to the overridden URL."""
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_articles(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, base_url="http://mock/news")
            await client.fetch_news()

        assert captured_url is not None
        assert captured_url.startswith("http://mock/news")

    async def test_eodhd_client_custom_page_size(self) -> None:
        """page_size=10 stops pagination after a single short page (< 10 items)."""
        call_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_articles(3))  # 3 < 10 → stop

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, page_size=10)
            result = await client.fetch_all_pages()

        assert len(result) == 3
        assert call_count == 1
