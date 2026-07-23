"""HTTP client for the Polymarket Gamma ``/events`` API.

No authentication required — the Gamma API is publicly accessible.

Pagination (verified live, 2026-07-16): the Gamma list endpoints paginate via
``offset``/``limit`` query params and return a **bare JSON array** of event
objects (there is NO response-body ``next_cursor`` field). The Gamma API
silently caps its page size at ~100 rows regardless of the requested
``limit`` (limit=500 → 100 rows observed live), so a page shorter than
``limit`` is the norm, NOT a signal of end-of-data — only an EMPTY page means
the walk is done. (An earlier revision of this client used the disproven
``len(items) < limit`` heuristic; it under-fetched the event universe after
~100 rows and was fixed the same night — see
``docs/audits/2026-07-23-bottleneck-content-ingestion-pagination.md``.)

To preserve the adapter's cursor-loop contract without leaking offset arithmetic
into the adapter, this client keeps the ``next_cursor`` parameter/field names but
treats the cursor as an **opaque synthetic string == the next offset**:

* ``next_cursor is None``  → start at offset 0 (first page).
* ``next_cursor == "500"`` → start at offset 500 (second page, page_size 500).
* returned ``next_cursor``  → derived via the shared
  :func:`~content_ingestion.infrastructure.adapters._pagination.next_offset_cursor`
  helper: ``str(offset + <actual returned count>)`` when the page was
  non-empty, or ``None`` when the page was empty (done). Advancing by the
  actual count (not ``limit``) ensures no rows are skipped when the provider
  under-fills a page.

The adapter loops until ``next_cursor is None`` or ``max_pages_per_cycle`` is hit,
so long-tail-but-active event groups (2028 Presidential, GTA VI, WC 2026, …) are
fetched instead of only the first 500 events — those member markets no longer keep
``event_id = NULL``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters._pagination import next_offset_cursor
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from content_ingestion.config import PolymarketEventsProviderSettings

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class GammaEventsPage:
    """Typed result from a single paginated Gamma ``/events`` call.

    Attributes:
        events: Raw event dicts from the response array.
        next_cursor: Synthetic opaque cursor (the next ``offset`` as a string) when
            more pages may remain, or ``None`` when this was the last page.
    """

    events: list[dict]
    next_cursor: str | None


def _cursor_to_offset(next_cursor: str | None) -> int:
    """Decode the opaque synthetic cursor into an integer offset.

    A missing/invalid cursor is treated as offset 0 (start of the list) so a
    malformed cursor can never silently skip the head of the universe.
    """
    if next_cursor is None:
        return 0
    try:
        offset = int(next_cursor)
    except (TypeError, ValueError):
        return 0
    return offset if offset >= 0 else 0


def _extract_items(data: object, *, key: str) -> list[dict]:
    """Normalise a Gamma response body into a list of dicts.

    The live Gamma API returns a bare JSON array, but we defensively also accept
    an object wrapping the array under ``key`` or ``data``. Any non-list / non-dict
    body yields an empty list so a malformed response can never crash the loop.
    """
    if isinstance(data, list):
        raw: list = data
    elif isinstance(data, dict):
        candidate = data.get(key)
        if not isinstance(candidate, list):
            candidate = data.get("data")
        raw = candidate if isinstance(candidate, list) else []
    else:
        raw = []
    return [item for item in raw if isinstance(item, dict)]


class PolymarketEventsClient:
    """Low-level HTTP adapter for the Polymarket Gamma ``/events`` endpoint.

    Stateless — receives an ``httpx.AsyncClient`` and provider settings as
    dependencies. No database interaction.

    Args:
        http_client: Shared async HTTP client (injected by the worker).
        settings: Provider configuration (base URL, page size, sort order, etc.).
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
        """Fetch one page of active Polymarket events via offset pagination.

        Args:
            limit: Maximum number of events per page (1-1000).
            next_cursor: Opaque synthetic cursor from a prior page (the next
                ``offset`` encoded as a string). ``None`` starts at offset 0.

        Returns:
            :class:`GammaEventsPage` with the parsed events and the synthetic next
            cursor (``None`` once the last page is reached).

        Raises:
            AdapterError: On any non-200 HTTP status (429 included — the worker
                treats ``AdapterError`` as retryable).
        """
        offset = _cursor_to_offset(next_cursor)

        # ``active=true`` + ``closed=false`` restrict to live, tradeable event
        # groups. ``order``/``ascending`` give a stable sort so offset paging is
        # deterministic and (when ordered by volume) high-value groups are fetched
        # first under the ``max_pages_per_cycle`` bound.
        params: dict[str, str | int] = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        }
        order = getattr(self._settings, "order", "") or ""
        if order:
            params["order"] = order
            params["ascending"] = "true" if getattr(self._settings, "ascending", False) else "false"

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

        events = _extract_items(resp.json(), key="events")

        # Delegate to the shared termination rule: advance by the ACTUAL
        # returned count, terminate only on an empty page. See module
        # docstring + _pagination.next_offset_cursor for why.
        next_offset: str | None = next_offset_cursor(offset=offset, returned_count=len(events))

        logger.debug(
            "gamma_events_page_fetched",
            offset=offset,
            event_count=len(events),
            has_next=next_offset is not None,
        )
        return GammaEventsPage(events=events, next_cursor=next_offset)
