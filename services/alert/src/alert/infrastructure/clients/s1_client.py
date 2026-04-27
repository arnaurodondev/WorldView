"""httpx-based client for S1 Portfolio internal endpoints.

Best-effort: if S1 is unreachable or returns an error, methods return
empty results and never raise.  This follows the deployment gate contract
(PRD §12.1 — S10 degrades gracefully when S1 is unavailable).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError

if TYPE_CHECKING:
    from alert.config import Settings

logger = structlog.get_logger(__name__)


class WatcherInfo:
    """Lightweight DTO returned by S1 internal watchlist endpoints."""

    __slots__ = ("alert_types", "user_id", "watchlist_id")

    def __init__(self, user_id: str, watchlist_id: str, alert_types: list[str] | None = None) -> None:
        self.user_id = user_id
        self.watchlist_id = watchlist_id
        self.alert_types = alert_types or []


class S1Client:
    """Async HTTP client for S1 Portfolio internal API.

    All public methods are *best-effort*: on any transport or HTTP error they
    log a warning and return an empty result rather than raising.
    """

    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        self._base_url = settings.s1_portfolio_base_url.rstrip("/")
        # PRD-0025: S1 Portfolio requires RS256 X-Internal-JWT. Set ALERT_S1_INTERNAL_JWT.
        self._jwt = settings.s1_internal_jwt
        self._client = client or AsyncClient(timeout=5.0)

    async def close(self) -> None:
        await self._client.aclose()

    # ----- public API -----

    async def get_watchers_by_entity(self, entity_id: str) -> tuple[list[WatcherInfo], bool]:
        """GET /internal/v1/watchlists/by-entity/{entity_id} → (watchers, success).

        Returns
        -------
            A 2-tuple ``(watchers, ok)`` where ``ok`` is ``True`` when the
            request succeeded (even if the entity has no watchers) and
            ``False`` on any network or HTTP error.

        """
        url = f"{self._base_url}/internal/v1/watchlists/by-entity/{entity_id}"
        data = await self._get_json(url)
        if data is None:
            return [], False
        return [
            WatcherInfo(
                user_id=w["user_id"],
                watchlist_id=w["watchlist_id"],
                alert_types=w.get("alert_types", []),
            )
            for w in data.get("watchers", [])
        ], True

    async def get_watchers_by_entities(self, entity_ids: list[str]) -> dict[str, list[WatcherInfo]]:
        """POST /internal/v1/watchlists/by-entities → {entity_id: [watchers]}."""
        url = f"{self._base_url}/internal/v1/watchlists/by-entities"
        data = await self._post_json(url, json_body={"entity_ids": entity_ids})
        if data is None:
            return {}
        result: dict[str, list[WatcherInfo]] = {}
        for eid, watchers in data.get("results", {}).items():
            result[eid] = [
                WatcherInfo(
                    user_id=w["user_id"],
                    watchlist_id=w["watchlist_id"],
                    alert_types=w.get("alert_types", []),
                )
                for w in watchers
            ]
        return result

    async def get_user_email(self, user_id: str) -> str | None:
        """GET /internal/v1/users/{user_id} → email address or None.

        Returns the user's email address from S1 Portfolio.  Returns None
        when S1 is unreachable, returns 4xx/5xx, or the field is absent.
        """
        url = f"{self._base_url}/internal/v1/users/{user_id}"
        data = await self._get_json(url)
        if data is None:
            return None
        email = data.get("email_address", "")
        return str(email) if email else None

    async def health_check(self) -> bool:
        """GET /internal/v1/health — returns True if S1 is healthy."""
        url = f"{self._base_url}/internal/v1/health"
        data = await self._get_json(url)
        return data is not None

    # ----- internals -----

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._jwt:
            headers["X-Internal-JWT"] = self._jwt
        # X-Internal-Token fallback removed — PRD-0025 mandates RS256 JWT on all services.
        return headers

    async def _get_json(self, url: str) -> dict | None:  # type: ignore[type-arg]
        try:
            resp = await self._client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except (RequestError, HTTPStatusError) as exc:
            logger.warning("s1_client_request_failed", url=url, error=str(exc))
            return None

    async def _post_json(self, url: str, json_body: dict) -> dict | None:  # type: ignore[type-arg]
        try:
            resp = await self._client.post(url, json=json_body, headers=self._headers())
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except (RequestError, HTTPStatusError) as exc:
            logger.warning("s1_client_request_failed", url=url, error=str(exc))
            return None
