"""Unit tests for the NewsAPI adapter."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import QuotaExhaustedError
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.newsapi.adapter import NewsAPIAdapter, _parse_published_at
from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient

import common.time

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


class TestNewsAPIAdapterFromDateCap:
    """BP-464: from_date older than 30 days triggers HTTP 426 on NewsAPI free tier.

    The adapter must cap effective_from to at most FREE_TIER_LOOKBACK_DAYS days ago
    regardless of source config or watermark value.
    """

    async def test_stale_config_from_date_is_capped(self) -> None:
        """A static from_date older than 29 days must be capped to the cutoff date."""
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = []

        adapter = NewsAPIAdapter(client=mock_client)
        source = _make_source(config={"query": "stocks", "from_date": "2026-01-01"})
        await adapter.fetch(source)

        call_kwargs = mock_client.fetch_all_pages.call_args.kwargs
        passed_from = call_kwargs["from_date"]
        cutoff = (common.time.utc_now() - timedelta(days=adapter._FREE_TIER_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        assert passed_from >= cutoff, f"Expected from_date >= {cutoff}, got {passed_from}"

    async def test_recent_from_date_is_not_capped(self) -> None:
        """A from_date within the 29-day window is passed through unchanged."""
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = []

        adapter = NewsAPIAdapter(client=mock_client)
        recent_date = (common.time.utc_now() - timedelta(days=5)).strftime("%Y-%m-%d")
        source = _make_source(config={"query": "stocks", "from_date": recent_date})
        await adapter.fetch(source)

        call_kwargs = mock_client.fetch_all_pages.call_args.kwargs
        assert call_kwargs["from_date"] == recent_date

    async def test_empty_from_date_is_not_modified(self) -> None:
        """An empty from_date (no date filter) is passed through unchanged."""
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = []

        adapter = NewsAPIAdapter(client=mock_client)
        source = _make_source(config={"query": "stocks"})
        await adapter.fetch(source)

        call_kwargs = mock_client.fetch_all_pages.call_args.kwargs
        assert call_kwargs["from_date"] == ""

    async def test_watermark_from_date_older_than_29d_is_capped(self) -> None:
        """from_date passed as watermark (not from config) is also capped if too old."""
        mock_client = AsyncMock(spec=NewsAPIClient)
        mock_client.fetch_all_pages.return_value = []

        adapter = NewsAPIAdapter(client=mock_client)
        source = _make_source(config={"query": "stocks"})
        # Simulate a watermark that's 60 days old
        old_watermark = (common.time.utc_now() - timedelta(days=60)).strftime("%Y-%m-%d")
        await adapter.fetch(source, from_date=old_watermark)

        call_kwargs = mock_client.fetch_all_pages.call_args.kwargs
        cutoff = (common.time.utc_now() - timedelta(days=adapter._FREE_TIER_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        assert call_kwargs["from_date"] >= cutoff


class TestNewsAPIClientQuota:
    async def test_check_quota_increments_counter(self) -> None:
        """Valkey counter should be atomically incremented on each request."""
        mock_valkey = AsyncMock()
        mock_valkey.incr.return_value = 6  # After increment: was 5, now 6
        mock_http = AsyncMock()

        from content_ingestion.config import NewsAPIProviderSettings

        client = NewsAPIClient(
            http_client=mock_http,
            api_key="test-key",
            provider_cfg=NewsAPIProviderSettings(),
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

        from content_ingestion.config import NewsAPIProviderSettings

        client = NewsAPIClient(
            http_client=mock_http,
            api_key="test-key",
            provider_cfg=NewsAPIProviderSettings(),
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

        from content_ingestion.config import NewsAPIProviderSettings

        client = NewsAPIClient(
            http_client=mock_http,
            api_key="test-key",
            provider_cfg=NewsAPIProviderSettings(),
            valkey=mock_valkey,
            daily_limit=100,
        )
        with pytest.raises(QuotaExhaustedError):
            await client._check_quota()
