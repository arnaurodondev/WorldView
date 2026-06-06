"""S1 Portfolio HTTP client adapter (T-E-3-03).

Endpoints:
  GET /internal/v1/users/{user_id}/portfolio/context → portfolio context (cached)

Auth: X-Internal-JWT propagated from ContextVar (PRD-0025 InternalJWTMiddleware).
      S1 Portfolio validates X-Internal-JWT like all other backend services.
      The legacy X-Internal-Token / X-User-Id / X-Tenant-Id headers are removed
      — they are rejected by InternalJWTMiddleware and were the root cause of
      portfolio context calls returning 401/403.
Cache: Valkey ``s1:v1:portfolio_ctx:{user_id}`` TTL=300 s.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

import httpx
import structlog  # type: ignore[import-untyped]

from rag_chat.application.ports.upstream_clients import (
    PortfolioContext,
    PortfolioPnL,
    PortfolioPnLItem,
)
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

if TYPE_CHECKING:
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
        x_internal_token: str = "",  # — kept for protocol compat; JWT from ContextVar
    ) -> PortfolioContext | None:
        """GET /internal/v1/users/{user_id}/portfolio/context.

        Checks Valkey cache first (TTL=300 s).  On cache miss, calls S1 and
        stores the result.  Returns ``None`` on timeout or HTTP error.

        Auth note (PRD-0025): x_internal_token is ignored — the X-Internal-JWT
        header is injected automatically from the ContextVar set by the API
        middleware (same pattern as S6/S7 clients via BaseUpstreamClient._get).
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
        # WHY: Use X-Internal-JWT (PRD-0025) not the legacy X-Internal-Token.
        # S1 Portfolio validates X-Internal-JWT via InternalJWTMiddleware at startup.
        # Legacy headers (X-Internal-Token, X-User-Id, X-Tenant-Id) are rejected
        # by InternalJWTMiddleware and caused 401/403 on every portfolio call.
        from rag_chat.infrastructure.clients.auth_context import get_current_jwt

        headers: dict[str, str] = {}
        jwt = get_current_jwt()
        if jwt:
            headers["X-Internal-JWT"] = jwt

        try:
            resp = await self._client.get(
                f"/internal/v1/users/{user_id}/portfolio/context",
                headers=headers,
            )
            resp.raise_for_status()
            raw: dict = resp.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=f"/internal/v1/users/{user_id}/portfolio/context")
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "upstream_http_error",
                path=f"/internal/v1/users/{user_id}/portfolio/context",
                status=exc.response.status_code,
            )
            return None
        except httpx.RequestError as exc:
            logger.warning(
                "upstream_request_error",
                path=f"/internal/v1/users/{user_id}/portfolio/context",
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

    # ── PLAN-0102 W2 T-W2-03 — overnight P&L ────────────────────────────────────

    async def get_portfolio_pnl(self, user_id: UUID) -> PortfolioPnL | None:
        """GET /internal/v1/users/{user_id}/portfolio/pnl.

        Returns ``None`` on any HTTP / network error — callers should
        gracefully degrade to the existing weight-only brief rendering.

        S1 caches the response for 60 s server-side, so we do NOT add a
        client-side Valkey cache here (would just compound TTL drift).
        Auth: X-Internal-JWT lifted from the request ContextVar (same
        pattern as ``get_portfolio_context``).
        """
        from rag_chat.infrastructure.clients.auth_context import get_current_jwt

        headers: dict[str, str] = {}
        jwt = get_current_jwt()
        if jwt:
            headers["X-Internal-JWT"] = jwt

        path = f"/internal/v1/users/{user_id}/portfolio/pnl"
        try:
            resp = await self._client.get(path, headers=headers)
            resp.raise_for_status()
            raw: dict = resp.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=path)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning("upstream_http_error", path=path, status=exc.response.status_code)
            return None
        except httpx.RequestError as exc:
            logger.warning("upstream_request_error", path=path, error=str(exc))
            return None

        # Hand-roll the mapping because we want to swallow per-row schema drift
        # rather than crashing the brief if S1 adds a forward-compat field.
        items: list[PortfolioPnLItem] = []
        for h in raw.get("holdings", []) or []:
            try:
                items.append(
                    PortfolioPnLItem(
                        symbol=h.get("symbol"),
                        entity_id=UUID(h["entity_id"]) if h.get("entity_id") else None,
                        instrument_id=UUID(h["instrument_id"]),
                        qty=float(h.get("qty", 0.0)),
                        last_close_usd=(float(h["last_close_usd"]) if h.get("last_close_usd") is not None else None),
                        current_price_usd=(
                            float(h["current_price_usd"]) if h.get("current_price_usd") is not None else None
                        ),
                        overnight_pnl_usd=float(h.get("overnight_pnl_usd", 0.0)),
                        overnight_pnl_pct=float(h.get("overnight_pnl_pct", 0.0)),
                    ),
                )
            except (KeyError, ValueError, TypeError):
                # Single-row malformed payload should not crash the brief.
                logger.warning("s1_pnl_row_parse_error", path=path)
                continue

        return PortfolioPnL(
            user_id=UUID(raw.get("user_id", str(user_id))),
            holdings=items,
            total_overnight_pnl_usd=float(raw.get("total_overnight_pnl_usd", 0.0)),
            total_overnight_pnl_pct=float(raw.get("total_overnight_pnl_pct", 0.0)),
        )
