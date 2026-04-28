"""Record transaction use case with idempotency."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import transaction_recorded_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.errors import (
    AuthorizationError,
    CannotRecordTransactionOnRootPortfolioError,
    CurrencyMismatchError,
    IdempotencyConflictError,
    IdempotencyKeyInvalidError,
    InstrumentNotFoundError,
    PortfolioNotFoundError,
    TenantInactiveError,
    UserInactiveError,
)
from portfolio.domain.events import TransactionRecorded

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork
    from portfolio.domain.enums import TransactionDirection, TransactionType

# Imported eagerly (not under TYPE_CHECKING) because PortfolioKind is referenced
# at runtime in the ROOT-rejection guard below.
from portfolio.domain.enums import PortfolioKind

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
    fees: Decimal = field(default_factory=lambda: Decimal(0))
    # ``amount`` is the broker-reported cash amount. PLAN-0046 / BP-263:
    # required to surface DIVIDEND values correctly (units≈0, price≈0,
    # amount=<cash>). Optional for BUY/SELL where it is informational.
    amount: Decimal | None = None
    external_ref: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None


@dataclass
class RecordTransactionResult:
    transaction: Transaction


class RecordTransactionUseCase:
    async def execute(self, cmd: RecordTransactionCommand, uow: UnitOfWork) -> RecordTransactionResult:
        from uuid import UUID as _UUID

        # Idempotency check — fail-fast on invalid key (D-007)
        idem_uuid: _UUID | None = None
        if cmd.idempotency_key is not None:
            try:
                idem_uuid = _UUID(cmd.idempotency_key)
            except (ValueError, AttributeError) as exc:
                raise IdempotencyKeyInvalidError(
                    f"idempotency_key must be a valid UUID: {exc}",
                ) from exc
            # BP-035: atomic dedup — single INSERT ON CONFLICT DO NOTHING RETURNING eliminates
            # the TOCTOU race that exists between separate exists() and record() calls.
            is_new = await uow.idempotency.create_if_not_exists(idem_uuid)
            if not is_new:
                existing = await uow.transactions.find_by_external_ref(
                    cmd.portfolio_id,
                    cmd.tenant_id,
                    cmd.idempotency_key,
                )
                if existing is not None:
                    return RecordTransactionResult(transaction=existing)
                # F-DS-002: idempotency key recorded but transaction missing — inconsistent state.
                # This can happen if a previous request committed the idempotency row but then
                # rolled back before writing the transaction. Raise to surface as 409.
                raise IdempotencyConflictError(
                    f"Idempotency key {cmd.idempotency_key!r} already recorded but "
                    "original transaction not found; state is inconsistent. Retry the request.",
                )

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

        # PLAN-0046 Wave 3 / T-46-3-03: reject ROOT portfolios. The root
        # portfolio is a read-time aggregate over the user's other portfolios
        # and holds no positions of its own — accepting transactions here
        # would silently create rows that the holdings fan-out can never
        # surface (see GetHoldingsUseCase). Returning 400 lets API clients
        # detect the misuse explicitly.
        if portfolio.kind == PortfolioKind.ROOT:
            raise CannotRecordTransactionOnRootPortfolioError(
                "Cannot record transactions against the root (aggregate) portfolio.",
                tenant_id=cmd.tenant_id,
                details={"portfolio_id": str(cmd.portfolio_id)},
            )

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

        # Create transaction entity (in memory)
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
            amount=cmd.amount,
            currency=cmd.currency,
            executed_at=cmd.executed_at,
            external_ref=cmd.external_ref or cmd.idempotency_key,
        )

        # ── BP-264 (PLAN-0046 T-46-1-03) ─────────────────────────────────────
        # Holdings are NO LONGER mutated here. Previously this use case called
        # ``Holding.apply_delta`` per transaction, which compounded duplicates
        # whenever the SnapTrade adapter emitted the same activity twice (e.g.
        # legacy + per-account fallback paths returning different IDs for the
        # same trade). The fix is to derive holdings from the broker's position
        # snapshot (``UpsertHoldingsFromSnapshotUseCase``) which is authoritative.
        # Transactions are now history-only: they record what happened but do
        # NOT mutate cumulative state. Manual transaction APIs that previously
        # relied on apply_delta would need a separate "manual holding adjust"
        # path; that is deferred and out of scope for Wave 1.
        # NOTE: ``HoldingChanged`` is no longer emitted here either — the
        # snapshot upsert use case is the new owner of that event so consumers
        # observe broker-truth quantities only.

        # Pre-validate: build outbox event dict BEFORE the DB write (M-009).
        # Serialization errors surface here, not after a partial DB write.
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
        tx_event_dict = transaction_recorded_to_dict(tx_event)

        # Single DB write (transaction + outbox event), atomic within the UoW.
        await uow.transactions.save(transaction)
        await uow.outbox.save(
            OutboxRecord(
                id=new_uuid(),
                tenant_id=cmd.tenant_id,
                event_type=TransactionRecorded.EVENT_TYPE,
                topic=EVENT_TOPIC_MAP[TransactionRecorded.EVENT_TYPE],
                payload=tx_event_dict,
                status="pending",
                attempt_count=0,
                lease_owner=None,
                lease_expires=None,
            ),
        )

        # Catch IntegrityError from concurrent same-key commits (TOCTOU race post-BP-035).
        # Both requests passed create_if_not_exists (neither had committed yet), then one
        # wins the commit race and the other hits a unique constraint violation.
        # Import is at call-site to keep the infrastructure detail contained (sqlalchemy
        # is a dependency of the infrastructure layer; use case tolerates this boundary cross).
        from sqlalchemy.exc import IntegrityError

        try:
            await uow.commit()
        except IntegrityError as exc:
            await uow.rollback()
            if cmd.idempotency_key is not None:
                existing = await uow.transactions.find_by_external_ref(
                    cmd.portfolio_id,
                    cmd.tenant_id,
                    cmd.idempotency_key,
                )
                if existing is not None:
                    return RecordTransactionResult(transaction=existing)
            raise IdempotencyConflictError(
                f"Concurrent idempotency conflict on key {cmd.idempotency_key!r}; retry the request.",
            ) from exc

        log = logger.bind(
            tenant_id=str(cmd.tenant_id),
            portfolio_id=str(cmd.portfolio_id),
            correlation_id=cmd.correlation_id,
        )
        log.info("transaction_recorded", transaction_id=str(transaction.id))  # type: ignore[no-any-return]

        return RecordTransactionResult(transaction=transaction)
