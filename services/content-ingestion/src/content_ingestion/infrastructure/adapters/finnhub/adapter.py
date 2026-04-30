"""Finnhub source adapter — fetches news and earnings transcripts.

Rate limit: TokenBucket(55 req/min).
Dedup: sha256(str(article_id)).
Retry: 3x with 1s/2s/4s exponential backoff; on 429, sleep to next minute boundary.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import common.ids
import common.time
from content_ingestion.domain.entities import FetchResult
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash
from content_ingestion.infrastructure.adapters.finnhub.client import PremiumEndpointError, RateLimitError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.domain.entities import Source
    from content_ingestion.domain.value_objects import TokenBucket
    from content_ingestion.infrastructure.adapters.finnhub.client import FinnhubClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _parse_published_at(article: dict[str, Any]) -> datetime | None:
    """Extract published_at from a Finnhub article's Unix timestamp ``datetime`` field."""
    raw = article.get("datetime")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (ValueError, TypeError, OSError):
        return None


class FinnhubAdapter(SourceAdapter):
    """Fetches news articles and earnings transcripts from Finnhub.

    Args:
        client: HTTP client for Finnhub endpoints.
        rate_limiter: Token-bucket rate limiter (55 req/min).
        exists_fn: Async callable checking url_hash existence.
        retry_config: Retry parameters.
    """

    def __init__(
        self,
        client: FinnhubClient,
        rate_limiter: TokenBucket,
        exists_fn: Any = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()

    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch news + transcripts from Finnhub for the configured symbol.

        Dedup uses sha256(str(article_id)). On 429, backs off to next minute boundary.
        """
        from datetime import timedelta

        config = source.config
        symbol = config.get("symbol", "")
        effective_from = from_date or config.get("from_date", "")
        to_date = config.get("to_date", "")

        # Finnhub company-news requires both from and to date parameters.
        # Default to today's date when to_date is missing; default from_date
        # to 30 days ago when also absent (incremental mode fetches recent news).
        now_utc = datetime.now(tz=UTC)
        if not to_date:
            to_date = now_utc.strftime("%Y-%m-%d")
        if not effective_from:
            effective_from = (now_utc - timedelta(days=30)).strftime("%Y-%m-%d")

        results: list[FetchResult] = []

        # Fetch company news
        try:
            articles = await self._retry_request(
                lambda: self._client.fetch_company_news(symbol=symbol, from_date=effective_from, to_date=to_date),
                retry_config=self._retry_config,
                context=f"finnhub:news:{symbol}",
            )
        except RateLimitError as e:
            logger.warning("finnhub_rate_limited", sleep_secs=e.sleep_secs)
            await asyncio.sleep(e.sleep_secs)
            articles = await self._client.fetch_company_news(symbol=symbol, from_date=effective_from, to_date=to_date)

        if isinstance(articles, list):
            for article in articles:
                article_id = article.get("id", "")
                if not article_id:
                    continue

                article_hash = url_hash(str(article_id))

                if self._exists_fn is not None and await self._exists_fn(article_hash):
                    logger.debug("finnhub_dedup_skip", url_hash=article_hash[:12])
                    continue

                # NOTE: No rate-limit consumption per news article — all articles
                # come from a single API call, not one call per article.
                # Rate limiting is applied only to transcript fetches below.
                raw_bytes = json.dumps(article).encode("utf-8")
                article_url = article.get("url", f"https://finnhub.io/news/{article_id}")
                title = article.get("headline") or None  # Finnhub uses "headline" not "title"

                results.append(
                    FetchResult(
                        source_id=source.id,
                        url=article_url,
                        url_hash=article_hash,
                        raw_bytes=raw_bytes,
                        fetched_at=common.time.utc_now(),
                        http_status=200,
                        content_type="application/json",
                        published_at=_parse_published_at(article),
                        is_backfill=is_backfill,
                        title=title,
                    ),
                )

        # Fetch transcripts (premium feature — gracefully skip if account lacks access).
        # F-104 fix: PremiumEndpointError now short-circuits before the retry loop,
        # so a free-tier account no longer wastes 3 retries x backoff per symbol per
        # cycle. Any other error still falls through to the existing soft-skip path.
        transcript_list: list[dict[str, Any]] = []
        try:
            transcript_list = await self._retry_request(  # type: ignore[assignment]
                lambda: self._client.fetch_transcript_list(symbol=symbol),
                retry_config=self._retry_config,
                context=f"finnhub:transcripts:{symbol}",
            )
        except PremiumEndpointError as exc:
            # Permanent licensing failure — log once at info, do NOT retry.
            logger.info(
                "finnhub_transcripts_unavailable",
                symbol=symbol,
                reason="premium_endpoint",
                endpoint=exc.endpoint,
            )
        except RateLimitError as e:
            logger.warning("finnhub_rate_limited_transcripts", sleep_secs=e.sleep_secs)
            await asyncio.sleep(e.sleep_secs)
            try:
                transcript_list = await self._client.fetch_transcript_list(symbol=symbol)  # type: ignore[assignment]
            except PremiumEndpointError as exc:
                logger.info(
                    "finnhub_transcripts_unavailable",
                    symbol=symbol,
                    reason="premium_endpoint",
                    endpoint=exc.endpoint,
                )
        except Exception as exc:
            # Non-403, non-429 errors — keep the soft-skip behaviour but log at warning
            # so the operator notices a real adapter regression (vs. premium licensing).
            logger.warning(
                "finnhub_transcripts_unavailable",
                symbol=symbol,
                reason="adapter_error",
                error=str(exc),
            )

        if isinstance(transcript_list, list):
            for transcript_meta in transcript_list:
                t_id = str(transcript_meta.get("id", ""))
                if not t_id:
                    continue

                transcript_hash = url_hash(f"transcript:{t_id}")

                if self._exists_fn is not None and await self._exists_fn(transcript_hash):
                    continue

                if not self._rate_limiter.consume():
                    wait = self._rate_limiter.wait_time()
                    await asyncio.sleep(wait)
                    self._rate_limiter.consume()

                try:
                    transcript = await self._retry_request(
                        lambda _tid=t_id: self._client.fetch_transcript(transcript_id=_tid),
                        retry_config=self._retry_config,
                        context=f"finnhub:transcript:{t_id}",
                    )
                except Exception:
                    logger.warning("finnhub_transcript_fetch_failed", transcript_id=t_id)
                    continue

                if isinstance(transcript, dict):
                    raw_bytes = json.dumps(transcript).encode("utf-8")
                    results.append(
                        FetchResult(
                            source_id=source.id,
                            url=f"https://finnhub.io/transcripts/{t_id}",
                            url_hash=transcript_hash,
                            raw_bytes=raw_bytes,
                            fetched_at=common.time.utc_now(),
                            http_status=200,
                            content_type="application/json",
                            published_at=None,
                            is_backfill=is_backfill,
                        ),
                    )

        logger.info("finnhub_fetch_complete", symbol=symbol, new=len(results))
        return results
