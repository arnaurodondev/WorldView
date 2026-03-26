"""HTTP client for the SEC EDGAR EFTS full-text search API.

Handles raw HTTP communication, User-Agent enforcement, and error mapping.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from content_ingestion.domain.exceptions import AdapterError, ConfigurationError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_FILING_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
_DEFAULT_FORMS = "10-K,10-Q,8-K,DEF14A"
_MAX_CONCURRENT = 8


class SECEdgarClient:
    """Low-level HTTP client for SEC EDGAR endpoints.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        user_agent: Required User-Agent header (SEC policy).

    Raises:
        ConfigurationError: If ``user_agent`` is empty.
    """

    def __init__(self, http_client: httpx.AsyncClient, user_agent: str) -> None:
        if not user_agent or not user_agent.strip():
            msg = "SEC EDGAR requires a User-Agent header. Set SEC_EDGAR_USER_AGENT."
            raise ConfigurationError(msg)
        self._http = http_client
        self._user_agent = user_agent
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    async def search_filings(
        self,
        *,
        from_date: str = "",
        to_date: str = "",
        forms: str = _DEFAULT_FORMS,
    ) -> list[dict[str, Any]]:
        """Search EFTS for recent filings.

        Args:
            from_date: Start date ``YYYY-MM-DD``.
            to_date: End date ``YYYY-MM-DD``.
            forms: Comma-separated form types.

        Returns:
            List of filing metadata dicts.

        Raises:
            AdapterError: On HTTP errors.
        """
        params: dict[str, str] = {
            "forms": forms,
        }
        if from_date and to_date:
            params["dateRange"] = "custom"
            params["startdt"] = from_date
            params["enddt"] = to_date

        headers = {"User-Agent": self._user_agent}

        async with self._semaphore:
            response = await self._http.get(_EFTS_URL, params=params, headers=headers)

        if response.status_code == 429:
            msg = "SEC EDGAR rate limit exceeded (HTTP 429)"
            raise AdapterError(msg)
        if response.status_code >= 400:
            msg = f"SEC EDGAR API error: HTTP {response.status_code}"
            raise AdapterError(msg)

        data = response.json()
        hits = data.get("hits", {}).get("hits", [])
        if not isinstance(hits, list):
            return []
        return hits  # type: ignore[no-any-return]

    async def fetch_filing_document(
        self,
        *,
        cik: str,
        accession_no: str,
        filename: str,
    ) -> bytes:
        """Fetch a single filing document (HTML, XBRL, etc.).

        Args:
            cik: Central Index Key.
            accession_no: Accession number (without dashes for URL).
            filename: Filing document filename.

        Returns:
            Raw document bytes.

        Raises:
            AdapterError: On HTTP errors.
        """
        acc_clean = accession_no.replace("-", "")
        url = f"{_FILING_BASE_URL}/{cik}/{acc_clean}/{filename}"
        headers = {"User-Agent": self._user_agent}

        async with self._semaphore:
            response = await self._http.get(url, headers=headers)

        if response.status_code >= 400:
            msg = f"SEC EDGAR document fetch error: HTTP {response.status_code} for {url}"
            raise AdapterError(msg)

        return bytes(response.content)
