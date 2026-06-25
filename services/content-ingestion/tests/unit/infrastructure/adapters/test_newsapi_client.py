"""HTTP client tests for NewsAPIClient using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
from content_ingestion.config import NewsAPIProviderSettings
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.newsapi.client import (
    NewsAPIClient,
    NewsAPIServerError,
    NewsAPIUpgradeRequiredError,
)

pytestmark = pytest.mark.unit


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _articles_response(n: int = 1, total: int | None = None) -> dict:
    articles = [{"url": f"https://example.com/{i}", "title": f"Art {i}"} for i in range(n)]
    return {"status": "ok", "totalResults": total if total is not None else n, "articles": articles}


def _make_client(
    http: httpx.AsyncClient,
    api_key: str = "key",
    valkey=None,
    daily_limit: int = 100,
    **cfg_overrides,
) -> NewsAPIClient:
    """Construct a NewsAPIClient with default provider settings, allowing overrides."""
    return NewsAPIClient(
        http_client=http,
        api_key=api_key,
        provider_cfg=NewsAPIProviderSettings(**cfg_overrides),
        valkey=valkey,
        daily_limit=daily_limit,
    )


class TestNewsAPIClient:
    async def test_fetch_articles_sends_api_key_header(self) -> None:
        captured_headers = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_headers
            captured_headers = dict(request.headers)
            return httpx.Response(200, json=_articles_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, api_key="test-api-key")
            result = await client.fetch_articles(query="AI")

        assert captured_headers is not None
        assert captured_headers.get("x-api-key") == "test-api-key"
        assert result["articles"][0]["url"] == "https://example.com/0"

    async def test_fetch_articles_429(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
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
            client = _make_client(http)
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
            client = _make_client(http, valkey=valkey, daily_limit=1)
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
            client = _make_client(http)
            await client.fetch_articles(query="AI", from_date="2026-03-01")

        assert captured_url is not None
        assert "from=2026-03-01" in captured_url

    async def test_newsapi_client_custom_quota_ttl(self) -> None:
        """TTL value passed to valkey.expire matches quota_ttl_seconds."""
        recorded_ttl = None

        class _RecordingValkey:
            async def incr(self, key: str) -> int:
                return 1

            async def expire(self, _key: str, ttl: int) -> None:
                nonlocal recorded_ttl
                recorded_ttl = ttl

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_articles_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, valkey=_RecordingValkey(), quota_ttl_seconds=3600)
            await client.fetch_articles(query="test")

        assert recorded_ttl == 3600


class TestNewsAPIServerErrorDetection:
    """PLAN-0109 / T-C-1-01 / BP-658 — NewsAPI returns HTTP 200 with
    ``{"status":"error",...}`` on quota and parameter failures; the client
    must raise ``NewsAPIServerError`` rather than letting the caller mistake
    it for a legitimate empty 200 response (and silently advance the
    watermark).
    """

    async def test_client_raises_on_status_error_rate_limited(self) -> None:
        """status=error + code=rateLimited → NewsAPIServerError with code/message."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "error",
                    "code": "rateLimited",
                    "message": "You have made too many requests recently.",
                },
            )

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(NewsAPIServerError) as exc_info:
                await client.fetch_articles(query="AI")

        assert exc_info.value.code == "rateLimited"
        assert exc_info.value.message is not None
        assert "too many requests" in exc_info.value.message

    async def test_client_raises_on_status_error_parameter_invalid(self) -> None:
        """status=error + code=parameterInvalid → NewsAPIServerError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "error",
                    "code": "parameterInvalid",
                    "message": "The 'from' parameter is invalid.",
                },
            )

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(NewsAPIServerError) as exc_info:
                await client.fetch_articles(query="AI", from_date="1900-01-01")

        assert exc_info.value.code == "parameterInvalid"

    async def test_client_succeeds_on_status_ok_empty_articles(self) -> None:
        """A legitimate "no news today" 200 response (status=ok, articles=[])
        must NOT raise — only ``status=error`` triggers the new typed error."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"status": "ok", "totalResults": 0, "articles": []},
            )

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            # No exception — returns the parsed dict with empty articles.
            result = await client.fetch_articles(query="AI")
            assert result["status"] == "ok"
            assert result["articles"] == []


class TestNewsAPIFreeTierPageCap:
    """NewsAPI free tier caps results at 100 (page 1 only); page >= 2 returns
    HTTP 426 "Upgrade Required". The pagination loop must treat that as
    end-of-pages and keep the page-1 results instead of discarding the whole
    batch by raising a retryable error.
    """

    async def test_fetch_all_pages_426_on_page_2_returns_page_1_articles(self) -> None:
        """Page 1 → 200 with 100 articles (total 250); page 2 → 426.
        fetch_all_pages must return the 100 page-1 articles, no exception."""
        call_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, json=_articles_response(n=100, total=250))
            return httpx.Response(426)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.fetch_all_pages(query="test")

        assert call_count == 2
        assert len(result) == 100

    async def test_fetch_all_pages_426_on_page_1_raises(self) -> None:
        """A 426 on page 1 means the whole request was rejected (e.g. stale
        from_date) — it must still propagate as an AdapterError subtype."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(426)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(NewsAPIUpgradeRequiredError) as exc_info:
                await client.fetch_all_pages(query="test")

        assert exc_info.value.page == 1

    async def test_fetch_articles_426_raises_typed_error_with_page(self) -> None:
        """fetch_articles always raises the typed 426 error (the page-cap
        tolerance lives only in fetch_all_pages)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(426)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(NewsAPIUpgradeRequiredError) as exc_info:
                await client.fetch_articles(query="test", page=2)

        assert exc_info.value.page == 2
        # Remains an AdapterError so existing generic handlers still catch it.
        assert isinstance(exc_info.value, AdapterError)


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
