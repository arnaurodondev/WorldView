"""EodhDClient — lightweight EODHD API client for S7 enrichment workers.

Covers the endpoints used by Workers 13D-6, 13D-7, and 13D-8:
- ``GET /economic-events``   — macro economic event calendar
- ``GET /macro-indicator``   — World Bank country macro indicators
- ``GET /insider-transactions`` — SEC Form 4 insider transaction filings

All HTTP errors are logged and surfaced as empty lists/None so callers
can treat them as "no data available, retry next cycle" without crashing.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)  # type: ignore[no-any-return]


class EodhDClient:
    """Thin async HTTP client for the EODHD API.

    Args:
        api_key:  EODHD API token (``api_token`` query parameter).
        http:     Injected ``httpx.AsyncClient`` (allows test injection).
        base_url: Override API base URL (default: ``https://eodhd.com/api``).
    """

    def __init__(
        self,
        api_key: str,
        http: httpx.AsyncClient,
        base_url: str = "https://eodhd.com/api",
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._base_url = base_url.rstrip("/")

    # ── Worker 13D-6 ─────────────────────────────────────────────────────────

    async def get_economic_events(
        self,
        country: str,
        from_date: date,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch economic events for *country* from *from_date*.

        Endpoint: ``GET /economic-events?country={iso2}&from={from_date}&to={to_date}&fmt=json``

        Returns the raw list of event dicts from the API.  On HTTP error or
        network failure, logs a warning and returns an empty list so the
        caller can proceed to the next country without crashing.

        Each dict typically contains:
        - ``date``             — ISO-8601 event date string
        - ``type``             — event name (e.g. "CPI m/m")
        - ``period``           — reporting period (e.g. "Mar 2026")
        - ``actual``           — released value (``null`` if not yet published)
        - ``estimate``         — analyst consensus estimate (``null`` if unavailable)
        - ``previous``         — prior period value
        - ``change_percentage``— % change from previous (``null`` if unavailable)
        - ``country``          — ISO-2 country code

        Args:
            country:   ISO-3166 alpha-2 country code (e.g. ``"US"``, ``"DE"``).
            from_date: Inclusive start date for the event calendar.
            to_date:   Inclusive end date; defaults to *from_date* + 1 day.
        """
        from datetime import timedelta

        if to_date is None:
            to_date = from_date + timedelta(days=1)

        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "country": country,
            "from": str(from_date),
            "to": str(to_date),
        }
        return await self._get_list(f"{self._base_url}/economic-events", params, context=f"economic_events/{country}")

    # ── Worker 13D-7 ─────────────────────────────────────────────────────────

    async def get_macro_indicator(
        self,
        iso3_country: str,
        indicator_code: str,
    ) -> list[dict[str, Any]]:
        """Fetch World Bank macro indicator values for a country.

        Endpoint: ``GET /macro-indicator/{ISO3_COUNTRY}?indicator={code}&fmt=json``

        Results are sorted by date descending — index 0 is the most recent.

        Args:
            iso3_country:   ISO 3166-1 alpha-3 country code (e.g. ``"USA"``).
            indicator_code: World Bank indicator code (e.g. ``"gdp_current_usd"``).
        """
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "indicator": indicator_code,
        }
        return await self._get_list(
            f"{self._base_url}/macro-indicator/{iso3_country}",
            params,
            context=f"macro_indicator/{iso3_country}/{indicator_code}",
        )

    # ── Worker 13D-8 ─────────────────────────────────────────────────────────

    async def get_insider_transactions(
        self,
        code: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch SEC Form 4 insider transactions for a ticker.

        Endpoint: ``GET /insider-transactions?code={ticker}.US&limit={n}&fmt=json``

        Args:
            code:  Ticker code including exchange suffix (e.g. ``"AAPL.US"``).
            limit: Maximum number of transactions to return.
        """
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "code": code,
            "limit": limit,
        }
        return await self._get_list(
            f"{self._base_url}/insider-transactions",
            params,
            context=f"insider_transactions/{code}",
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _get_list(
        self,
        url: str,
        params: dict[str, Any],
        context: str,
    ) -> list[dict[str, Any]]:
        """Shared GET helper — returns list or empty list on error."""
        try:
            resp = await self._http.get(url, params=params)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "eodhd_client_network_error",
                context=context,
                error=str(exc),
            )
            return []

        if resp.status_code == 401:
            logger.error(  # type: ignore[no-any-return]
                "eodhd_client_auth_error",
                context=context,
                status_code=resp.status_code,
            )
            return []

        if resp.status_code != 200:
            logger.warning(  # type: ignore[no-any-return]
                "eodhd_client_http_error",
                context=context,
                status_code=resp.status_code,
            )
            return []

        try:
            data: list[dict[str, Any]] = resp.json()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "eodhd_client_json_error",
                context=context,
                error=str(exc),
            )
            return []

        if not isinstance(data, list):
            logger.warning(  # type: ignore[no-any-return]
                "eodhd_client_unexpected_shape",
                context=context,
                type=type(data).__name__,
            )
            return []

        return data
