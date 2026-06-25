"""HTTP client for S6 NLP-pipeline news-signal endpoints (PLAN-0113 W2 — NEW).

No S6 client existed before the rule engine. This adapter backs the
news-count and news-momentum poll evaluators with two read-only sources:

  - ``GET /internal/v1/instruments/{id}/news-rollup-7d`` → ``news_count_7d``
    (the 7-day article count; used for the ``window="7d"`` NEWS_COUNT case).
  - ``GET /api/v1/news/trending-entities?window_hours=`` → per-entity ``count``
    and ``delta_pct`` for the 24/72/168-hour windows (NEWS_COUNT short windows
    + NEWS_MOMENTUM).

R9: cross-service access via REST only. R25: implements ``IS6NewsClient`` ABC.
Best-effort: every method returns ``None`` on any transport/HTTP error so the
poller treats a flaky S6 as "no observation" (no state change). BP-235: every
call sets an explicit ``httpx.Timeout`` and is wrapped in ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError, Timeout

from alert.application.ports.signal_clients import IS6NewsClient

if TYPE_CHECKING:
    from alert.config import Settings

logger = structlog.get_logger(__name__)

# BP-235: wedged S6 must not hang the poller cycle.
_S6_TIMEOUT_S = 10.0
# The trending endpoint snaps to these windows; sending anything else silently
# falls back to 24h server-side, so we constrain here too (matches the
# NEWS_MOMENTUM_WINDOW_HOURS allow-list in domain/rule_conditions.py).
_TRENDING_WINDOWS: frozenset[int] = frozenset({24, 72, 168})


class S6NewsClient(IS6NewsClient):
    """Async HTTP client for S6 NLP-pipeline news-signal endpoints."""

    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        self._base_url = settings.s6_nlp_base_url.rstrip("/")
        # PRD-0025: S6 internal endpoints require X-Internal-JWT.
        self._jwt = settings.s6_internal_jwt
        self._client = client or AsyncClient(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-JWT": self._jwt} if self._jwt else {}

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        """GET → parsed JSON, or None on any failure (best-effort)."""
        try:
            resp = await asyncio.wait_for(
                self._client.get(
                    url,
                    params=params or {},
                    headers=self._headers(),
                    timeout=Timeout(_S6_TIMEOUT_S),
                ),
                timeout=_S6_TIMEOUT_S + 1.0,
            )
            resp.raise_for_status()
            return resp.json()
        except (RequestError, HTTPStatusError, TimeoutError) as exc:
            logger.warning("s6_client_request_failed", url=url, error=str(exc))
            return None

    async def get_news_count_7d(self, instrument_id: UUID) -> int | None:
        """GET /internal/v1/instruments/{id}/news-rollup-7d → ``news_count_7d``."""
        url = f"{self._base_url}/internal/v1/instruments/{instrument_id}/news-rollup-7d"
        data = await self._get_json(url)
        if not isinstance(data, dict):
            return None
        raw = data.get("news_count_7d")
        try:
            return int(raw) if raw is not None else None
        except (ValueError, TypeError):
            return None

    async def get_trending_count(self, entity_id: UUID, window_hours: int) -> int | None:
        """Trending article ``count`` for an entity in a window, or None if absent."""
        entry = await self._find_trending_entity(entity_id, window_hours)
        if entry is None:
            # The entity is simply not in the trending feed for this window →
            # zero recent articles. Return 0 (a real observation) so a NEWS_COUNT
            # rule can re-arm below threshold, rather than None (skip).
            return 0
        raw = entry.get("count")
        try:
            return int(raw) if raw is not None else 0
        except (ValueError, TypeError):
            return 0

    async def get_trending_momentum(self, entity_id: UUID, window_hours: int) -> tuple[float, int] | None:
        """``(delta_pct, count)`` for an entity in a window, or None if absent.

        Unlike ``get_trending_count``, momentum returns None (skip — no state
        change) when the entity is absent: a non-trending entity has no
        meaningful ``delta_pct`` to compare against the threshold.
        """
        entry = await self._find_trending_entity(entity_id, window_hours)
        if entry is None:
            return None
        try:
            delta_pct = float(entry["delta_pct"])
            count = int(entry["count"])
        except (KeyError, ValueError, TypeError):
            return None
        return delta_pct, count

    async def _find_trending_entity(self, entity_id: UUID, window_hours: int) -> dict[str, Any] | None:
        """Fetch the trending feed for a window and return the matching entry.

        Returns ``None`` both on request failure AND when the entity is not in
        the feed; callers distinguish the two cases by their own semantics
        (count rules re-arm on absence, momentum rules skip).
        """
        window = window_hours if window_hours in _TRENDING_WINDOWS else 24
        url = f"{self._base_url}/api/v1/news/trending-entities"
        # limit=100 is the endpoint cap — maximise the chance the target entity
        # is present without paging (the feed is small).
        data = await self._get_json(url, params={"window_hours": window, "limit": 100})
        if not isinstance(data, dict):
            return None
        target = str(entity_id)
        for entry in data.get("entities", []):
            if str(entry.get("entity_id")) == target:
                return entry  # type: ignore[no-any-return]
        return None
