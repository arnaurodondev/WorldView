"""HTTP client tests for FinnhubClient using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
from content_ingestion.config import FinnhubProviderSettings
from content_ingestion.infrastructure.adapters.finnhub.client import FinnhubClient, RateLimitError

pytestmark = pytest.mark.unit


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _make_client(http: httpx.AsyncClient, api_key: str = "key", **cfg_overrides) -> FinnhubClient:
    """Construct a FinnhubClient with default provider settings, allowing overrides."""
    return FinnhubClient(
        http_client=http,
        api_key=api_key,
        provider_cfg=FinnhubProviderSettings(**cfg_overrides),
    )


class TestFinnhubClient:
    async def test_fetch_company_news_params(self) -> None:
        captured_request = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json=[{"id": 1, "headline": "Test"}])

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, api_key="test-key")
            result = await client.fetch_company_news(symbol="AAPL", from_date="2026-01-01", to_date="2026-03-01")

        assert len(result) == 1
        url = str(captured_request.url)
        assert "symbol=AAPL" in url
        assert "from=2026-01-01" in url
        assert "token=test-key" in url

    async def test_fetch_company_news_429_raises_rate_limit(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(RateLimitError) as exc_info:
                await client.fetch_company_news(symbol="AAPL", from_date="2026-01-01", to_date="2026-03-01")
            assert exc_info.value.sleep_secs >= 1.0

    async def test_fetch_company_news_non_list_returns_empty(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "invalid"})

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.fetch_company_news(symbol="AAPL", from_date="2026-01-01", to_date="2026-03-01")
            assert result == []

    async def test_fetch_transcript_list(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"transcripts": [{"id": "t1"}, {"id": "t2"}]})

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.fetch_transcript_list(symbol="AAPL")
            assert len(result) == 2

    async def test_fetch_transcript(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "t1", "transcript": [{"text": "Hello"}]})

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.fetch_transcript(transcript_id="t1")
            assert result["id"] == "t1"

    async def test_finnhub_client_custom_base_url(self) -> None:
        """Requests go to the overridden base URL."""
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=[{"id": 1}])

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, base_url="http://mock-finnhub/api/v1")
            await client.fetch_company_news(symbol="TSLA", from_date="2026-01-01", to_date="2026-03-01")

        assert captured_url is not None
        assert captured_url.startswith("http://mock-finnhub/api/v1/")
