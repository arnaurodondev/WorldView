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

# Process-level state so the transcripts-unavailable condition is announced
# LOUDLY but ONCE, not re-logged for every symbol on every scheduler cycle.
#   * ``_transcripts_disabled_warned`` — the capability-flag-OFF path logged its
#     single startup WARNING already.
#   * ``_transcripts_premium_blocked`` — the flag was ON but Finnhub answered
#     403; once tripped, every later cycle skips the request entirely (acts like
#     the disabled path) so we never hammer a permanently-403 premium endpoint.
_transcripts_disabled_warned = False
_transcripts_premium_blocked = False


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
        *,
        transcripts_enabled: bool = False,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()
        # Capability flag — the earnings-call transcripts endpoint is a PAID
        # Finnhub tier. Default OFF (free-tier guard): when False we never issue
        # the permanently-403 request, so there is no per-symbol/per-cycle 403
        # log spam and no api-key-bearing transcript URL for httpx to log.
        self._transcripts_enabled = transcripts_enabled

    def _record_transcripts_skip(self) -> None:
        """Surface a transcripts skip on the metric + a single loud WARNING.

        Called on the flag-OFF / breaker-tripped path (no HTTP request issued).
        The WARNING fires ONCE per process (``_transcripts_disabled_warned``) so
        the free-tier state is announced loudly but never spams the log on every
        symbol/every cycle; the counter still increments every time so the dark
        feed remains scrapeable.
        """
        global _transcripts_disabled_warned
        from content_ingestion.infrastructure.metrics.prometheus import (
            s4_finnhub_transcripts_skipped_total,
        )

        reason = "premium_403" if _transcripts_premium_blocked else "disabled"
        s4_finnhub_transcripts_skipped_total.labels(reason=reason).inc()
        if not _transcripts_disabled_warned:
            _transcripts_disabled_warned = True
            logger.warning(
                "finnhub_transcripts_disabled",
                reason=reason,
                detail=(
                    "Finnhub earnings-call transcripts require a paid plan; the "
                    "current API key is free-tier (company-news works, transcripts "
                    "return 403). Transcript fetches are skipped. Set "
                    "CONTENT_INGESTION_FINNHUB__TRANSCRIPTS_ENABLED=true after "
                    "upgrading the plan to re-enable."
                ),
            )

    def _trip_premium_breaker(self, symbol: str, endpoint: str) -> None:
        """Flip the process-level premium breaker on the first live 403.

        After this, ``fetch`` skips the transcripts request on every later cycle
        (like the disabled path) so a permanently-403 premium endpoint is never
        hammered. Emits the metric and a single loud WARNING.
        """
        global _transcripts_premium_blocked, _transcripts_disabled_warned
        from content_ingestion.infrastructure.metrics.prometheus import (
            s4_finnhub_transcripts_skipped_total,
        )

        s4_finnhub_transcripts_skipped_total.labels(reason="premium_403").inc()
        if not _transcripts_premium_blocked:
            _transcripts_premium_blocked = True
            _transcripts_disabled_warned = True  # suppress a duplicate disabled WARNING
            logger.warning(
                "finnhub_transcripts_unavailable",
                symbol=symbol,
                reason="premium_endpoint",
                endpoint=endpoint,
                detail=(
                    "Finnhub returned 403 on the transcripts endpoint — the plan "
                    "does not include transcripts. Disabling transcript fetches "
                    "for this process (no further calls will be made)."
                ),
            )

    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch news + transcripts from Finnhub for the configured symbol.

        Dedup uses sha256(str(article_id)). On 429, backs off to next minute boundary.
        """
        from datetime import timedelta

        config = source.config
        symbol = config.get("symbol", "")

        # Defense-in-depth: the company-news endpoint requires a ticker symbol.
        # A source seeded without a "symbol" key would silently produce an empty
        # string and trigger HTTP 422 on every scheduler tick (3x retries wasted).
        # Bail out early with a warning so the operator notices the misconfiguration
        # without burning API quota or filling logs with retry noise.
        if not symbol or not symbol.strip():
            logger.warning("finnhub_skip_no_symbol", source_id=str(source.id))
            return []

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
        #
        # The transcripts endpoints are a PAID Finnhub tier; on our free plan they
        # return HTTP 403 on every call (the company-news endpoint on the SAME key
        # works, so the key is valid — only transcripts are tier-gated). Two guards
        # keep this from becoming a repeating, key-leaking 403:
        #   1. Capability flag OFF (default): skip the request entirely — no HTTP
        #      call, no 403, no api-key-bearing URL for httpx to log. Announced
        #      LOUDLY but ONCE per process via a WARNING.
        #   2. Flag ON but a 403 was already seen this process: a module-level
        #      breaker (``_transcripts_premium_blocked``) makes every later cycle
        #      skip too, so we never hammer a permanently-403 premium endpoint.
        # Either way the skip is surfaced on the ``s4_finnhub_transcripts_skipped_total``
        # counter so the dark feed is scrapeable, not silently swallowed.
        transcript_list: list[dict[str, Any]] = []
        if not self._transcripts_enabled or _transcripts_premium_blocked:
            self._record_transcripts_skip()
            logger.info("finnhub_fetch_complete", symbol=symbol, new=len(results))
            return results
        try:
            transcript_list = await self._retry_request(  # type: ignore[assignment]
                lambda: self._client.fetch_transcript_list(symbol=symbol),
                retry_config=self._retry_config,
                context=f"finnhub:transcripts:{symbol}",
            )
        except PremiumEndpointError as exc:
            # Permanent licensing failure — trip the process-level breaker so
            # every later cycle skips the request entirely (no retry, no repeat
            # 403), surface it on the metric, and log a single loud WARNING.
            self._trip_premium_breaker(symbol, exc.endpoint)
        except RateLimitError as e:
            logger.warning("finnhub_rate_limited_transcripts", sleep_secs=e.sleep_secs)
            await asyncio.sleep(e.sleep_secs)
            try:
                transcript_list = await self._client.fetch_transcript_list(symbol=symbol)  # type: ignore[assignment]
            except PremiumEndpointError as exc:
                self._trip_premium_breaker(symbol, exc.endpoint)
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
