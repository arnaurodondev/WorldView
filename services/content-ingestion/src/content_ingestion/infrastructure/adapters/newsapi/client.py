"""HTTP client for the NewsAPI.org API.

API key is sent via ``X-Api-Key`` header (not query param).
Daily quota is tracked in Valkey.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError, QuotaExhaustedError
from content_ingestion.infrastructure.metrics.prometheus import record_fetch_attempt
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import NewsAPIProviderSettings
    from messaging.valkey.client import ValkeyClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


class NewsAPIServerError(Exception):
    """Raised when NewsAPI returns HTTP 200 with ``{"status":"error", ...}``.

    NewsAPI's free tier surfaces quota exhaustion, parameter validation,
    and other upstream issues as HTTP 200 responses with a JSON body of the
    form ``{"status":"error","code":"...","message":"..."}``.  Without an
    explicit check (PLAN-0109 / BP-658) callers parse ``articles`` as an
    empty list and silently advance their watermark.

    Attributes:
        code:    NewsAPI ``code`` field (e.g. ``"rateLimited"``,
                 ``"parameterInvalid"``, ``"maximumResultsReached"``).
        message: Human-readable upstream error message.
    """

    def __init__(self, *, code: str | None, message: str | None) -> None:
        self.code = code
        self.message = message
        super().__init__(f"NewsAPI upstream error: code={code!r} message={message!r}")


class NewsAPIUpgradeRequiredError(AdapterError):
    """Raised when NewsAPI returns HTTP 426 "Upgrade Required".

    The free tier caps results at 100 (page 1 only); requesting page >= 2
    returns HTTP 426. ``fetch_all_pages`` treats a 426 during pagination as
    end-of-pages and keeps the articles collected so far, while a 426 on
    page 1 still propagates (the whole request was rejected).

    Attributes:
        page: The page number that triggered the 426.
    """

    def __init__(self, *, page: int) -> None:
        self.page = page
        super().__init__(f"NewsAPI error: HTTP 426 Upgrade Required (page={page})")


class NewsAPIClient:
    """Low-level HTTP client for the NewsAPI.org endpoint.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        api_key: NewsAPI key (sent in ``X-Api-Key`` header).
        provider_cfg: Operational parameters (base URL, page size, quota TTL).
        valkey: Valkey client for daily quota tracking.
        daily_limit: Maximum requests per day.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str,
        provider_cfg: NewsAPIProviderSettings,
        valkey: ValkeyClient | None = None,
        daily_limit: int = 100,
    ) -> None:
        self._http = http_client
        self._api_key = api_key
        self._base_url = provider_cfg.base_url
        self._page_size = provider_cfg.page_size
        self._quota_ttl_seconds = provider_cfg.quota_ttl_seconds
        self._valkey = valkey
        self._daily_limit = daily_limit

    def _quota_key(self) -> str:
        """Build the Valkey key for today's request counter."""
        import common.time

        today = common.time.utc_now().strftime("%Y-%m-%d")
        return f"newsapi:daily_requests:{today}"

    async def _check_quota(self) -> None:
        """Check and increment the daily quota counter atomically.

        Uses Redis INCR for atomic increment — safe under concurrent access.

        Raises:
            QuotaExhaustedError: If the daily limit has been reached.
        """
        if self._valkey is None:
            return

        key = self._quota_key()
        # Atomic increment — no race condition between get and set
        current = await self._valkey.incr(key)
        # Set TTL on first increment only
        if current == 1:
            await self._valkey.expire(key, self._quota_ttl_seconds)

        if current > self._daily_limit:
            msg = f"NewsAPI daily quota exhausted ({current}/{self._daily_limit})"
            raise QuotaExhaustedError(msg)

    async def fetch_articles(
        self,
        *,
        query: str,
        from_date: str = "",
        language: str = "en",
        page: int = 1,
    ) -> dict[str, Any]:
        """Fetch a single page of articles from NewsAPI.

        Args:
            query: Search query string.
            from_date: Start date ``YYYY-MM-DD``.
            language: Article language filter.
            page: Page number (1-indexed).

        Returns:
            Full API response dict with ``status``, ``totalResults``, ``articles``.

        Raises:
            QuotaExhaustedError: If daily quota is exhausted.
            AdapterError: On HTTP errors.
        """
        await self._check_quota()

        headers = {"X-Api-Key": self._api_key}
        params: dict[str, str | int] = {
            "q": query,
            # "publishedAt" sort requires a paid plan (triggers HTTP 426 on free tier).
            # "relevancy" is available on all tiers.
            "sortBy": "relevancy",
            "language": language,
            "pageSize": self._page_size,
            "page": page,
        }
        if from_date:
            params["from"] = from_date

        # Per-attempt Prometheus instrumentation (BP-174 fix; mirrors the
        # EODHD client). status_label is mutated inside try/except so the
        # finally block records the correct outcome label.
        start = time.monotonic()
        status_label = "success"
        try:
            response = await self._http.get(self._base_url, params=params, headers=headers)

            if response.status_code == 429:
                status_label = "rate_limited"
                msg = "NewsAPI rate limit exceeded (HTTP 429)"
                raise AdapterError(msg)
            if response.status_code == 426:
                # Free tier caps at 100 results (page 1 only). A 426 on
                # page >= 2 is an expected pagination ceiling, not a failure
                # — fetch_all_pages handles it; a 426 on page 1 means the
                # entire request was rejected and must still raise.
                status_label = "page_cap" if page >= 2 else "error"
                raise NewsAPIUpgradeRequiredError(page=page)
            if response.status_code >= 400:
                status_label = "error"
                msg = f"NewsAPI error: HTTP {response.status_code}"
                raise AdapterError(msg)
        except AdapterError:
            raise
        except Exception:
            status_label = "error"
            raise
        finally:
            record_fetch_attempt("newsapi", status_label, time.monotonic() - start)

        data = response.json()
        if not isinstance(data, dict):
            return {"status": "error", "articles": []}

        # NewsAPI free tier surfaces upstream errors (rateLimited,
        # parameterInvalid, maximumResultsReached, etc.) as HTTP 200 with a
        # JSON body of the form ``{"status":"error","code":"...","message":"..."}``.
        # The previous implementation parsed this as ``{"articles": []}`` and
        # let the caller mistake an upstream error for a legitimate
        # "no news today" 200 — silently advancing the watermark (BP-658).
        # Log with structured fields BEFORE raising so the worker's
        # log-correlation pipeline always captures the upstream code.
        if data.get("status") == "error":
            code = data.get("code") if isinstance(data.get("code"), str) else None
            message = data.get("message") if isinstance(data.get("message"), str) else None
            logger.warning(
                "newsapi_upstream_error",
                code=code,
                message=message,
            )
            raise NewsAPIServerError(code=code, message=message)
        return data  # type: ignore[no-any-return]

    async def fetch_all_pages(
        self,
        *,
        query: str,
        from_date: str = "",
        language: str = "en",
    ) -> list[dict[str, Any]]:
        """Paginate through all available articles.

        Stops pagination when no more articles or quota exhausted.
        """
        all_articles: list[dict[str, Any]] = []
        page = 1

        while True:
            try:
                data = await self.fetch_articles(query=query, from_date=from_date, language=language, page=page)
            except QuotaExhaustedError:
                logger.warning("newsapi_quota_exhausted_mid_pagination", page=page)
                break
            except NewsAPIUpgradeRequiredError:
                if page == 1:
                    # 426 on the first page means the whole request was
                    # rejected (e.g. from_date older than the free-tier
                    # window) — propagate as a real failure.
                    raise
                # Free tier caps at 100 results / page 1: page >= 2 returning
                # HTTP 426 is the expected end-of-pages signal. Keep the
                # page-1 articles instead of discarding the whole batch.
                logger.info(
                    "newsapi_free_tier_page_cap",
                    page=page,
                    articles_collected=len(all_articles),
                )
                break

            articles = data.get("articles", [])
            if not isinstance(articles, list) or not articles:
                break

            all_articles.extend(articles)

            total_results = data.get("totalResults", 0)
            if len(all_articles) >= total_results:
                break

            page += 1

        return all_articles
