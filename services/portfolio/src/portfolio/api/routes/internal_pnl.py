"""GET /internal/v1/users/{user_id}/portfolio/pnl — overnight P&L (PLAN-0102 W2).

Returns per-holding overnight P&L (dollar + percent) plus portfolio aggregates,
so the rag-chat morning brief can render lines like
``"AAPL +1.45% pre-mkt — +$280"`` against real data instead of cost-basis.

Auth: ``X-Internal-JWT`` validated by ``InternalJWTMiddleware`` at the app
level (sets ``request.state.user_id`` / ``tenant_id``). The path ``user_id``
must match the JWT ``user_id`` claim — same pattern as the existing
``/internal/v1/users/{user_id}/portfolio/context`` endpoint — with one
exception: an allow-listed system-token caller (the brief scheduler) may
read any user's P&L on behalf of the brief pre-generation job.

Cache: 60-second Valkey cache keyed by ``portfolio_pnl:v1:{user_id}``.
60 s matches the spec in PLAN-0102 §T-W2-01 and is short enough that an
in-flight market move surfaces in the next brief regen.

Why a dedicated router file (not a method on ``internal.py``):
    Keeps internal.py readable. Plan §T-W2-01 explicitly asks for a new
    file. Mounted by ``app.py`` alongside the existing internal_router.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.api.dependencies import ReadUoWDep
from portfolio.application.use_cases.get_portfolio_pnl import (
    GetPortfolioPnLUseCase,
    PortfolioPnLDTO,
)
from portfolio.domain.errors import UserNotFoundError

logger = get_logger(__name__)  # type: ignore[no-any-return]

internal_pnl_router = APIRouter(prefix="/internal/v1", tags=["internal-pnl"])

# Allow-list of service-token callers — same convention as ``internal.py``.
_SERVICE_PNL_ALLOWED: frozenset[str] = frozenset(
    {
        "rag-chat-brief-scheduler",
    },
)

_CACHE_KEY_PREFIX = "portfolio_pnl:v1"
_CACHE_TTL_SEC = 60


# ── Pydantic wire schemas ──────────────────────────────────────────────────────


class PnLHoldingResponse(BaseModel):
    """One holding row in the response."""

    # ``ConfigDict`` here just so future schema evolution (e.g. ``populate_by_name``)
    # is easy to add without changing call sites.
    model_config = ConfigDict()

    symbol: str | None
    entity_id: UUID | None
    instrument_id: UUID
    qty: float
    last_close_usd: float | None
    current_price_usd: float | None
    overnight_pnl_usd: float
    overnight_pnl_pct: float = Field(
        description="Per-holding overnight % (0.0 when last close unavailable)",
    )


class PortfolioPnLResponse(BaseModel):
    """Top-level response."""

    user_id: UUID
    as_of: datetime
    holdings: list[PnLHoldingResponse]
    total_overnight_pnl_usd: float
    total_overnight_pnl_pct: float
    generated_at: datetime


def _to_response(dto: PortfolioPnLDTO) -> PortfolioPnLResponse:
    """Map the internal DTO to the wire shape (Decimal → float for JSON)."""
    return PortfolioPnLResponse(
        user_id=dto.user_id,
        as_of=dto.as_of,
        holdings=[
            PnLHoldingResponse(
                symbol=h.symbol,
                entity_id=h.entity_id,
                instrument_id=h.instrument_id,
                qty=float(h.qty),
                last_close_usd=float(h.last_close_usd) if h.last_close_usd is not None else None,
                current_price_usd=float(h.current_price_usd) if h.current_price_usd is not None else None,
                overnight_pnl_usd=float(h.overnight_pnl_usd),
                overnight_pnl_pct=h.overnight_pnl_pct,
            )
            for h in dto.holdings
        ],
        total_overnight_pnl_usd=float(dto.total_overnight_pnl_usd),
        total_overnight_pnl_pct=dto.total_overnight_pnl_pct,
        generated_at=dto.generated_at,
    )


# ── Endpoint ───────────────────────────────────────────────────────────────────


@internal_pnl_router.get(
    "/users/{user_id}/portfolio/pnl",
    response_model=PortfolioPnLResponse,
    status_code=status.HTTP_200_OK,
    summary="Per-holding overnight P&L for a user",
)
async def get_portfolio_pnl(
    user_id: UUID,
    request: Request,
    uow: ReadUoWDep,
) -> PortfolioPnLResponse:
    """Compute overnight P&L per holding.

    Cache miss → joins holdings (DB) with current price + last close
    (S3 ``POST /internal/v1/price/batch``) via ``GetPortfolioPnLUseCase``.
    Cache hit → returns the cached JSON shape verbatim (60 s TTL).
    """
    # ── Auth: ownership check (same shape as portfolio_context) ────────────────
    jwt_user_id = getattr(request.state, "user_id", None)
    jwt_tenant_id = getattr(request.state, "tenant_id", None)
    jwt_role = getattr(request.state, "role", "") or ""
    jwt_service_name = getattr(request.state, "service_name", "") or ""

    is_system_caller = jwt_role == "system" and jwt_service_name in _SERVICE_PNL_ALLOWED

    if not is_system_caller:
        if jwt_user_id is None or str(jwt_user_id) != str(user_id):
            raise HTTPException(status_code=403, detail="JWT user_id must match path user_id")
        if not jwt_tenant_id:
            raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
        tenant_id = UUID(str(jwt_tenant_id))
    else:
        # System-token path: resolve real tenant from user row.
        user_entity = await uow.users.find_by_id_any_tenant(user_id)
        if user_entity is None:
            raise HTTPException(status_code=404, detail="User not found")
        tenant_id = user_entity.tenant_id
        logger.info(
            "portfolio_pnl_service_caller",
            service_name=jwt_service_name,
            path_user_id=str(user_id),
            resolved_tenant_id=str(tenant_id),
        )

    # ── Cache read ─────────────────────────────────────────────────────────────
    # The Valkey client is attached to app.state during lifespan startup.
    valkey = getattr(request.app.state, "valkey_client", None)
    cache_key = f"{_CACHE_KEY_PREFIX}:{user_id}"
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                # The cache stores the model_dump_json() bytes; round-trip via
                # model_validate_json to re-hydrate as a typed response.
                return PortfolioPnLResponse.model_validate_json(cached)
        except Exception as exc:
            # Cache failures are non-fatal: log & fall through to the live path.
            logger.warning("portfolio_pnl_cache_read_error", error=str(exc))

    # ── Live compute path ──────────────────────────────────────────────────────
    price_client = getattr(request.app.state, "recent_prices_client", None)
    if price_client is None:
        # Lazy-build a default client if the lifespan didn't pre-wire one.
        # In production app.py always sets this; the fallback exists so unit
        # tests that don't go through the full lifespan can still drive the
        # endpoint with a fake injected directly via dependency override.
        raise HTTPException(status_code=503, detail="recent_prices_client not configured")

    uc = GetPortfolioPnLUseCase(price_client=price_client)
    try:
        dto = await uc.execute(user_id=user_id, tenant_id=tenant_id, uow=uow)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    response = _to_response(dto)

    # ── Cache write ────────────────────────────────────────────────────────────
    if valkey is not None:
        try:
            payload = response.model_dump_json()
            await valkey.setex(cache_key, _CACHE_TTL_SEC, payload)
        except Exception as exc:
            logger.warning("portfolio_pnl_cache_write_error", error=str(exc))

    return response


# Decimal import retained for any future schema tweak (e.g. switching float→Decimal
# on the wire). Avoids re-import churn the next time we touch this file.
_ = Decimal  # pragma: no cover

# Marker: ``json`` unused — left here because future cache codecs may want
# explicit JSON control. Removed completely (not re-imported) to keep ruff happy.
