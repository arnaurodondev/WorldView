"""HTTP client for the Polymarket Gamma ``/events`` API.

No authentication required — the Gamma API is publicly accessible. Each page
returns up to ``limit`` events and an optional ``next_cursor`` for pagination,
mirroring the ``/markets`` endpoint used by :class:`PolymarketClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import PolymarketEventsProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class GammaEventsPage:
    """Typed result from a single paginated Gamma ``/events`` call.

    Attributes:
        events: Raw event dicts from the ``events`` array in the response.
        next_cursor: Opaque cursor for the next page, or ``None`` if no more pages.
    """

    events: list[dict]
    next_cursor: str | None


class PolymarketEventsClient:
    """Low-level HTTP adapter for the Polymarket Gamma ``/events`` endpoint.

    Stateless — receives an ``httpx.AsyncClient`` and provider settings as
    dependencies. No database interaction.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, page size, etc.).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: PolymarketEventsProviderSettings,
    ) -> None:
        self._http = http_client
        self._settings = settings

    async def fetch_events_page(
        self,
        *,
        limit: int = 500,
        next_cursor: str | None = None,
    ) -> GammaEventsPage:
        """Fetch one page of active Polymarket events.

        Args:
            limit: Maximum number of events per page (1-1000).
            next_cursor: Opaque pagination cursor from a prior response.

        Returns:
            :class:`GammaEventsPage` with the parsed events and optional cursor.

        Raises:
            AdapterError: On any non-200 HTTP status (429 included — the worker
                treats ``AdapterError`` as retryable).
        """
        params: dict[str, str | int] = {"active": "true", "limit": limit}
        if next_cursor is not None:
            params["next_cursor"] = next_cursor

        try:
            resp = await self._http.get(
                self._settings.base_url,
                params=params,
                timeout=30.0,
            )
        except Exception as exc:
            raise AdapterError(f"Gamma events API request failed: {exc}") from exc

        if resp.status_code != 200:
            raise AdapterError(f"Gamma events API HTTP {resp.status_code}", status_code=resp.status_code)

        data = resp.json()
        # Guard against a non-list body: a malformed / unexpected response (e.g. a
        # bare string, number, or error object) must yield an empty page rather
        # than propagating a non-iterable into ``_process_event`` and failing the
        # whole task. Only a genuine list of event dicts is accepted.
        raw_events = data.get("events", []) if isinstance(data, dict) else data
        events: list[dict] = [e for e in raw_events if isinstance(e, dict)] if isinstance(raw_events, list) else []
        cursor: str | None = data.get("next_cursor") if isinstance(data, dict) else None

        logger.debug(
            "gamma_events_page_fetched",
            event_count=len(events),
            has_next=cursor is not None,
        )
        return GammaEventsPage(events=events, next_cursor=cursor)
