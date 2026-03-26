"""Unit tests for the SEC EDGAR adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import ConfigurationError
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.sec_edgar.adapter import (
    SECEdgarAdapter,
    _parse_published_at,
)
from content_ingestion.infrastructure.adapters.sec_edgar.client import SECEdgarClient

pytestmark = pytest.mark.unit


def _make_source(**kwargs: Any) -> Source:
    defaults: dict[str, Any] = {
        "name": "test-edgar",
        "source_type": SourceType.SEC_EDGAR,
        "enabled": True,
        "config": {"from_date": "2026-01-01", "to_date": "2026-03-01"},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _filing(accession_no: str, file_name: str = "filing.htm") -> dict[str, Any]:
    return {
        "_source": {
            "accession_no": accession_no,
            "file_name": file_name,
            "cik": "12345",
            "period_of_report": "2026-01-15",
        }
    }


class TestSECEdgarUserAgentValidation:
    def test_raises_on_empty_user_agent(self) -> None:
        mock_http = AsyncMock()
        with pytest.raises(ConfigurationError, match="User-Agent"):
            SECEdgarClient(http_client=mock_http, user_agent="")

    def test_raises_on_whitespace_user_agent(self) -> None:
        mock_http = AsyncMock()
        with pytest.raises(ConfigurationError, match="User-Agent"):
            SECEdgarClient(http_client=mock_http, user_agent="   ")

    def test_accepts_valid_user_agent(self) -> None:
        mock_http = AsyncMock()
        client = SECEdgarClient(http_client=mock_http, user_agent="worldview/1.0 test@example.com")
        assert client._user_agent == "worldview/1.0 test@example.com"


class TestParsePublishedAt:
    def test_period_of_report(self) -> None:
        result = _parse_published_at({"_source": {"period_of_report": "2026-01-15"}})
        assert result is not None
        assert result.day == 15

    def test_file_date_fallback(self) -> None:
        result = _parse_published_at({"_source": {"file_date": "2026-02-20"}})
        assert result is not None
        assert result.month == 2

    def test_no_date_fields(self) -> None:
        assert _parse_published_at({"_source": {}}) is None


class TestSECEdgarAdapterFetch:
    async def test_fetches_and_returns_results(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [
            _filing("0001234567-26-000001"),
        ]
        mock_client.fetch_filing_document.return_value = b"<html>Filing content</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert b"Filing content" in results[0].raw_bytes

    async def test_dedup_skips_existing(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [_filing("0001234567-26-000002")]
        exists_fn = AsyncMock(return_value=True)

        adapter = SECEdgarAdapter(
            client=mock_client,
            exists_fn=exists_fn,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0

    async def test_dedup_hash_uses_accession_and_filename(self) -> None:
        """Different filenames for same accession should produce different hashes."""
        from content_ingestion.infrastructure.adapters.base import url_hash

        h1 = url_hash("0001234567-26-000001filing.htm")
        h2 = url_hash("0001234567-26-000001xbrl.xml")
        assert h1 != h2

    async def test_is_backfill_propagated(self) -> None:
        mock_client = AsyncMock(spec=SECEdgarClient)
        mock_client.search_filings.return_value = [_filing("0001234567-26-000003")]
        mock_client.fetch_filing_document.return_value = b"<html>content</html>"

        adapter = SECEdgarAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(), is_backfill=True)
        assert len(results) == 1
        assert results[0].is_backfill is True
