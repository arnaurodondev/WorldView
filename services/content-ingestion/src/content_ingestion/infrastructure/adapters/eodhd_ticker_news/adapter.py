"""EODHD per-ticker news adapter for content-ingestion (PLAN-0106 Wave C-1).

Fetches news articles for a specific equity ticker from EODHD's /api/v1/news
endpoint, routing them into the content.article.raw.v1 pipeline (not
market.dataset.fetched — this is article content, not financial data).

Differences from the global EODHDAdapter (adapters/eodhd/adapter.py):
  - Config carries ``symbol`` + ``exchange`` instead of a global ticker.
  - Issues a single HTTP request (no pagination) with ``limit=50``.
  - Uses the standard ``httpx.AsyncClient`` directly — no EODHD-specific
    client wrapper — because the per-ticker endpoint is simpler and does
    not need the paginated ``fetch_all_pages`` contract.
  - Raises ``AdapterError`` (subclass of ``DomainError``) on non-2xx
    responses; preserves ``ProviderRateLimited`` naming via ``AdapterError``
    with a ``rate_limited=True`` attribute for the scheduler back-off path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx

import common.ids  # type: ignore[import-untyped]
import common.time  # type: ignore[import-untyped]
from content_ingestion.domain.entities import FetchResult
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.base import SourceAdapter, url_hash
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from content_ingestion.config import Settings
    from content_ingestion.domain.entities import Source

logger = get_logger(__name__)  # type: ignore[no-any-return]

# EODHD per-ticker news endpoint — separate from the global news feed
# (https://eodhd.com/api/news) to allow symbol-scoped fetching without
# consuming the credits/quota of the general news cycle.
_EODHD_TICKER_NEWS_BASE_URL = "https://eodhd.com/api/v1/news"
# 50 articles per request keeps credit usage low; a separate scheduled job
# (TickerNewsSymbolSyncWorker) re-enqueues each ticker every 6 hours so
# freshness is preserved without hammering the API.
_DEFAULT_LIMIT = 50


class ProviderRateLimited(AdapterError):  # noqa: N818
    """Raised when EODHD returns HTTP 429.

    WHY a subclass of ``AdapterError`` rather than a new domain exception:
    ``AdapterError`` is the established infrastructure-level error for
    adapter failures.  Subclassing it lets callers that only catch
    ``AdapterError`` remain unchanged while callers that need to distinguish
    rate-limit-specific back-off can do so via ``isinstance``.

    WHY N818 suppressed: ``ProviderRateLimited`` follows the naming convention
    used by market-ingestion's ``ProviderRateLimited`` (domain/errors.py) to
    keep the two services' error vocabularies consistent for operators.
    """


class EODHDTickerNewsAdapter(SourceAdapter):
    """Fetch news articles for a single equity ticker from EODHD /api/v1/news.

    Source config keys:
        ``symbol``   (str): Equity ticker, e.g. ``"AAPL"``.
        ``exchange`` (str): Exchange suffix, e.g. ``"US"``.

    The constructed URL is::

        https://eodhd.com/api/v1/news?s={symbol}.{exchange}&api_token={key}&limit=50&fmt=json

    An optional ``from`` query parameter is included when the adapter
    receives a non-empty ``from_date`` watermark from the scheduler — this
    avoids re-fetching articles already stored on previous cycles.

    Error handling:
        - HTTP 429  → ``ProviderRateLimited`` (subclass of ``AdapterError``)
        - Other non-2xx → ``AdapterError``
        - Empty/missing config fields → skip + WARNING, return ``[]``
    """

    def __init__(self, settings: Settings) -> None:
        # Settings is injected by the scheduler when constructing adapters so
        # the API key is read from the environment at runtime rather than
        # being baked into the adapter at import time.
        self._api_key: str = settings.eodhd_api_key

    async def fetch(
        self,
        source: Source,
        *,
        is_backfill: bool = False,
        from_date: str = "",
    ) -> list[FetchResult]:
        """Fetch per-ticker news from EODHD and return new ``FetchResult`` objects.

        Args:
            source: The ``eodhd_ticker_news`` source row; ``source.config``
                    must contain ``{"symbol": str, "exchange": str}``.
            is_backfill: Propagated to each ``FetchResult`` so downstream
                         consumers (S5, S10) can suppress alert fan-out.
            from_date: Optional watermark date (``YYYY-MM-DD``) injected by
                       the scheduler.  Maps to EODHD's ``from`` query param.

        Returns:
            List of ``FetchResult`` for every article returned by the API.

        Raises:
            ProviderRateLimited: On HTTP 429.
            AdapterError: On other non-2xx responses.
        """
        config = source.config

        # Validate required config keys — if either is missing we cannot build
        # a meaningful EODHD URL.  Log a warning and return empty so the task
        # is marked succeeded (not retried) — a malformed config won't self-
        # heal on retry; operator intervention is needed.
        symbol: str = str(config.get("symbol", "")).strip().upper()
        exchange: str = str(config.get("exchange", "")).strip().upper()

        if not symbol or not exchange:
            logger.warning(
                "eodhd_ticker_news_bad_config",
                source_id=str(source.id),
                source_name=source.name,
                config=config,
                hint="source.config must have 'symbol' and 'exchange' keys",
            )
            return []

        # Build query parameters for the EODHD /api/v1/news endpoint.
        # ``fmt=json`` is mandatory — without it EODHD returns CSV.
        params: dict[str, str | int] = {
            "s": f"{symbol}.{exchange}",
            "api_token": self._api_key,
            "limit": _DEFAULT_LIMIT,
            "fmt": "json",
        }

        # Watermark: only fetch articles published after the last successful
        # run so we don't re-ingest the same 50 articles on every tick.
        if from_date:
            params["from"] = from_date

        url = _EODHD_TICKER_NEWS_BASE_URL

        logger.debug(
            "eodhd_ticker_news_fetch_start",
            symbol=symbol,
            exchange=exchange,
            source_id=str(source.id),
            from_date=from_date or "none",
        )

        try:
            # BP-235: always set an explicit httpx.Timeout — never rely on
            # the httpx 5-second default for cross-service / external calls.
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            msg = f"EODHD ticker-news HTTP error for {symbol}.{exchange}: {exc}"
            raise AdapterError(msg) from exc

        # Rate-limit — EODHD returns 429 under burst load; the scheduler
        # back-off path (scheduler.py _poll_loop) catches ``AdapterError``
        # and backs off; callers that care specifically about rate-limits
        # can isinstance-check ``ProviderRateLimited``.
        if resp.status_code == 429:
            msg = f"EODHD rate-limited for {symbol}.{exchange} (HTTP 429)"
            raise ProviderRateLimited(msg)

        if resp.status_code != 200:
            msg = f"EODHD ticker-news non-200 for {symbol}.{exchange}: HTTP {resp.status_code}"
            raise AdapterError(msg)

        try:
            articles: object = resp.json()
        except ValueError as exc:
            msg = f"EODHD ticker-news JSON decode error for {symbol}.{exchange}: {exc}"
            raise AdapterError(msg) from exc

        if not isinstance(articles, list):
            logger.warning(
                "eodhd_ticker_news_unexpected_response_shape",
                symbol=symbol,
                exchange=exchange,
                response_type=type(articles).__name__,
            )
            return []

        results: list[FetchResult] = []
        fetched_at = common.time.utc_now()

        for article in articles:
            if not isinstance(article, dict):
                continue

            link: str = str(article.get("link") or "").strip()
            if not link:
                # EODHD occasionally returns articles without a link; skip
                # them since URL dedup relies on the link field.
                continue

            article_hash = url_hash(link)
            raw_bytes: bytes = json.dumps(article).encode("utf-8")
            published_at: datetime | None = _parse_published_at(article)
            title: str | None = article.get("title") or None

            results.append(
                FetchResult(
                    source_id=source.id,
                    url=link,
                    url_hash=article_hash,
                    raw_bytes=raw_bytes,
                    fetched_at=fetched_at,
                    http_status=200,
                    content_type="application/json",
                    published_at=published_at,
                    is_backfill=is_backfill,
                    title=title,
                )
            )

        logger.info(
            "eodhd_ticker_news_fetch_complete",
            symbol=symbol,
            exchange=exchange,
            total_api=len(articles),
            new=len(results),
        )
        return results


def _parse_published_at(article: dict) -> datetime | None:  # type: ignore[type-arg]
    """Extract publication datetime from the EODHD article ``date`` field.

    EODHD may return dates as ISO 8601 strings (``"2026-06-05T14:30:00+00:00"``)
    or bare date strings (``"2026-06-05"``).  Both are handled; timezone-naive
    values are assumed UTC and made aware.
    """
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
