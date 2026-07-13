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

    from content_ingestion.config import SECEdgarProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class SECEdgarClient:
    """Low-level HTTP client for SEC EDGAR endpoints.

    Args:
        http_client: An ``httpx.AsyncClient`` for making requests.
        user_agent: Required User-Agent header (SEC policy).
        provider_cfg: Operational parameters (URLs, form types, concurrency).

    Raises:
        ConfigurationError: If ``user_agent`` is empty.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        user_agent: str,
        provider_cfg: SECEdgarProviderSettings,
    ) -> None:
        if not user_agent or not user_agent.strip():
            msg = "SEC EDGAR requires a User-Agent header. Set SEC_EDGAR_USER_AGENT."
            raise ConfigurationError(msg)
        self._http = http_client
        self._user_agent = user_agent
        self._efts_url = provider_cfg.efts_url
        self._filing_base_url = provider_cfg.filing_base_url
        self._default_forms = provider_cfg.default_forms
        self._semaphore = asyncio.Semaphore(provider_cfg.max_concurrent)

    async def search_filings(
        self,
        *,
        from_date: str = "",
        to_date: str = "",
        forms: str = "",
        ciks: str = "",
    ) -> list[dict[str, Any]]:
        """Search EFTS for recent filings.

        Args:
            from_date: Start date ``YYYY-MM-DD``.
            to_date: End date ``YYYY-MM-DD``.
            forms: Comma-separated form types.  Defaults to ``default_forms`` from config.
            ciks: Optional comma-separated, zero-padded 10-digit CIK(s) to scope the
                search to specific filers.  When empty, EFTS returns the most-recent
                filings across ALL filers (date-sorted) — which is why a watched
                company (e.g. Apple) is otherwise never ingested: its filings are
                diluted out of the global date-sorted result set.  Passing the
                company's CIK pins the search to that filer (coverage fix, R1 Fix ②).

        Returns:
            List of filing metadata dicts.

        Raises:
            AdapterError: On HTTP errors.
        """
        actual_forms = forms or self._default_forms
        params: dict[str, str] = {
            "forms": actual_forms,
        }
        if from_date and to_date:
            params["dateRange"] = "custom"
            params["startdt"] = from_date
            params["enddt"] = to_date
        # EFTS scopes results to specific filers via the ``ciks`` query param.
        if ciks:
            params["ciks"] = ciks

        headers = {"User-Agent": self._user_agent}

        async with self._semaphore:
            response = await self._http.get(self._efts_url, params=params, headers=headers)

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

    async def fetch_filing_manifest(
        self,
        *,
        cik: str,
        accession_no: str,
    ) -> dict[str, Any]:
        """Fetch the filing's JSON manifest (``index.json``).

        The manifest lists every document in the filing (primary document, XBRL
        instance/linkbases, exhibits, R-viewer files) with ``name``/``type``/``size``.
        We parse it to resolve the *primary* document filename so we can download
        the actual 10-K/10-Q/8-K narrative rather than the ~40-word index page
        (R1 root cause — see docs/audits/2026-07-04-sec-filings-ingestion-storage-gap.md).

        Args:
            cik: Central Index Key (no leading zeros).
            accession_no: Accession number (dashes are stripped for the URL).

        Returns:
            The parsed manifest dict (``{"directory": {"item": [...]}}``), or an
            empty dict if the response is not a JSON object.

        Raises:
            AdapterError: On HTTP errors.
        """
        acc_clean = accession_no.replace("-", "")
        url = f"{self._filing_base_url}/{cik}/{acc_clean}/index.json"
        headers = {"User-Agent": self._user_agent}

        async with self._semaphore:
            response = await self._http.get(url, headers=headers)

        if response.status_code >= 400:
            msg = f"SEC EDGAR manifest fetch error: HTTP {response.status_code} for {url}"
            raise AdapterError(msg)

        data = response.json()
        return data if isinstance(data, dict) else {}

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
        url = f"{self._filing_base_url}/{cik}/{acc_clean}/{filename}"
        headers = {"User-Agent": self._user_agent}

        async with self._semaphore:
            response = await self._http.get(url, headers=headers)

        if response.status_code >= 400:
            msg = f"SEC EDGAR document fetch error: HTTP {response.status_code} for {url}"
            raise AdapterError(msg)

        return bytes(response.content)
