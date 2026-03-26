"""Unit tests for the EODHD adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.domain.value_objects import TokenBucket
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.eodhd.adapter import EODHDAdapter, _parse_published_at
from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient

import common.time

pytestmark = pytest.mark.unit


def _make_source(**kwargs: Any) -> Source:
    defaults: dict[str, Any] = {
        "name": "test-eodhd",
        "source_type": SourceType.EODHD,
        "enabled": True,
        "config": {"ticker": "AAPL.US", "from_date": "2026-01-01", "to_date": "2026-03-01"},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _make_bucket() -> TokenBucket:
    return TokenBucket(capacity=100, tokens=100.0, refill_rate=10.0, last_refill=common.time.utc_now())


def _article(link: str, date: str = "2026-03-15T10:00:00") -> dict[str, Any]:
    return {"link": link, "title": f"Article {link}", "date": date}


class TestParsePublishedAt:
    def test_valid_iso_date(self) -> None:
        result = _parse_published_at({"date": "2026-03-15T10:00:00"})
        assert result is not None
        assert result.year == 2026
        assert result.tzinfo is not None

    def test_missing_date(self) -> None:
        assert _parse_published_at({}) is None

    def test_invalid_date(self) -> None:
        assert _parse_published_at({"date": "not-a-date"}) is None


class TestEODHDAdapterFetch:
    async def test_fetches_and_returns_results(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://example.com/a"),
            _article("https://example.com/b"),
        ]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        source = _make_source()
        results = await adapter.fetch(source)
        assert len(results) == 2
        assert results[0].url == "https://example.com/a"
        assert results[1].url == "https://example.com/b"

    async def test_dedup_skips_existing(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://example.com/dup"),
        ]
        exists_fn = AsyncMock(return_value=True)
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            exists_fn=exists_fn,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0
        exists_fn.assert_called_once()

    async def test_published_at_extracted(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://example.com/dated", date="2026-02-20T14:30:00"),
        ]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert results[0].published_at is not None
        assert results[0].published_at.month == 2

    async def test_is_backfill_flag_propagated(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [_article("https://example.com/bf")]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(), is_backfill=True)
        assert len(results) == 1
        assert results[0].is_backfill is True

    async def test_skips_articles_without_link(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [{"title": "No link"}]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0

    async def test_retry_on_transient_failure(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        call_count = 0

        async def flaky_fetch(**_kwargs: Any) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "transient"
                raise AdapterError(msg)
            return [_article("https://example.com/retry-ok")]

        mock_client.fetch_all_pages.side_effect = flaky_fetch
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=2, backoff_factors=(0.0, 0.0)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
