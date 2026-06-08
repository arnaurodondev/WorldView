"""Unit tests for the Finnhub adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.value_objects import TokenBucket
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.finnhub.adapter import FinnhubAdapter, _parse_published_at
from content_ingestion.infrastructure.adapters.finnhub.client import FinnhubClient, RateLimitError

import common.time

pytestmark = pytest.mark.unit


def _make_source(**kwargs: Any) -> Source:
    defaults: dict[str, Any] = {
        "name": "test-finnhub",
        "source_type": SourceType.FINNHUB,
        "enabled": True,
        "config": {"symbol": "AAPL", "from_date": "2026-01-01", "to_date": "2026-03-01"},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _make_bucket() -> TokenBucket:
    return TokenBucket(capacity=55, tokens=55.0, refill_rate=55.0 / 60.0, last_refill=common.time.utc_now())


def _article(article_id: int, url: str = "") -> dict[str, Any]:
    return {
        "id": article_id,
        "url": url or f"https://finnhub.io/news/{article_id}",
        "headline": f"Article {article_id}",
        "datetime": 1774000000,  # approx 2026-03
    }


class TestParsePublishedAt:
    def test_valid_unix_timestamp(self) -> None:
        result = _parse_published_at({"datetime": 1774000000})
        assert result is not None
        assert result.year >= 2026

    def test_missing_datetime(self) -> None:
        assert _parse_published_at({}) is None

    def test_invalid_datetime(self) -> None:
        assert _parse_published_at({"datetime": "not-a-number"}) is None


class TestFinnhubAdapterFetch:
    async def test_fetches_news_and_returns_results(self) -> None:
        mock_client = AsyncMock(spec=FinnhubClient)
        mock_client.fetch_company_news.return_value = [_article(1001), _article(1002)]
        mock_client.fetch_transcript_list.return_value = []

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 2

    async def test_dedup_skips_existing(self) -> None:
        mock_client = AsyncMock(spec=FinnhubClient)
        mock_client.fetch_company_news.return_value = [_article(2001)]
        mock_client.fetch_transcript_list.return_value = []
        exists_fn = AsyncMock(return_value=True)

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            exists_fn=exists_fn,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0

    async def test_published_at_from_unix_timestamp(self) -> None:
        mock_client = AsyncMock(spec=FinnhubClient)
        mock_client.fetch_company_news.return_value = [_article(3001)]
        mock_client.fetch_transcript_list.return_value = []

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert results[0].published_at is not None

    async def test_429_backoff(self) -> None:
        """On 429, adapter should sleep then retry."""
        mock_client = AsyncMock(spec=FinnhubClient)
        call_count = 0

        async def rate_limited_news(**_kw: Any) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitError(sleep_secs=0.01)
            return [_article(4001)]

        mock_client.fetch_company_news.side_effect = rate_limited_news
        mock_client.fetch_transcript_list.return_value = []

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert call_count == 2

    async def test_is_backfill_propagated(self) -> None:
        mock_client = AsyncMock(spec=FinnhubClient)
        mock_client.fetch_company_news.return_value = [_article(5001)]
        mock_client.fetch_transcript_list.return_value = []

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(), is_backfill=True)
        assert len(results) == 1
        assert results[0].is_backfill is True

    # ------------------------------------------------------------------
    # Regression tests for the empty-symbol guard (BP-XXX)
    # A source seeded without a "symbol" key must return [] immediately
    # without making any HTTP call, so we do not waste API quota or
    # produce HTTP 422 retry noise on every scheduler tick.
    # ------------------------------------------------------------------

    async def test_empty_symbol_returns_empty_without_http_call(self) -> None:
        """fetch() must bail out early when config has no symbol key."""
        mock_client = AsyncMock(spec=FinnhubClient)

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(config={}))

        assert results == []
        mock_client.fetch_company_news.assert_not_called()
        mock_client.fetch_transcript_list.assert_not_called()

    async def test_whitespace_only_symbol_returns_empty_without_http_call(self) -> None:
        """fetch() must bail out early when symbol is whitespace-only."""
        mock_client = AsyncMock(spec=FinnhubClient)

        adapter = FinnhubAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(config={"symbol": "   "}))

        assert results == []
        mock_client.fetch_company_news.assert_not_called()
        mock_client.fetch_transcript_list.assert_not_called()
