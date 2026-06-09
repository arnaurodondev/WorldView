"""Transaction API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT (PRD-0025, F-CRIT-001 remediation).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    PaginatedResponse,
    RecordTransactionRequest,
    RecordTransactionResponse,
    TransactionListItem,
)
from portfolio.application.use_cases.read_models import ListTransactionsUseCase
from portfolio.application.use_cases.record_transaction import RecordTransactionCommand, RecordTransactionUseCase
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType

router = APIRouter(tags=["transactions"])


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


def _extract_owner_id(request: Request) -> UUID:
    """Read user_id (owner) from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "user_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    return UUID(str(raw))


@router.post(
    "/transactions",
    response_model=RecordTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_transaction(
    body: RecordTransactionRequest,
    uow: UoWDep,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> RecordTransactionResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)

    # PLAN-0108: TRADE transactions derive direction from trade_side so the
    # frontend doesn't need to know the INFLOW/OUTFLOW convention.
    # All other transaction types still require an explicit direction field.
    if body.transaction_type == "TRADE":
        direction = TransactionDirection.INFLOW if body.trade_side == "BUY" else TransactionDirection.OUTFLOW
        trade_side = TradeSide(body.trade_side)  # type: ignore[arg-type]
    else:
        # The schema validator already ensures direction is non-None for non-TRADE,
        # but we provide a fallback to avoid a runtime AttributeError if direction
        # is absent from older clients (results in 422 via Pydantic before this point).
        direction = TransactionDirection(body.direction or "INFLOW")
        trade_side = None

    uc = RecordTransactionUseCase()
    result = await uc.execute(
        RecordTransactionCommand(
            tenant_id=x_tenant_id,
            portfolio_id=body.portfolio_id,
            owner_id=x_owner_id,
            instrument_id=body.instrument_id,
            transaction_type=TransactionType(body.transaction_type),
            direction=direction,
            trade_side=trade_side,
            quantity=body.quantity,
            price=body.price,
            fees=body.fees,
            currency=body.currency,
            executed_at=body.executed_at,
            external_ref=body.external_ref,
            idempotency_key=idempotency_key,
        ),
        uow,
    )
    t = result.transaction
    return RecordTransactionResponse(
        id=t.id,
        portfolio_id=t.portfolio_id,
        instrument_id=t.instrument_id,
        transaction_type=str(t.transaction_type),
        direction=str(t.direction),
        quantity=t.quantity,
        price=t.price,
        fees=t.fees,
        currency=t.currency,
        executed_at=t.executed_at,
        created_at=t.created_at,
        trade_side=str(t.trade_side) if t.trade_side else None,
    )


def _build_transaction_response(
    enriched: list,  # type: ignore[type-arg]  # list[EnrichedTransaction]
    total: int,
    limit: int,
    offset: int,
) -> PaginatedResponse[TransactionListItem]:
    """Shared serialisation for the flat and nested transaction endpoints.

    F-012: extracted so both ``GET /transactions`` (flat) and
    ``GET /portfolios/{id}/transactions`` (nested) emit identical bodies.
    F-205 (QA iter-2): now consumes ``EnrichedTransaction`` so the response
    carries ``ticker``/``name`` resolved from the local instruments cache.
    """
    return PaginatedResponse(
        items=[
            TransactionListItem(
                id=e.transaction.id,
                portfolio_id=e.transaction.portfolio_id,
                instrument_id=e.transaction.instrument_id,
                transaction_type=str(e.transaction.transaction_type),
                direction=str(e.transaction.direction),
                quantity=e.transaction.quantity,
                price=e.transaction.price,
                fees=e.transaction.fees,
                amount=e.transaction.amount,  # PLAN-0046 / BP-263 — surface SnapTrade cash amount
                currency=e.transaction.currency,
                # F-205: enrichment fields (None when instrument not in local cache).
                ticker=e.ticker,
                name=e.name,
                # PLAN-0053 T-D-4-02: asset_class for frontend badge.
                asset_class=e.asset_class,
                executed_at=e.transaction.executed_at,
                external_ref=e.transaction.external_ref,
                # P2-E: broker-supplied description (Alembic 0020). None for
                # historical rows and brokers that omit the field.
                description=e.transaction.description,
                created_at=e.transaction.created_at,
            )
            for e in enriched
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/transactions", response_model=PaginatedResponse[TransactionListItem])
async def list_transactions(
    uow: ReadUoWDep,
    request: Request,
    portfolio_id: UUID = Header(..., alias="X-Portfolio-ID"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[TransactionListItem]:
    x_owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = ListTransactionsUseCase()
    transactions, total = await uc.execute(portfolio_id, x_owner_id, x_tenant_id, uow, limit=limit, offset=offset)
    return _build_transaction_response(transactions, total, limit, offset)


# F-012 (QA 2026-04-28): canonical REST-nested form. The flat
# ``/v1/transactions?portfolio_id=...`` path stays for backward compat
# (the dashboard / older clients still hit it), but the nested form
# matches the rest of the analytics surface (``/portfolios/{id}/exposure``,
# ``/value-history``, ``/risk-metrics``) so a strict OpenAPI consumer
# isn't forced to special-case transactions.
@router.get(
    "/portfolios/{portfolio_id}/transactions",
    response_model=PaginatedResponse[TransactionListItem],
)
async def list_transactions_nested(
    portfolio_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[TransactionListItem]:
    """Nested alias for ``GET /transactions?portfolio_id=...``.

    Keeps the API surface uniform across the portfolio analytics endpoints
    that already use the nested form. The flat endpoint remains as the
    canonical path during the transition.
    """
    x_owner_id = _extract_owner_id(request)
    x_tenant_id = _extract_tenant_id(request)
    uc = ListTransactionsUseCase()
    transactions, total = await uc.execute(portfolio_id, x_owner_id, x_tenant_id, uow, limit=limit, offset=offset)
    return _build_transaction_response(transactions, total, limit, offset)
