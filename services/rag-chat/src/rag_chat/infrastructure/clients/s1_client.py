"""S1 Portfolio HTTP client adapter (T-E-3-03).

Endpoints:
  GET /api/v1/users/{user_id}/portfolio/context → portfolio context (cached)

Auth: X-Internal-Token + X-User-Id headers (internal service-to-service).
Cache: Valkey ``s1:v1:portfolio_ctx:{user_id}`` TTL=300 s.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import structlog  # type: ignore[import-untyped]

from rag_chat.application.ports.upstream_clients import PortfolioContext
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

if TYPE_CHECKING:
    from uuid import UUID

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

_CACHE_TTL = 300  # seconds
_CACHE_KEY_PREFIX = "s1:v1:portfolio_ctx"


class S1Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S1 Portfolio service.

    Caches portfolio context in Valkey to avoid hammering S1 on every
    chat request when the PORTFOLIO intent fires.
    """

    def __init__(
        self,
        base_url: str,
        valkey: ValkeyClient,  # type: ignore[name-defined]
        timeout: float = 5.0,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._valkey = valkey

    async def get_portfolio_context(
        self,
        user_id: UUID,
        tenant_id: UUID,
        x_internal_token: str,
    ) -> PortfolioContext | None:
        """GET /api/v1/users/{user_id}/portfolio/context.

        Checks Valkey cache first (TTL=300 s).  On cache miss, calls S1 and
        stores the result.  Returns ``None`` on timeout or HTTP error.
        """
        cache_key = f"{_CACHE_KEY_PREFIX}:{user_id}"

        # ── Cache read ─────────────────────────────────────────────────────────
        try:
            cached = await self._valkey.get(cache_key)
            if cached is not None:
                data = json.loads(cached)
                return PortfolioContext(
                    user_id=data["user_id"],
                    tenant_id=data["tenant_id"],
                    holdings=data.get("holdings", []),
                    watchlist=data.get("watchlist", []),
                    total_positions=int(data.get("total_positions", 0)),
                )
        except Exception as exc:
            logger.warning("s1_cache_read_error", error=str(exc))

        # ── HTTP call ──────────────────────────────────────────────────────────
        try:
            resp = await self._client.get(
                f"/api/v1/users/{user_id}/portfolio/context",
                headers={
                    "X-Internal-Token": x_internal_token,
                    "X-User-Id": str(user_id),
                    "X-Tenant-Id": str(tenant_id),
                },
            )
            resp.raise_for_status()
            raw: dict = resp.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=f"/api/v1/users/{user_id}/portfolio/context")
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "upstream_http_error",
                path=f"/api/v1/users/{user_id}/portfolio/context",
                status=exc.response.status_code,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning(
                "upstream_request_error",
                path=f"/api/v1/users/{user_id}/portfolio/context",
                error=str(exc),
            )
            return None

        ctx = PortfolioContext(
            user_id=raw.get("user_id", str(user_id)),
            tenant_id=raw.get("tenant_id", str(tenant_id)),
            holdings=raw.get("holdings", []),
            watchlist=raw.get("watchlist", []),
            total_positions=int(raw.get("total_positions", 0)),
        )

        # ── Cache write ────────────────────────────────────────────────────────
        try:
            payload = {
                "user_id": ctx.user_id,
                "tenant_id": ctx.tenant_id,
                "holdings": ctx.holdings,
                "watchlist": ctx.watchlist,
                "total_positions": ctx.total_positions,
            }
            await self._valkey.setex(cache_key, _CACHE_TTL, json.dumps(payload))
        except Exception as exc:
            logger.warning("s1_cache_write_error", error=str(exc))

        return ctx
