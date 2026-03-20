"""Record transaction use case with idempotency."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.holding import Holding
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TransactionDirection, TransactionType
from portfolio.domain.errors import (
    AuthorizationError,
    CurrencyMismatchError,
    InstrumentNotFoundError,
    PortfolioNotFoundError,
    TenantInactiveError,
    UserInactiveError,
)
from portfolio.domain.events import HoldingChanged, TransactionRecorded
from portfolio.messaging.mapper import holding_changed_to_dict, transaction_recorded_to_dict
from portfolio.messaging.topics import EVENT_TOPIC_MAP

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class RecordTransactionCommand:
    tenant_id: UUID
    portfolio_id: UUID
    owner_id: UUID
    instrument_id: UUID
    transaction_type: TransactionType
    direction: TransactionDirection
    quantity: Decimal
    price: Decimal
    currency: str
    executed_at: datetime
    fees: Decimal = field(default_factory=lambda: Decimal("0"))
    external_ref: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None


@dataclass
class RecordTransactionResult:
    transaction: Transaction


class RecordTransactionUseCase:
    async def execute(self, cmd: RecordTransactionCommand, uow: UnitOfWork) -> RecordTransactionResult:
        from uuid import UUID as _UUID

        # Idempotency check
        if cmd.idempotency_key is not None:
            try:
                idem_uuid = _UUID(cmd.idempotency_key)
                already_done = await uow.idempotency.exists(idem_uuid)
                if already_done:
                    # Look up existing transaction by external_ref as proxy
                    txns, _ = await uow.transactions.list_by_portfolio(cmd.portfolio_id, cmd.tenant_id, limit=10000)
                    for t in txns:
                        if t.external_ref == cmd.idempotency_key:
                            return RecordTransactionResult(transaction=t)
            except (ValueError, AttributeError):
                pass

        # Validate tenant
        tenant = await uow.tenants.get(cmd.tenant_id)
        if tenant is None or not tenant.is_active():
            raise TenantInactiveError(
                f"Tenant {cmd.tenant_id} is not active",
                tenant_id=cmd.tenant_id,
            )

        # Validate user
        user = await uow.users.get(cmd.owner_id, cmd.tenant_id)
        if user is None or not user.is_active():
            raise UserInactiveError(
                f"User {cmd.owner_id} is not active",
                user_id=cmd.owner_id,
            )

        # Validate portfolio ownership
        portfolio = await uow.portfolios.get(cmd.portfolio_id, cmd.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {cmd.portfolio_id} not found")
        if portfolio.owner_id != cmd.owner_id:
            raise AuthorizationError("Not authorized to record transactions for this portfolio")

        # Validate currency matches portfolio
        if cmd.currency != portfolio.currency:
            raise CurrencyMismatchError(
                f"Transaction currency {cmd.currency!r} does not match portfolio currency {portfolio.currency!r}",
                details={"expected": portfolio.currency, "got": cmd.currency},
            )

        # Validate instrument exists
        instrument = await uow.instruments.get(cmd.instrument_id)
        if instrument is None:
            raise InstrumentNotFoundError(
                f"Instrument {cmd.instrument_id} not found",
                details={"instrument_id": str(cmd.instrument_id)},
            )

        # Create transaction
        transaction = Transaction(
            id=new_uuid(),
            tenant_id=cmd.tenant_id,
            portfolio_id=cmd.portfolio_id,
            instrument_id=cmd.instrument_id,
            transaction_type=cmd.transaction_type,
            direction=cmd.direction,
            quantity=cmd.quantity,
            price=cmd.price,
            fees=cmd.fees,
            currency=cmd.currency,
            executed_at=cmd.executed_at,
            external_ref=cmd.external_ref or cmd.idempotency_key,
        )
        await uow.transactions.save(transaction)

        # Update or create holding
        holding = await uow.holdings.get(cmd.portfolio_id, cmd.instrument_id)
        if holding is None:
            holding = Holding(
                id=new_uuid(),
                portfolio_id=cmd.portfolio_id,
                instrument_id=cmd.instrument_id,
                currency=cmd.currency,
            )

        # Compute quantity delta: positive for inflow, negative for outflow
        qty_delta = cmd.quantity if cmd.direction == TransactionDirection.INFLOW else -cmd.quantity
        holding.apply_delta(qty_delta, cmd.price)
        await uow.holdings.save(holding)

        # Emit outbox events
        tx_event = TransactionRecorded(
            tenant_id=cmd.tenant_id,
            transaction_id=transaction.id,
            portfolio_id=cmd.portfolio_id,
            instrument_id=cmd.instrument_id,
            transaction_type=str(cmd.transaction_type),
            direction=str(cmd.direction),
            quantity=str(cmd.quantity),
            price=str(cmd.price),
            fees=str(cmd.fees),
            currency=cmd.currency,
            executed_at=cmd.executed_at.isoformat(),
            correlation_id=cmd.correlation_id,
        )
        holding_event = HoldingChanged(
            tenant_id=cmd.tenant_id,
            holding_id=holding.id,
            portfolio_id=cmd.portfolio_id,
            instrument_id=cmd.instrument_id,
            quantity=str(holding.quantity),
            average_cost=str(holding.average_cost),
            currency=holding.currency,
        )

        await uow.outbox.save(
            OutboxRecord(
                id=new_uuid(),
                tenant_id=cmd.tenant_id,
                event_type=TransactionRecorded.EVENT_TYPE,
                topic=EVENT_TOPIC_MAP[TransactionRecorded.EVENT_TYPE],
                payload=transaction_recorded_to_dict(tx_event),
                status="pending",
                attempt_count=0,
                lease_owner=None,
                lease_expires=None,
            )
        )
        await uow.outbox.save(
            OutboxRecord(
                id=new_uuid(),
                tenant_id=cmd.tenant_id,
                event_type=HoldingChanged.EVENT_TYPE,
                topic=EVENT_TOPIC_MAP[HoldingChanged.EVENT_TYPE],
                payload=holding_changed_to_dict(holding_event),
                status="pending",
                attempt_count=0,
                lease_owner=None,
                lease_expires=None,
            )
        )

        # Record idempotency
        if cmd.idempotency_key is not None:
            with contextlib.suppress(ValueError):
                await uow.idempotency.record(_UUID(cmd.idempotency_key))

        log = logger.bind(
            tenant_id=str(cmd.tenant_id),
            portfolio_id=str(cmd.portfolio_id),
            correlation_id=cmd.correlation_id,
        )
        log.info("transaction_recorded", transaction_id=str(transaction.id))  # type: ignore[no-any-return]

        return RecordTransactionResult(transaction=transaction)
