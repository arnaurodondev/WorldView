"""NewsAPI source adapter — fetches articles via the NewsAPI.org API.

Rate limit: Valkey daily quota counter with 86400s TTL.
Dedup: sha256(article.url).
Retry: No retry on QuotaExhaustedError (breaks immediately).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import common.ids
import common.time
from content_ingestion.domain.entities import FetchResult
from content_ingestion.domain.exceptions import QuotaExhaustedError
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.newsapi.client import NewsAPIClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _parse_published_at(article: dict[str, Any]) -> datetime | None:
    """Extract published_at from the NewsAPI ``publishedAt`` ISO-8601 field."""
    raw = article.get("publishedAt")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        return None


class NewsAPIAdapter(SourceAdapter):
    """Fetches articles from NewsAPI.org with Valkey-based daily quota tracking.

    On QuotaExhaustedError, the adapter breaks immediately (no retry).

    Args:
        client: HTTP client for NewsAPI endpoints.
        exists_fn: Async callable checking url_hash existence.
        retry_config: Retry parameters.
    """

    def __init__(
        self,
        client: NewsAPIClient,
        exists_fn: Any = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._client = client
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()

    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch and deduplicate NewsAPI articles.

        QuotaExhaustedError propagates immediately — no retry.
        """
        config = source.config
        query = config.get("query", "")
        effective_from = from_date or config.get("from_date", "")

        try:
            articles = await self._client.fetch_all_pages(query=query, from_date=effective_from)
        except QuotaExhaustedError:
            logger.warning("newsapi_quota_exhausted", query=query)
            raise

        results: list[FetchResult] = []
        for article in articles:
            article_url = article.get("url", "")
            if not article_url:
                continue

            article_hash = url_hash(article_url)

            if self._exists_fn is not None and await self._exists_fn(article_hash):
                logger.debug("newsapi_dedup_skip", url_hash=article_hash[:12])
                continue

            raw_bytes = json.dumps(article).encode("utf-8")
            published_at = _parse_published_at(article)

            results.append(
                FetchResult(
                    source_id=source.id,
                    url=article_url,
                    url_hash=article_hash,
                    raw_bytes=raw_bytes,
                    fetched_at=common.time.utc_now(),
                    http_status=200,
                    content_type="application/json",
                    published_at=published_at,
                    is_backfill=is_backfill,
                ),
            )

        logger.info("newsapi_fetch_complete", total_api=len(articles), new=len(results))
        return results
