"""Kafka consumer: trigger manual holdings recomputation on receiving recompute events.

PLAN-0114 W1 / T-W1-07.

Subscribes to ``portfolio.holding.recompute_requested.v1``.
On each message, calls ``ComputeManualHoldingsUseCase`` to replay the
transaction history for the target MANUAL portfolio and rebuild holdings.

Architecture:
- Extends ``BaseKafkaConsumer`` (same pattern as InstrumentEventConsumer).
- Uses idempotency via the ``idempotency`` table so replay of the same
  event_id is a no-op (the consumer group will rebalance or reset after
  failure; without idempotency a crash-retry would double-compute).
- The advisory lock inside ``ComputeManualHoldingsUseCase`` prevents concurrent
  recomputation even if two consumer replicas receive the same partition.

WHY a dedicated consumer (not handled in RecordTransactionUseCase):
    RecordTransactionUseCase runs synchronously in the API request path.
    Holdings recomputation scans the full transaction history — O(n) on
    number of trades. Moving this to an async consumer keeps the API p50
    response time constant regardless of how large the history grows.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.use_cases.compute_manual_holdings import (
    ComputeManualHoldingsCommand,
    ComputeManualHoldingsUseCase,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]

_CONSUMER_GROUP = "portfolio-manual-holdings-recompute"
_TOPIC = "portfolio.holding.recompute_requested.v1"


class ManualHoldingsRecomputeConsumer(BaseKafkaConsumer[None]):
    """Consume recompute requests and rebuild MANUAL portfolio holdings.

    PLAN-0114 W1 / T-W1-07.

    One message corresponds to one portfolio recomputation. The consumer is
    single-partition (RF=1 dev) so ordering is preserved: if two transactions
    land for the same portfolio in rapid succession, the two recompute events
    will be processed sequentially. The second recomputation produces the
    correct final state because it replays the full history including both
    transactions.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: Any,
        emit_holding_changed_events: bool = False,
    ) -> None:
        super().__init__(config)
        self._session_factory = session_factory
        self._use_case = ComputeManualHoldingsUseCase(
            emit_holding_changed_events=emit_holding_changed_events,
        )

    # ── UoW ──────────────────────────────────────────────────────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        from portfolio.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

        uow = cast("UnitOfWorkProtocol", SqlAlchemyUnitOfWork(self._session_factory))
        self._current_uow = uow
        return uow

    # ── Core message processing ───────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Invoke ComputeManualHoldingsUseCase for the portfolio in the event.

        Idempotency is enforced via the ``idempotency`` table:
        - The event_id is inserted atomically; if it already exists the
          method returns early (safe replay on consumer restart).
        - BaseKafkaConsumer calls commit() after this method — we do NOT
          call uow.commit() here.
        """
        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called outside _handle_message context")

        # Validate required envelope fields
        raw_event_id = value.get("event_id", "")
        if not raw_event_id:
            raise MalformedDataError("Missing event_id in recompute_requested event")
        try:
            event_uid = UUID(str(raw_event_id))
        except ValueError as exc:
            raise MalformedDataError(f"Invalid event_id format: {raw_event_id!r}") from exc

        # Atomic idempotency check — skip if already processed (replay safety).
        is_new = await uow.idempotency.create_if_not_exists(event_uid)  # type: ignore[attr-defined]
        if not is_new:
            logger.debug(  # type: ignore[no-any-return]
                "manual_holdings_consumer_duplicate",
                event_id=str(event_uid)[:8],
            )
            return

        # Extract portfolio context from the event payload
        raw_portfolio_id = value.get("portfolio_id", "")
        raw_tenant_id = value.get("tenant_id", "")
        raw_owner_id = value.get("owner_id", "")

        try:
            portfolio_id = UUID(str(raw_portfolio_id))
            tenant_id = UUID(str(raw_tenant_id))
            owner_id = UUID(str(raw_owner_id))
        except (ValueError, TypeError) as exc:
            raise MalformedDataError(
                f"Invalid UUID fields in recompute_requested event: "
                f"portfolio_id={raw_portfolio_id!r} "
                f"tenant_id={raw_tenant_id!r} "
                f"owner_id={raw_owner_id!r}"
            ) from exc

        # ComputeManualHoldingsUseCase calls UpsertHoldingsFromSnapshotUseCase
        # which calls uow.commit() internally. BaseKafkaConsumer will call
        # commit() again after this method returns — that second commit is a
        # no-op on an already-committed transaction.
        cmd = ComputeManualHoldingsCommand(
            portfolio_id=portfolio_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            trigger="event",
        )
        # NOTE: we pass the consumer's UoW to the use case. The use case may
        # call uow.commit() internally (via UpsertHoldingsFromSnapshotUseCase).
        # This is intentional and safe: the idempotency INSERT and the holdings
        # upsert land in the same transaction, ensuring atomicity.
        result = await self._use_case.execute(cmd, uow)  # type: ignore[arg-type]

        if result.skipped:
            logger.info(  # type: ignore[no-any-return]
                "manual_holdings_consumer_skipped",
                portfolio_id=str(portfolio_id),
                reason="advisory_lock_held_or_non_manual",
            )
        else:
            logger.info(  # type: ignore[no-any-return]
                "manual_holdings_consumer_done",
                portfolio_id=str(portfolio_id),
                upserted=result.upserted,
                deleted=result.deleted,
            )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        """Re-process a stored failure (no-op: payload not stored for this consumer)."""
        logger.warning(  # type: ignore[no-any-return]
            "manual_holdings_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ── Idempotency (handled atomically in process_message) ──────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        """Always False — dedup is handled atomically inside process_message."""
        return False

    async def mark_processed(self, event_id: str) -> None:
        """No-op — dedup record inserted atomically in process_message."""

    # ── Failure tracking ─────────────────────────────────────────────────────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "manual_holdings_consumer_failure",
            event_id=failure.event_id,
            attempt=failure.attempt,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "manual_holdings_consumer_failure_updated",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "manual_holdings_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize message value — JSON fallback (Avro payload for future SR support)."""
        return cast("dict[str, Any]", json.loads(raw))

    def get_schema_path(self, topic: str) -> str | None:
        """Return None — this consumer currently uses JSON serialization."""
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
