"""HTTP client tests for SECEdgarClient using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
from content_ingestion.config import SECEdgarProviderSettings
from content_ingestion.domain.exceptions import AdapterError, ConfigurationError
from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

pytestmark = pytest.mark.unit


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _filing_response(n: int = 1) -> dict:
    hits = [
        {"_source": {"accession_no": f"0001-{i:04d}", "file_name": f"doc{i}.htm", "cik": "12345"}} for i in range(n)
    ]
    return {"hits": {"hits": hits}}


def _make_client(
    http: httpx.AsyncClient,
    user_agent: str = "Bot/1.0 test@example.com",
    **cfg_overrides,
) -> SECEdgarClient:
    """Construct a SECEdgarClient with default provider settings, allowing overrides."""
    return SECEdgarClient(
        http_client=http,
        user_agent=user_agent,
        provider_cfg=SECEdgarProviderSettings(**cfg_overrides),
    )


class TestSECEdgarClient:
    async def test_user_agent_required(self) -> None:
        async with httpx.AsyncClient() as http:
            with pytest.raises(ConfigurationError, match="User-Agent"):
                SECEdgarClient(
                    http_client=http,
                    user_agent="",
                    provider_cfg=SECEdgarProviderSettings(),
                )

    async def test_search_filings_sends_user_agent(self) -> None:
        captured_headers = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_headers
            captured_headers = dict(request.headers)
            return httpx.Response(200, json=_filing_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, user_agent="TestBot/1.0 test@example.com")
            result = await client.search_filings()

        assert len(result) == 1
        assert captured_headers is not None
        assert captured_headers.get("user-agent") == "TestBot/1.0 test@example.com"

    async def test_search_filings_429(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            with pytest.raises(AdapterError, match="429"):
                await client.search_filings()

    async def test_search_filings_extracts_hits(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_filing_response(3))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            result = await client.search_filings()
            assert len(result) == 3

    async def test_fetch_filing_document(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>Filing</html>")

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http)
            raw = await client.fetch_filing_document(cik="12345", accession_no="0001-23-456789", filename="doc.htm")
            assert raw == b"<html>Filing</html>"

    async def test_sec_edgar_client_custom_urls(self) -> None:
        """EFTS and filing base URLs are configurable via provider settings."""
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_filing_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, efts_url="http://mock-efts/search")
            await client.search_filings()

        assert captured_url is not None
        assert captured_url.startswith("http://mock-efts/search")

    async def test_sec_edgar_client_filing_base_url_override(self) -> None:
        """fetch_filing_document uses the overridden filing_base_url."""
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, content=b"data")

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, filing_base_url="http://mock-sec/data")
            await client.fetch_filing_document(cik="123", accession_no="0001-23-456", filename="doc.htm")

        assert captured_url is not None
        assert captured_url.startswith("http://mock-sec/data/123/")

    async def test_sec_edgar_custom_max_concurrent(self) -> None:
        """Semaphore size matches max_concurrent from provider settings."""
        async with httpx.AsyncClient() as http:
            client = _make_client(http, max_concurrent=2)
            # Internal semaphore should have _value == 2
            assert client._semaphore._value == 2

    async def test_search_filings_default_forms_from_config(self) -> None:
        """search_filings() uses default_forms from provider_cfg when forms arg is empty."""
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_filing_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, default_forms="8-K")
            await client.search_filings()

        assert captured_url is not None
        assert "forms=8-K" in captured_url

    async def test_search_filings_explicit_forms_override_default(self) -> None:
        """Explicit forms= arg overrides default_forms from config."""
        captured_url = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(200, json=_filing_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = _make_client(http, default_forms="10-K")
            await client.search_filings(forms="DEF14A")

        assert captured_url is not None
        assert "forms=DEF14A" in captured_url
