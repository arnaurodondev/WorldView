"""HTTP client for the EODHD News API.

Handles raw HTTP communication, pagination, and error mapping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BASE_URL = "https://eodhd.com/api/news"
_PAGE_SIZE = 100


class EODHDClient:
    """Low-level HTTP client for the EODHD News endpoint.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        api_key: EODHD API token.
    """

    def __init__(self, http_client: httpx.AsyncClient, api_key: str) -> None:
        self._http = http_client
        self._api_key = api_key

    async def fetch_news(
        self,
        *,
        ticker: str = "",
        from_date: str = "",
        to_date: str = "",
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of news articles.

        Args:
            ticker: Symbol filter (e.g. ``"AAPL.US"``).  Empty for general news.
            from_date: Start date ``YYYY-MM-DD``.
            to_date: End date ``YYYY-MM-DD``.
            offset: Pagination offset.

        Returns:
            List of article dicts from the API response.

        Raises:
            AdapterError: On HTTP 4xx/5xx.
        """
        params: dict[str, str | int] = {
            "api_token": self._api_key,
            "fmt": "json",
            "limit": _PAGE_SIZE,
            "offset": offset,
        }
        if ticker:
            params["s"] = ticker
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        response = await self._http.get(_BASE_URL, params=params)

        if response.status_code == 429:
            msg = "EODHD rate limit exceeded (HTTP 429)"
            raise AdapterError(msg)
        if response.status_code >= 400:
            msg = f"EODHD API error: HTTP {response.status_code}"
            raise AdapterError(msg)

        data = response.json()
        if not isinstance(data, list):
            return []
        return data  # type: ignore[no-any-return]

    async def fetch_all_pages(
        self,
        *,
        ticker: str = "",
        from_date: str = "",
        to_date: str = "",
    ) -> list[dict[str, Any]]:
        """Paginate through all available news articles.

        Continues fetching while the response length equals ``_PAGE_SIZE``.
        """
        all_articles: list[dict[str, Any]] = []
        offset = 0

        while True:
            page = await self.fetch_news(
                ticker=ticker,
                from_date=from_date,
                to_date=to_date,
                offset=offset,
            )
            all_articles.extend(page)

            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return all_articles
