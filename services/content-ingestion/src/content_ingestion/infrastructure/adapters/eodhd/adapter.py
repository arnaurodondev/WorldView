"""EODHD source adapter — fetches news articles via the EODHD API.

Rate limit: token bucket at configurable requests/minute (default 10 req/s).
Dedup: sha256(article.link).
Retry: 3x with 1s/2s/4s exponential backoff.
Backfill: date-range via ``from``/``to`` parameters.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import common.ids
import common.time
from content_ingestion.domain.entities import FetchResult
from content_ingestion.infrastructure.adapters.base import RetryConfig, SourceAdapter, url_hash
from content_ingestion.infrastructure.metrics.prometheus import record_general_firehose_sweep
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

    Two code paths:

    - **Legacy bulk pull** (``firehose_enabled=False`` or a ``ticker``-scoped
      source): ``fetch_all_pages`` pulls every page since the watermark, then
      dedups. Cheap for the hourly incremental cadence it was designed for.
    - **General firehose EARLY-EXIT sweep** (``firehose_enabled=True`` +
      filter-less/general source, SHADOW STAGE 2026-07-01): paginates
      page-by-page and STOPS the whole sweep as soon as it hits an article whose
      url_hash is already stored. Because the general feed returns newest-first,
      the first already-stored article means every remaining (older) article is
      also stored — so a steady-state high-frequency poll costs exactly ONE
      request (5 credits). See :meth:`_fetch_firehose`.

    Args:
        client: HTTP client for EODHD endpoints.
        rate_limiter: Token-bucket rate limiter.
        exists_fn: Async callable that checks if a url_hash already exists in fetch_log.
        retry_config: Retry parameters (defaults to 3x with 1s/2s/4s backoff).
        firehose_enabled: Enable the general early-exit sweep (default OFF).
        shadow_mode: Emit the SHADOW coverage signal per sweep (default OFF).
        page_size: Page size for the firehose sweep (defaults to the client's).
        max_pages: Defensive per-sweep page cap for the firehose sweep.
    """

    def __init__(
        self,
        client: EODHDClient,
        rate_limiter: TokenBucket,
        exists_fn: Any = None,
        retry_config: RetryConfig | None = None,
        *,
        firehose_enabled: bool = False,
        shadow_mode: bool = False,
        page_size: int = 100,
        max_pages: int = 3,
    ) -> None:
        self._client = client
        self._rate_limiter = rate_limiter
        self._exists_fn = exists_fn
        self._retry_config = retry_config or RetryConfig()
        self._firehose_enabled = firehose_enabled
        self._shadow_mode = shadow_mode
        # ge=1 guards: a zero page_size would make ``len(page) < page_size``
        # always False and spin the sweep to the page cap every time.
        self._page_size = max(1, page_size)
        self._max_pages = max(1, max_pages)

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
        # QUOTA-OPT (2026-06-16): anchor ``from`` on the watermark and set
        # ``to=today`` so EODHD returns the entire batch since our last sweep
        # in one (paginated) call — EODHD bills per-request, not per-article.
        # ``from_date`` already carries the watermark (or "" on first run);
        # an explicit source-config ``from_date``/``to_date`` still wins for
        # operator-driven backfills.
        effective_from = from_date or config.get("from_date", "")
        to_date = config.get("to_date", "") or common.time.utc_now().date().isoformat()

        # SHADOW STAGE: route the filter-less GENERAL feed through the early-exit
        # sweep when the firehose flag is on. Requires ``exists_fn`` — without a
        # dedup oracle there is no "already-seen boundary" to early-exit on, so we
        # fall back to the legacy bulk pull. A ``ticker``-scoped source never uses
        # the firehose (it is the per-symbol legacy path).
        if self._firehose_enabled and not ticker and self._exists_fn is not None:
            return await self._fetch_firehose(
                source,
                from_date=effective_from,
                to_date=to_date,
                is_backfill=is_backfill,
            )

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

            await self._respect_rate_limit()

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

    async def _fetch_firehose(
        self,
        source: Source,
        *,
        from_date: str,
        to_date: str,
        is_backfill: bool,
    ) -> list[FetchResult]:
        """High-frequency EARLY-EXIT sweep of the general (filter-less) news feed.

        Paginates one page at a time via :meth:`EODHDClient.fetch_news` (which
        records the shared EODHD quota with ``endpoint="news"`` on each request).
        The sweep STOPS as soon as it encounters an article already stored in
        ``fetch_log`` — the general feed is newest-first, so the first stored
        article implies every remaining (older) one is stored too. In steady
        state (e.g. a 60s poll) the newest article is already stored, so the
        sweep exits after ONE request (5 credits).

        Termination reasons (recorded as the sweep ``outcome``):
        - ``early_exit``: hit an already-stored article — the normal 1-request case.
        - ``drained``: a partial page (< page_size) — no more data since ``from``.
        - ``page_cap``: the ``max_pages`` backstop (guards an EODHD that ignores
          ``offset`` and returns full pages forever — QA H1). Logged as WARNING;
          the watermark is not advanced past unfetched articles, so nothing is lost.
        """
        results: list[FetchResult] = []
        seen_in_sweep: set[str] = set()
        symbol_tag_count = 0
        offset = 0
        page_count = 0
        outcome = "drained"

        while True:
            page = await self._retry_request(
                lambda o=offset: self._client.fetch_news(
                    ticker="",
                    from_date=from_date,
                    to_date=to_date,
                    offset=o,
                ),
                retry_config=self._retry_config,
                context="eodhd:firehose",
            )
            page_count += 1
            if not isinstance(page, list):
                break

            early_exit = False
            for article in page:
                if not isinstance(article, dict):
                    continue
                link = str(article.get("link") or "").strip()
                if not link:
                    continue
                article_hash = url_hash(link)
                # Intra-sweep dedup: the watermark's date-granular overlap can
                # return the same article across pages; collapse before the
                # exists check so a within-batch dup is never treated as the
                # already-stored boundary.
                if article_hash in seen_in_sweep:
                    continue
                seen_in_sweep.add(article_hash)

                # EARLY-EXIT boundary: first already-stored article ends the sweep.
                if await self._exists_fn(article_hash):
                    logger.debug("eodhd_firehose_early_exit", url_hash=article_hash[:12], page=page_count)
                    early_exit = True
                    outcome = "early_exit"
                    break

                await self._respect_rate_limit()

                # SHADOW coverage signal: count the symbol tags carried by this
                # article (the general feed's superset advantage over per-ticker).
                symbols = article.get("symbols")
                if isinstance(symbols, list):
                    symbol_tag_count += len(symbols)

                results.append(
                    FetchResult(
                        source_id=source.id,
                        url=link,
                        url_hash=article_hash,
                        raw_bytes=json.dumps(article).encode("utf-8"),
                        fetched_at=common.time.utc_now(),
                        http_status=200,
                        content_type="application/json",
                        published_at=_parse_published_at(article),
                        is_backfill=is_backfill,
                        title=article.get("title") or None,
                    ),
                )

            if early_exit:
                break
            # Partial page → we have drained everything since ``from``.
            if len(page) < self._page_size:
                outcome = "drained"
                break
            # Defensive backstop: never spin forever if EODHD ignores ``offset``.
            if page_count >= self._max_pages:
                outcome = "page_cap"
                logger.warning(
                    "eodhd_firehose_page_cap_reached",
                    pages=page_count,
                    max_pages=self._max_pages,
                    fetched_so_far=len(results),
                )
                break
            offset += self._page_size

        # Always record the sweep so the early_exit-request ratio (credit
        # efficiency) is observable; symbol_tags is the SHADOW coverage signal.
        record_general_firehose_sweep(
            requests=page_count,
            outcome=outcome,
            new_articles=len(results),
            symbol_tags=symbol_tag_count,
        )
        log_event = "eodhd_firehose_shadow_sweep" if self._shadow_mode else "eodhd_firehose_sweep_complete"
        logger.info(
            log_event,
            requests=page_count,
            outcome=outcome,
            new=len(results),
            symbol_tags=symbol_tag_count,
            shadow_mode=self._shadow_mode,
        )
        return results

    async def _respect_rate_limit(self) -> None:
        """Consume one token, sleeping if the bucket is momentarily empty."""
        if self._rate_limiter.consume():
            return
        wait = self._rate_limiter.wait_time()
        logger.debug("eodhd_rate_limit_wait", wait_seconds=wait)
        import asyncio

        await asyncio.sleep(wait)
        self._rate_limiter.consume()
