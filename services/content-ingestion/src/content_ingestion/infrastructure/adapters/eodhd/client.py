"""HTTP client for the EODHD News API.

Handles raw HTTP communication, pagination, and error mapping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import EODHDProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class EODHDClient:
    """Low-level HTTP client for the EODHD News endpoint.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        api_key: EODHD API token.
        provider_cfg: Operational parameters (base URL, page size).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str,
        provider_cfg: EODHDProviderSettings,
    ) -> None:
        self._http = http_client
        self._api_key = api_key
        self._base_url = provider_cfg.base_url
        self._page_size = provider_cfg.page_size

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
            "limit": self._page_size,
            "offset": offset,
        }
        if ticker:
            params["s"] = ticker
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        response = await self._http.get(self._base_url, params=params)

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

        Continues fetching while the response length equals ``page_size``.
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

            if len(page) < self._page_size:
                break
            offset += self._page_size

        return all_articles
