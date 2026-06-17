"""EODHD per-ticker news adapter for content-ingestion (PLAN-0106 Wave C-1).

Fetches news articles for a specific equity ticker from EODHD's /api/news
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
from datetime import UTC, date, datetime, timedelta
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
# BP-XXX: EODHD has no /api/v1/ namespace; /api/v1/news returns HTTP 404
# (marketing HTML).  Correct path is /api/news (same as global feed but with
# ?s= param for per-ticker scoping).
_EODHD_TICKER_NEWS_BASE_URL = "https://eodhd.com/api/news"


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
    """Fetch news articles for a single equity ticker from EODHD /api/news.

    Source config keys:
        ``symbol``   (str): Equity ticker, e.g. ``"AAPL"``.
        ``exchange`` (str): Exchange suffix, e.g. ``"US"``.

    The constructed URL is::

        https://eodhd.com/api/news?s={symbol}.{exchange}&api_token={key}&limit=50&fmt=json

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
        # QUOTA-OPT (2026-06-16): pull the WHOLE batch since the watermark in
        # one request. EODHD bills per-request (flat 5 + 5/ticker) regardless of
        # how many articles come back, so a single ``limit=1000`` request is the
        # cheapest way to capture every new article. ``_page_limit`` doubles as
        # the pagination trigger: a full page implies there may be more.
        self._page_limit: int = settings.eodhd.news_page_limit
        # Defensive cap on pages per sweep — backstop against an EODHD that
        # ignores ``offset`` and returns full pages forever (QA H1).
        self._max_pages: int = settings.eodhd.news_max_pages
        # Days subtracted from the watermark to build ``from`` (boundary-safe).
        self._overlap_days: int = settings.eodhd.news_watermark_overlap_days
        # First-run horizon when there is no watermark yet — a BOUNDED backfill
        # rather than "since epoch", which would be an unbounded sweep.
        self._backfill_days: int = settings.backfill_initial_days

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

        # EODHD encodes US share classes with a hyphen (BRK-B.US), not a second
        # dot. A stored dot-class symbol (BRK.B) would yield s=BRK.B.US -> HTTP 422.
        # Translate at the EODHD boundary ONLY; canonical symbol/exchange (used in
        # logs + error messages) are left untouched.
        eodhd_symbol = symbol.replace(".", "-")

        # ── Build the [from, to] window for this sweep (QUOTA-OPT) ──────────
        # ``from`` anchors on the stored watermark minus a safety overlap so a
        # boundary article is never missed; on an empty watermark we fall back
        # to a BOUNDED backfill horizon (never "since epoch"). ``to`` is today
        # so EODHD returns the whole batch up to now in a single sweep.
        effective_from = self._resolve_from_date(from_date)
        to_date = common.time.utc_now().date().isoformat()

        # ``s`` and ``api_token`` are constant across pages; ``offset``/``limit``
        # drive pagination. ``fmt=json`` is mandatory — without it EODHD CSVs.
        base_params: dict[str, str | int] = {
            "s": f"{eodhd_symbol}.{exchange}",
            "api_token": self._api_key,
            "limit": self._page_limit,
            "from": effective_from,
            "to": to_date,
            "fmt": "json",
        }

        url = _EODHD_TICKER_NEWS_BASE_URL

        logger.debug(
            "eodhd_ticker_news_fetch_start",
            symbol=symbol,
            exchange=exchange,
            source_id=str(source.id),
            from_date=effective_from,
            to_date=to_date,
            limit=self._page_limit,
        )

        results: list[FetchResult] = []
        fetched_at = common.time.utc_now()
        seen_hashes: set[str] = set()
        total_api = 0
        offset = 0
        page_count = 0

        # BP-235: always set an explicit httpx.Timeout — never rely on the
        # httpx 5-second default for cross-service / external calls.  One
        # client is reused across pages so a paginated sweep shares the pool.
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            while True:
                params = {**base_params, "offset": offset}
                articles = await self._fetch_page(client, url, params, symbol, exchange)
                page_count += 1
                total_api += len(articles)

                for article in articles:
                    if not isinstance(article, dict):
                        continue
                    link: str = str(article.get("link") or "").strip()
                    if not link:
                        # EODHD occasionally returns articles without a link;
                        # skip — URL dedup relies on the link field.
                        continue
                    article_hash = url_hash(link)
                    # Intra-sweep dedup: the watermark overlap can return the
                    # same article on consecutive pages/runs; collapse here so
                    # the downstream pipeline never sees an in-batch duplicate.
                    if article_hash in seen_hashes:
                        continue
                    seen_hashes.add(article_hash)
                    results.append(
                        FetchResult(
                            source_id=source.id,
                            url=link,
                            url_hash=article_hash,
                            raw_bytes=json.dumps(article).encode("utf-8"),
                            fetched_at=fetched_at,
                            http_status=200,
                            content_type="application/json",
                            published_at=_parse_published_at(article),
                            is_backfill=is_backfill,
                            title=article.get("title") or None,
                        )
                    )

                # Paginate ONLY when the page was full — a partial page means
                # we have drained every article since the watermark, so the
                # normal incremental run is exactly one request.
                if len(articles) < self._page_limit:
                    break
                # Defensive backstop (QA H1): if EODHD keeps returning full
                # pages (e.g. it ignores ``offset``), stop at the cap rather
                # than spinning forever. Log a WARNING so a genuinely huge
                # backlog is visible and never silently truncated — the next
                # sweep continues from the (un-advanced-past-unfetched)
                # watermark, so no article is lost.
                if page_count >= self._max_pages:
                    logger.warning(
                        "eodhd_ticker_news_page_cap_reached",
                        symbol=symbol,
                        exchange=exchange,
                        pages=page_count,
                        max_pages=self._max_pages,
                        fetched_so_far=len(results),
                    )
                    break
                offset += self._page_limit

        logger.info(
            "eodhd_ticker_news_fetch_complete",
            symbol=symbol,
            exchange=exchange,
            total_api=total_api,
            new=len(results),
            pages=page_count,
        )
        return results

    def _resolve_from_date(self, watermark: str) -> str:
        """Return the EODHD ``from`` date (YYYY-MM-DD) for this sweep.

        - With a watermark: ``watermark - overlap_days`` so a same-day boundary
          article is never dropped (downstream url_hash dedup absorbs the
          re-fetch at zero extra credit cost).
        - Without a watermark (first run): a BOUNDED backfill horizon
          ``today - backfill_days`` — never an unbounded "since epoch" sweep.
        """
        if watermark:
            try:
                anchor = date.fromisoformat(watermark)
            except ValueError:
                # Malformed stored watermark — fall back to the bounded horizon
                # rather than sending EODHD an invalid ``from`` (HTTP 422).
                anchor = common.time.utc_now().date() - timedelta(days=self._backfill_days)
            else:
                anchor = anchor - timedelta(days=self._overlap_days)
        else:
            anchor = common.time.utc_now().date() - timedelta(days=self._backfill_days)
        return anchor.isoformat()

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str | int],
        symbol: str,
        exchange: str,
    ) -> list[dict]:  # type: ignore[type-arg]
        """Fetch one page, mapping transport/HTTP errors to adapter errors.

        On HTTP 429 raises ``ProviderRateLimited`` so the worker's retry/back-off
        path engages and the watermark is NOT advanced (a failed fetch must not
        look like a successful empty poll).
        """
        try:
            resp = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            msg = f"EODHD ticker-news HTTP error for {symbol}.{exchange}: {exc}"
            raise AdapterError(msg) from exc

        if resp.status_code == 429:
            msg = f"EODHD rate-limited for {symbol}.{exchange} (HTTP 429)"
            raise ProviderRateLimited(msg)
        if resp.status_code != 200:
            msg = f"EODHD ticker-news non-200 for {symbol}.{exchange}: HTTP {resp.status_code}"
            raise AdapterError(msg)

        try:
            payload: object = resp.json()
        except ValueError as exc:
            msg = f"EODHD ticker-news JSON decode error for {symbol}.{exchange}: {exc}"
            raise AdapterError(msg) from exc

        if not isinstance(payload, list):
            logger.warning(
                "eodhd_ticker_news_unexpected_response_shape",
                symbol=symbol,
                exchange=exchange,
                response_type=type(payload).__name__,
            )
            return []
        return payload


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
