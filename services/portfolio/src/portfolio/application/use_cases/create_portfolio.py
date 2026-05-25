"""Create portfolio use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.messaging.mapper import portfolio_created_to_dict
from portfolio.application.messaging.topics import EVENT_TOPIC_MAP
from portfolio.application.ports.repositories import OutboxRecord
from portfolio.domain.entities.portfolio import Portfolio
from portfolio.domain.errors import (
    IdempotencyConflictError,
    IdempotencyKeyInvalidError,
    TenantInactiveError,
    UserInactiveError,
)
from portfolio.domain.events import PortfolioCreated

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import UnitOfWork

logger = get_logger(__name__)  # type: ignore[no-any-return]


@dataclass
class CreatePortfolioCommand:
    tenant_id: UUID
    owner_id: UUID
    name: str
    currency: str = "USD"
    # REQ-002a (TASK-W0-02): caller-supplied ``Idempotency-Key`` header value.
    # When present and a portfolio with this (tenant_id, key) pair already
    # exists, the use case returns that portfolio instead of inserting a
    # second row — making POST /v1/portfolios safe to retry on network errors.
    idempotency_key: str | None = None


@dataclass
class CreatePortfolioResult:
    """Result wrapper that surfaces whether the call created a new row.

    The route uses ``created`` to pick the HTTP status code (201 for new,
    200 for an idempotent replay). Returning the dataclass instead of the
    bare ``Portfolio`` keeps the use case's contract explicit and avoids a
    second DB round-trip in the route to discover create-vs-replay state.
    """

    portfolio: Portfolio
    created: bool


class CreatePortfolioUseCase:
    async def execute(self, cmd: CreatePortfolioCommand, uow: UnitOfWork) -> CreatePortfolioResult:
        # ── REQ-002a: idempotency check ───────────────────────────────────────
        # Mirrors the proven pattern from ``RecordTransactionUseCase`` — single
        # atomic ``create_if_not_exists`` against the ``idempotency`` table to
        # eliminate the TOCTOU race, then look up the original portfolio if
        # the key has been seen before.
        idem_uuid: UUID | None = None
        if cmd.idempotency_key is not None:
            try:
                idem_uuid = UUID(cmd.idempotency_key)
            except (ValueError, AttributeError) as exc:
                raise IdempotencyKeyInvalidError(
                    f"idempotency_key must be a valid UUID: {exc}",
                ) from exc
            is_new = await uow.idempotency.create_if_not_exists(idem_uuid)
            if not is_new:
                existing = await uow.portfolios.find_by_idempotency_key(
                    cmd.tenant_id,
                    idem_uuid,
                )
                if existing is not None:
                    # Same key, same payload conceptually — return original.
                    # "Same key + different body" is detected here too: the
                    # original row carries the originally-committed name /
                    # currency / owner; the route returns it verbatim and the
                    # caller observes the *original* state, which is the
                    # canonical idempotent behaviour. Strict "different body"
                    # rejection (409) lives below where we can compare fields.
                    if (
                        existing.owner_id != cmd.owner_id
                        or existing.name != cmd.name
                        or existing.currency != cmd.currency
                    ):
                        # Same key, materially different body → 409. Caller is
                        # misusing the header (reused key for a different
                        # request). Surfacing it loudly prevents silent drift.
                        raise IdempotencyConflictError(
                            f"Idempotency key {cmd.idempotency_key!r} already used " "with a different request body",
                        )
                    return CreatePortfolioResult(portfolio=existing, created=False)
                # The idempotency row exists but the portfolio doesn't — a
                # previous request reserved the key but rolled back before
                # writing the row, or the rows are out-of-sync. Surface as
                # 409 to force the caller to retry with a fresh key.
                raise IdempotencyConflictError(
                    f"Idempotency key {cmd.idempotency_key!r} already recorded but "
                    "original portfolio not found; state is inconsistent.",
                )

        tenant = await uow.tenants.get(cmd.tenant_id)
        if tenant is None or not tenant.is_active():
            raise TenantInactiveError(
                f"Tenant {cmd.tenant_id} is not active",
                tenant_id=cmd.tenant_id,
            )

        user = await uow.users.get(cmd.owner_id, cmd.tenant_id)
        if user is None or not user.is_active():
            raise UserInactiveError(
                f"User {cmd.owner_id} is not active",
                user_id=cmd.owner_id,
            )

        portfolio = Portfolio(
            id=new_uuid(),
            tenant_id=cmd.tenant_id,
            owner_id=cmd.owner_id,
            name=cmd.name,
            currency=cmd.currency,
            # REQ-002a: stamp the idempotency key on the row so any future
            # concurrent replay can resolve back to this portfolio via the
            # partial unique index on (tenant_id, idempotency_key).
            idempotency_key=idem_uuid,
        )
        await uow.portfolios.save(portfolio)

        # PortfolioCreated MUST be emitted (not commented out as in legacy)
        event = PortfolioCreated(
            tenant_id=portfolio.tenant_id,
            portfolio_id=portfolio.id,
            owner_id=portfolio.owner_id,
            name=portfolio.name,
            currency=portfolio.currency,
        )
        record = OutboxRecord(
            id=new_uuid(),
            tenant_id=portfolio.tenant_id,
            event_type=PortfolioCreated.EVENT_TYPE,
            topic=EVENT_TOPIC_MAP[PortfolioCreated.EVENT_TYPE],
            payload=portfolio_created_to_dict(event),
            status="pending",
            attempt_count=0,
            lease_owner=None,
            lease_expires=None,
        )
        await uow.outbox.save(record)

        # REQ-002a: catch the TOCTOU race where two concurrent requests both
        # pass ``create_if_not_exists`` (neither had committed yet), then one
        # wins the commit race and the other trips the partial unique index.
        # Same shape as record_transaction.py:230-244.
        from sqlalchemy.exc import IntegrityError

        try:
            await uow.commit()
        except IntegrityError as exc:
            await uow.rollback()
            if idem_uuid is not None:
                existing = await uow.portfolios.find_by_idempotency_key(
                    cmd.tenant_id,
                    idem_uuid,
                )
                if existing is not None:
                    return CreatePortfolioResult(portfolio=existing, created=False)
            raise IdempotencyConflictError(
                f"Concurrent idempotency conflict on key {cmd.idempotency_key!r}; retry the request.",
            ) from exc

        logger.info(
            "portfolio_created",
            tenant_id=str(portfolio.tenant_id),
            portfolio_id=str(portfolio.id),
        )
        return CreatePortfolioResult(portfolio=portfolio, created=True)
