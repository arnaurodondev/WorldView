"""Transaction API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, status

from portfolio.api.dependencies import UoWDep
from portfolio.api.schemas import RecordTransactionRequest, RecordTransactionResponse, TransactionListItem
from portfolio.application.use_cases.read_models import ListTransactionsUseCase
from portfolio.application.use_cases.record_transaction import RecordTransactionCommand, RecordTransactionUseCase

router = APIRouter(tags=["transactions"])


@router.post(
    "/transactions",
    response_model=RecordTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_transaction(
    body: RecordTransactionRequest,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> RecordTransactionResponse:
    from portfolio.domain.enums import TransactionDirection, TransactionType

    uc = RecordTransactionUseCase()
    result = await uc.execute(
        RecordTransactionCommand(
            tenant_id=x_tenant_id,
            portfolio_id=body.portfolio_id,
            owner_id=x_owner_id,
            instrument_id=body.instrument_id,
            transaction_type=TransactionType(body.transaction_type),
            direction=TransactionDirection(body.direction),
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
    )


@router.get("/transactions", response_model=list[TransactionListItem])
async def list_transactions(
    uow: UoWDep,
    portfolio_id: UUID = Header(..., alias="X-Portfolio-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
) -> list[TransactionListItem]:
    uc = ListTransactionsUseCase()
    transactions = await uc.execute(portfolio_id, x_owner_id, x_tenant_id, uow)
    return [
        TransactionListItem(
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
            external_ref=t.external_ref,
            created_at=t.created_at,
        )
        for t in transactions
    ]
