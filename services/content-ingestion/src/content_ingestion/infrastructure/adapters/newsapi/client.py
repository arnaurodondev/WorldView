"""HTTP client for the NewsAPI.org API.

API key is sent via ``X-Api-Key`` header (not query param).
Daily quota is tracked in Valkey.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError, QuotaExhaustedError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from messaging.valkey.client import ValkeyClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BASE_URL = "https://newsapi.org/v2/everything"
_PAGE_SIZE = 100
_QUOTA_TTL_SECONDS = 86400


class NewsAPIClient:
    """Low-level HTTP client for the NewsAPI.org endpoint.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        api_key: NewsAPI key (sent in ``X-Api-Key`` header).
        valkey: Valkey client for daily quota tracking.
        daily_limit: Maximum requests per day.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str,
        valkey: ValkeyClient | None = None,
        daily_limit: int = 100,
    ) -> None:
        self._http = http_client
        self._api_key = api_key
        self._valkey = valkey
        self._daily_limit = daily_limit

    def _quota_key(self) -> str:
        """Build the Valkey key for today's request counter."""
        import common.time

        today = common.time.utc_now().strftime("%Y-%m-%d")
        return f"newsapi:daily_requests:{today}"

    async def _check_quota(self) -> None:
        """Check and increment the daily quota counter.

        Raises:
            QuotaExhaustedError: If the daily limit has been reached.
        """
        if self._valkey is None:
            return

        key = self._quota_key()
        raw = await self._valkey.get(key)
        current = int(raw) if raw else 0

        if current >= self._daily_limit:
            msg = f"NewsAPI daily quota exhausted ({current}/{self._daily_limit})"
            raise QuotaExhaustedError(msg)

        await self._valkey.set(key, str(current + 1), ttl=_QUOTA_TTL_SECONDS)

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
            "sortBy": "publishedAt",
            "language": language,
            "pageSize": _PAGE_SIZE,
            "page": page,
        }
        if from_date:
            params["from"] = from_date

        response = await self._http.get(_BASE_URL, params=params, headers=headers)

        if response.status_code == 429:
            msg = "NewsAPI rate limit exceeded (HTTP 429)"
            raise AdapterError(msg)
        if response.status_code >= 400:
            msg = f"NewsAPI error: HTTP {response.status_code}"
            raise AdapterError(msg)

        data = response.json()
        if not isinstance(data, dict):
            return {"status": "error", "articles": []}
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

            articles = data.get("articles", [])
            if not isinstance(articles, list) or not articles:
                break

            all_articles.extend(articles)

            total_results = data.get("totalResults", 0)
            if len(all_articles) >= total_results:
                break

            page += 1

        return all_articles
