"""HTTP client tests for SECEdgarClient using httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest
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


class TestSECEdgarClient:
    async def test_user_agent_required(self) -> None:
        async with httpx.AsyncClient() as http:
            with pytest.raises(ConfigurationError, match="User-Agent"):
                SECEdgarClient(http_client=http, user_agent="")

    async def test_search_filings_sends_user_agent(self) -> None:
        captured_headers = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_headers
            captured_headers = dict(request.headers)
            return httpx.Response(200, json=_filing_response(1))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = SECEdgarClient(http_client=http, user_agent="TestBot/1.0 test@example.com")
            result = await client.search_filings()

        assert len(result) == 1
        assert captured_headers is not None
        assert captured_headers.get("user-agent") == "TestBot/1.0 test@example.com"

    async def test_search_filings_429(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = SECEdgarClient(http_client=http, user_agent="Bot/1.0")
            with pytest.raises(AdapterError, match="429"):
                await client.search_filings()

    async def test_search_filings_extracts_hits(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_filing_response(3))

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = SECEdgarClient(http_client=http, user_agent="Bot/1.0")
            result = await client.search_filings()
            assert len(result) == 3

    async def test_fetch_filing_document(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>Filing</html>")

        async with httpx.AsyncClient(transport=_mock_transport(handler)) as http:
            client = SECEdgarClient(http_client=http, user_agent="Bot/1.0")
            raw = await client.fetch_filing_document(cik="12345", accession_no="0001-23-456789", filename="doc.htm")
            assert raw == b"<html>Filing</html>"
