"""HTTP client for the Finnhub API (news + transcripts).

Handles raw HTTP communication, rate limiting on 429, and error mapping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import FinnhubProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class RateLimitError(AdapterError):
    """Raised when Finnhub returns HTTP 429.

    Attributes:
        sleep_secs: Recommended seconds to wait before retrying.
    """

    def __init__(self, sleep_secs: float) -> None:
        self.sleep_secs = sleep_secs
        super().__init__(f"Finnhub rate limited, retry after {sleep_secs:.1f}s")


class PremiumEndpointError(AdapterError):
    """Raised when Finnhub returns HTTP 403 — the API key tier lacks access.

    F-104 fix (2026-04-30): the transcripts endpoint is paid; on the free
    tier every call returns 403. The previous code raised a generic
    ``AdapterError`` and the retry loop happily burned 3 attempts x backoff
    on every symbol every cycle (~56 s wasted per cycle). 403 is a
    permanent contract failure, not a transient one — we surface it with
    its own type so the caller can distinguish "not licensed" from
    "transient" and skip silently instead of retrying.
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        super().__init__(
            f"Finnhub endpoint '{endpoint}' returned 403 — premium endpoint "
            f"requires a paid Finnhub plan; skipping (no retry).",
        )


class FinnhubClient:
    """Low-level HTTP client for Finnhub endpoints.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        api_key: Finnhub API token.
        provider_cfg: Operational parameters (base URL).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str,
        provider_cfg: FinnhubProviderSettings,
    ) -> None:
        self._http = http_client
        self._api_key = api_key
        self._base_url = provider_cfg.base_url

    async def fetch_company_news(
        self,
        *,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """Fetch company news for a symbol within a date range.

        Args:
            symbol: Ticker symbol (e.g. ``"AAPL"``).
            from_date: Start date ``YYYY-MM-DD``.
            to_date: End date ``YYYY-MM-DD``.

        Returns:
            List of news article dicts.

        Raises:
            RateLimitError: On HTTP 429 with calculated wait time.
            AdapterError: On other HTTP errors.
        """
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }

        response = await self._http.get(f"{self._base_url}/company-news", params=params)
        self._check_response(response)

        data = response.json()
        if not isinstance(data, list):
            return []
        return data  # type: ignore[no-any-return]

    async def fetch_transcript_list(self, *, symbol: str) -> list[dict[str, Any]]:
        """Fetch the list of available earnings call transcripts.

        Args:
            symbol: Ticker symbol.

        Returns:
            List of transcript metadata dicts.
        """
        params = {"symbol": symbol, "token": self._api_key}
        response = await self._http.get(f"{self._base_url}/stock/transcripts/list", params=params)
        self._check_response(response)

        data = response.json()
        transcripts = data.get("transcripts", [])
        if not isinstance(transcripts, list):
            return []
        return transcripts  # type: ignore[no-any-return]

    async def fetch_transcript(self, *, transcript_id: str) -> dict[str, Any]:
        """Fetch a single earnings call transcript by ID.

        Args:
            transcript_id: Transcript identifier.

        Returns:
            Transcript dict with content.
        """
        params = {"id": transcript_id, "token": self._api_key}
        response = await self._http.get(f"{self._base_url}/stock/transcripts", params=params)
        self._check_response(response)

        data = response.json()
        if not isinstance(data, dict):
            return {}
        return data  # type: ignore[no-any-return]

    def _check_response(self, response: httpx.Response) -> None:
        """Check HTTP response for errors.

        Raises:
            RateLimitError: On 429 with wait time to next minute boundary.
            PremiumEndpointError: On 403 — endpoint requires a paid plan.
            AdapterError: On other error status codes.
        """
        if response.status_code == 429:
            from datetime import UTC, datetime

            now = datetime.now(tz=UTC)
            sleep_secs = max(1.0, 60.0 - now.second)
            raise RateLimitError(sleep_secs=sleep_secs)
        # F-104 fix: 403 is a permanent licensing failure, not transient —
        # raise a distinct exception so the retry loop can short-circuit
        # rather than burning 3 attempts x backoff on every symbol.
        if response.status_code == 403:
            # The URL path is the most useful identifier for which endpoint
            # was rejected. Keep it short — full URL leaks the api_key query
            # param into logs.
            endpoint = response.request.url.path if response.request else "<unknown>"
            raise PremiumEndpointError(endpoint=endpoint)
        if response.status_code >= 400:
            msg = f"Finnhub API error: HTTP {response.status_code}"
            raise AdapterError(msg)
