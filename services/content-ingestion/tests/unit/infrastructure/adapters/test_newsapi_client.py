"""HTTP client tests for NewsAPIClient using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient

pytestmark = pytest.mark.unit


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _articles_response(n: int = 1, total: int | None = None) -> dict:
    articles = [{"url": f"https://example.com/{i}", "title": f"Art {i}"} for i in range(n)]
    return {"status": "ok", "totalResults": total if total is not None else n, "articles": articles}


class TestNewsAPIClient:
    async def test_fetch_articles_sends_api_key_header(self) -> None:
        captured_headers = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_headers
            captured_headers = dict(request.headers)
            return httpx.Response(200, json=_articles_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = NewsAPIClient(http_client=http, api_key="test-api-key")
            result = await client.fetch_articles(query="AI")

        assert captured_headers is not None
        assert captured_headers.get("x-api-key") == "test-api-key"
        assert result["articles"][0]["url"] == "https://example.com/0"

    async def test_fetch_articles_429(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = NewsAPIClient(http_client=http, api_key="key")
            with pytest.raises(AdapterError, match="429"):
                await client.fetch_articles(query="test")

    async def test_fetch_all_pages_pagination_until_total(self) -> None:
        """Stops when accumulated articles >= totalResults."""
        call_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_articles_response(n=50, total=80))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = NewsAPIClient(http_client=http, api_key="key")
            result = await client.fetch_all_pages(query="test")

        # 50 >= 80? No → page 2. 100 >= 80? Yes → stop.
        assert call_count == 2
        assert len(result) == 100

    async def test_fetch_all_pages_quota_halt(self) -> None:
        """QuotaExhaustedError mid-pagination → returns what we have so far."""
        valkey = _FakeValkey(fail_after=1)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_articles_response(n=50, total=200))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = NewsAPIClient(http_client=http, api_key="key", valkey=valkey, daily_limit=1)
            result = await client.fetch_all_pages(query="test")

        # First page OK (count=1, within limit), second page quota exceeded (count=2 > 1)
        assert len(result) == 50

    async def test_from_date_param_sent(self) -> None:
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_articles_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = NewsAPIClient(http_client=http, api_key="key")
            await client.fetch_articles(query="AI", from_date="2026-03-01")

        assert captured_url is not None
        assert "from=2026-03-01" in captured_url


class _FakeValkey:
    """Minimal fake Valkey for quota testing."""

    def __init__(self, fail_after: int = 100) -> None:
        self._counters: dict[str, int] = {}
        self._fail_after = fail_after

    async def incr(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    async def expire(self, _key: str, _ttl: int) -> None:
        pass
