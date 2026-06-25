"""HTTP client for the EODHD News API.

Handles raw HTTP communication, pagination, and error mapping.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.metrics.prometheus import record_fetch_attempt
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
        # Store the full provider config so fetch_all_pages() can read
        # max_pages_per_cycle without hardcoding it here (rule: no hardcoded values).
        self._provider_cfg = provider_cfg

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

        # Per-attempt Prometheus instrumentation (BP-174: dashboard panels
        # were "No data" because s4_fetches_total had no live call sites).
        # We time the HTTP call and label the outcome (success/error/rate_limited)
        # in a try/finally so duration is always observed even on exception.
        start = time.monotonic()
        status_label = "success"
        try:
            response = await self._http.get(self._base_url, params=params)

            if response.status_code == 429:
                status_label = "rate_limited"
                msg = "EODHD rate limit exceeded (HTTP 429)"
                raise AdapterError(msg)
            if response.status_code >= 400:
                status_label = "error"
                msg = f"EODHD API error: HTTP {response.status_code}"
                raise AdapterError(msg)
        except AdapterError:
            raise
        except Exception:
            # Network / timeout / DNS — counts as error attempt.
            status_label = "error"
            raise
        finally:
            record_fetch_attempt("eodhd", status_label, time.monotonic() - start)

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
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate through news articles up to a maximum page count (OPT-3).

        Continues fetching while the response length equals ``page_size`` AND
        the number of pages fetched is below ``max_pages``.  When the limit is
        reached the method logs a warning so the truncation is visible in prod.

        Args:
            ticker: Symbol filter (e.g. ``"AAPL.US"``).  Empty for general news.
            from_date: Start date ``YYYY-MM-DD``.
            to_date: End date ``YYYY-MM-DD``.
            max_pages: Override the per-cycle page cap.  When ``None`` (the
                default) the value from ``provider_cfg.max_pages_per_cycle``
                is used — never a hardcoded constant.
        """
        # Resolve the effective page cap: caller override takes precedence,
        # otherwise fall back to the value from provider config (config.py).
        limit = max_pages if max_pages is not None else self._provider_cfg.max_pages_per_cycle

        all_articles: list[dict[str, Any]] = []
        offset = 0
        page_count = 0

        while True:
            page = await self.fetch_news(
                ticker=ticker,
                from_date=from_date,
                to_date=to_date,
                offset=offset,
            )
            all_articles.extend(page)
            page_count += 1

            # Normal termination: API returned a partial page — no more data.
            if len(page) < self._page_size:
                break

            # OPT-3: Safety cap — stop before consuming more API credits.
            if page_count >= limit:
                logger.warning(
                    "eodhd_fetch_truncated",
                    ticker=ticker,
                    page_count=page_count,
                    max_pages=limit,
                    articles_fetched=len(all_articles),
                    message=(
                        "fetch_all_pages stopped at the page cap; some articles may have been skipped this cycle."
                    ),
                )
                break

            offset += self._page_size

        return all_articles
