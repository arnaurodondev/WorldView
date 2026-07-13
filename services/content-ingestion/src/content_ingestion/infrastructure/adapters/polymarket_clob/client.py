"""HTTP client for the Polymarket CLOB ``/prices-history`` API.

No authentication required. Returns a token's price time-series as
``{"history": [{"t": <epoch_s>, "p": <price>}, ...]}``. Resolved markets often
have no 1-hour series, so the *adapter* retries at a coarser interval on an
HTTP 400 or an empty series (PRD-0033 §4.4/§9.2) — this client simply surfaces
the status via :class:`AdapterError.status_code`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import PolymarketClobProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class PolymarketClobHistoryClient:
    """Low-level HTTP adapter for the Polymarket CLOB ``/prices-history`` endpoint.

    Stateless — receives an ``httpx.AsyncClient`` and provider settings as
    dependencies. No database interaction.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, fidelity, intervals, etc.).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: PolymarketClobProviderSettings,
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def fetch_price_history(
        self,
        *,
        token_id: str,
        interval: str,
        start_ts: int | None = None,
        fidelity: int | None = None,
    ) -> dict:
        """Fetch the raw price-history response for one CLOB token.

        Args:
            token_id: The CLOB market token id (the ``market`` query param).
            interval: Requested resolution, e.g. ``"1h"`` or ``"1d"``.
            start_ts: Optional Unix epoch-seconds lower bound (``startTs``).
            fidelity: Optional resolution in minutes (``fidelity``).

        Returns:
            The raw JSON dict (``{"history": [...]}``).

        Raises:
            AdapterError: On any non-200 HTTP status. ``status_code`` is set so
                the adapter can branch on HTTP 400 for the resolved-market
                fallback. 429 is included and treated as retryable by the worker.
        """
        params: dict[str, str | int] = {"market": token_id, "interval": interval}
        if start_ts is not None:
            params["startTs"] = start_ts
        if fidelity is not None:
            params["fidelity"] = fidelity

        try:
            resp = await self._http.get(
                self._settings.base_url,
                params=params,
                timeout=30.0,
            )
        except Exception as exc:
            raise AdapterError(f"CLOB prices-history request failed: {exc}") from exc

        if resp.status_code != 200:
            raise AdapterError(
                f"CLOB prices-history HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        data = resp.json()
        history_len = len(data.get("history", [])) if isinstance(data, dict) else 0
        logger.debug(
            "clob_prices_history_fetched",
            token_id=token_id,
            interval=interval,
            point_count=history_len,
        )
        return data if isinstance(data, dict) else {"history": data}
