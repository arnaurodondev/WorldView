"""Unit tests for the NewsAPI adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import QuotaExhaustedError
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.newsapi.adapter import NewsAPIAdapter, _parse_published_at
from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient

pytestmark = pytest.mark.unit


def _make_source(**kwargs: Any) -> Source:
    defaults: dict[str, Any] = {
        "name": "test-newsapi",
        "source_type": SourceType.NEWSAPI,
        "enabled": True,
        "config": {"query": "tech stocks", "from_date": "2026-01-01"},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _article(url: str, published_at: str = "2026-03-15T10:00:00Z") -> dict[str, Any]:
    return {
        "url": url,
        "title": f"Article {url}",
        "publishedAt": published_at,
        "source": {"name": "Test Source"},
    }


class TestParsePublishedAt:
    def test_valid_iso_with_z(self) -> None:
        result = _parse_published_at({"publishedAt": "2026-03-15T10:00:00Z"})
        assert result is not None
        assert result.year == 2026
        assert result.tzinfo is not None

    def test_valid_iso_with_offset(self) -> None:
        result = _parse_published_at({"publishedAt": "2026-03-15T10:00:00+02:00"})
        assert result is not None

    def test_missing_published_at(self) -> None:
        assert _parse_published_at({}) is None

    def test_invalid_date(self) -> None:
        assert _parse_published_at({"publishedAt": "invalid"}) is None


class TestNewsAPIAdapterFetch:
    async def test_fetches_and_returns_results(self) -> None:
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://news.example.com/1"),
            _article("https://news.example.com/2"),
        ]
        adapter = NewsAPIAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 2

    async def test_dedup_skips_existing(self) -> None:
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://news.example.com/dup"),
        ]
        exists_fn = AsyncMock(return_value=True)
        adapter = NewsAPIAdapter(
            client=mock_client,
            exists_fn=exists_fn,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0

    async def test_published_at_extracted(self) -> None:
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://news.example.com/dated", published_at="2026-02-20T14:30:00Z"),
        ]
        adapter = NewsAPIAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert results[0].published_at is not None
        assert results[0].published_at.month == 2

    async def test_quota_exhausted_propagates_immediately(self) -> None:
        """QuotaExhaustedError should propagate without retry."""
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.side_effect = QuotaExhaustedError("quota hit")

        adapter = NewsAPIAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=3, backoff_factors=(0.0, 0.0, 0.0)),
        )
        with pytest.raises(QuotaExhaustedError):
            await adapter.fetch(_make_source())

        # Should have been called only once (no retry)
        assert mock_client.fetch_all_pages.call_count == 1

    async def test_is_backfill_propagated(self) -> None:
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://news.example.com/bf"),
        ]
        adapter = NewsAPIAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(), is_backfill=True)
        assert len(results) == 1
        assert results[0].is_backfill is True

    async def test_skips_articles_without_url(self) -> None:
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = [{"title": "No URL article"}]

        adapter = NewsAPIAdapter(
            client=mock_client,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0


class TestNewsAPIClientQuota:
    async def test_check_quota_increments_counter(self) -> None:
        """Valkey counter should be atomically incremented on each request."""
        mock_valkey = AsyncMock()
        mock_valkey.incr.return_value = 6  # After increment: was 5, now 6
        mock_http = AsyncMock()

        client = NewsAPIClient(
            http_client=mock_http,
            api_key="test-key",
            valkey=mock_valkey,
            daily_limit=100,
        )
        await client._check_quota()
        mock_valkey.incr.assert_called_once()

    async def test_check_quota_sets_ttl_on_first_increment(self) -> None:
        """TTL should be set when incr returns 1 (first call of the day)."""
        mock_valkey = AsyncMock()
        mock_valkey.incr.return_value = 1
        mock_http = AsyncMock()

        client = NewsAPIClient(
            http_client=mock_http,
            api_key="test-key",
            valkey=mock_valkey,
            daily_limit=100,
        )
        await client._check_quota()
        mock_valkey.expire.assert_called_once()

    async def test_check_quota_raises_on_limit(self) -> None:
        """Should raise QuotaExhaustedError when limit exceeded."""
        mock_valkey = AsyncMock()
        mock_valkey.incr.return_value = 101  # Over the limit of 100
        mock_http = AsyncMock()

        client = NewsAPIClient(
            http_client=mock_http,
            api_key="test-key",
            valkey=mock_valkey,
            daily_limit=100,
        )
        with pytest.raises(QuotaExhaustedError):
            await client._check_quota()
