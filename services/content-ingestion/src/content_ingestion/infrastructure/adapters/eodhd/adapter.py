"""EODHD source adapter — fetches news articles via the EODHD API.

Rate limit: token bucket at configurable requests/minute (default 10 req/s).
Dedup: sha256(article.link).
Retry: 3x with 1s/2s/4s exponential backoff.
Backfill: date-range via ``from``/``to`` parameters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import common.ids
import common.time
from content_ingestion.domain.entities import FetchResult
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import Source
    from content_ingestion.domain.value_objects import TokenBucket
    from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _parse_published_at(article: dict[str, Any]) -> datetime | None:
    """Extract published_at from the EODHD article ``date`` field."""
    raw = article.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


class EODHDAdapter(SourceAdapter):
    """Fetches news articles from the EODHD API.

    Args:
        client: HTTP client for EODHD endpoints.
        rate_limiter: Token-bucket rate limiter.
        exists_fn: Async callable that checks if a url_hash already exists in fetch_log.
        retry_config: Retry parameters (defaults to 3x with 1s/2s/4s backoff).
    """

    def __init__(
        self,
        client: EODHDClient,
        rate_limiter: TokenBucket,
        exists_fn: Any = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()

    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch and deduplicate EODHD news articles.

        For each article returned by the API:
        1. Compute ``url_hash = sha256(article.link)``
        2. Skip if ``exists_fn(url_hash)`` returns True
        3. Extract ``published_at`` from ``article['date']``
        4. Build a :class:`FetchResult` with raw JSON bytes
        """
        config = source.config
        ticker = config.get("ticker", "")
        effective_from = from_date or config.get("from_date", "")
        to_date = config.get("to_date", "")

        articles = await self._retry_request(
            lambda: self._client.fetch_all_pages(ticker=ticker, from_date=effective_from, to_date=to_date),
            retry_config=self._retry_config,
            context=f"eodhd:fetch:{ticker or 'general'}",
        )
        if not isinstance(articles, list):
            return []

        results: list[FetchResult] = []
        for article in articles:
            link = article.get("link", "")
            if not link:
                continue

            article_hash = url_hash(link)

            # Dedup check
            if self._exists_fn is not None and await self._exists_fn(article_hash):
                logger.debug("eodhd_dedup_skip", url_hash=article_hash[:12])
                continue

            # Rate-limit
            if not self._rate_limiter.consume():
                wait = self._rate_limiter.wait_time()
                logger.debug("eodhd_rate_limit_wait", wait_seconds=wait)
                import asyncio

                await asyncio.sleep(wait)
                self._rate_limiter.consume()

            import json

            raw_bytes = json.dumps(article).encode("utf-8")
            published_at = _parse_published_at(article)
            title = article.get("title") or None  # EODHD news articles have a "title" field

            results.append(
                FetchResult(
                    source_id=source.id,
                    url=link,
                    url_hash=article_hash,
                    raw_bytes=raw_bytes,
                    fetched_at=common.time.utc_now(),
                    http_status=200,
                    content_type="application/json",
                    published_at=published_at,
                    is_backfill=is_backfill,
                    title=title,
                ),
            )

        logger.info("eodhd_fetch_complete", total_api=len(articles), new=len(results))
        return results
