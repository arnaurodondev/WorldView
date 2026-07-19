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
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.use_cases.compute_manual_holdings import (
    ComputeManualHoldingsCommand,
    ComputeManualHoldingsUseCase,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]

_CONSUMER_GROUP = "portfolio-manual-holdings-recompute"
_TOPIC = "portfolio.holding.recompute_requested.v1"

# WHY module-level: find_schema_dir() resolves the canonical schema directory
# once at import time (avoids repeated filesystem calls per message). The schema
# file for this topic is portfolio_holding_recompute_requested.v1.avsc.
_SCHEMA_DIR = find_schema_dir()

# EXPLICIT topic → schema-filename map (audit 2026-07-19).
#
# WHY NOT a string transform: the previous implementation derived the filename
# with ``topic.replace('.', '_')`` which turns
#   portfolio.holding.recompute_requested.v1
# into
#   portfolio_holding_recompute_requested_v1.avsc   (WRONG — trailing "_v1")
# but the real file (and the producer's explicit map in serialization.py) is
#   portfolio_holding_recompute_requested.v1.avsc   (the version dot is kept)
# The dot-before-``v1`` is preserved by convention, so the lossy replace-all
# produced a non-existent path → get_schema_path returned None → the consumer
# fell back to json.loads() on Confluent-Avro bytes → UnicodeDecodeError →
# every recompute event dead-lettered → the holdings table stayed empty.
#
# This map mirrors serialization.py's producer map (keyed there by event_type
# ``portfolio.holding.recompute_requested`` → same filename), keyed here by the
# full Kafka topic so serialization and deserialization stay in lock-step. Add
# a new topic here the moment this consumer subscribes to one.
_TOPIC_SCHEMA_FILES: dict[str, str] = {
    _TOPIC: "portfolio_holding_recompute_requested.v1.avsc",
}


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
            # WHY metrics increment here (not in the use case): R25 forbids
            # application-layer modules from importing infrastructure.
            # The consumer is in the infrastructure layer and is the correct
            # place for Prometheus side-effects (analogous to other consumers
            # that call metrics after a successful use-case invocation).
            import contextlib

            with contextlib.suppress(Exception):
                from portfolio.infrastructure.metrics.prometheus import MANUAL_HOLDINGS_RECOMPUTED_TOTAL

                MANUAL_HOLDINGS_RECOMPUTED_TOTAL.labels(trigger="event").inc()

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
        """Deserialize Confluent-Avro bytes for portfolio.holding.recompute_requested.v1.

        WHY Avro (not JSON): R28 mandates Avro on the wire for all Kafka topics
        that have a registered .avsc schema. The producer (RecordTransactionUseCase
        / ManualHoldingsOutboxDispatcher) serialises via serialization.py which
        emits Confluent-Avro wire format (magic byte 0x00 + 4-byte schema ID +
        Avro payload). A bare json.loads() call breaks on that prefix — Python's
        JSON codec auto-detects the leading 0x00 as UTF-32-BE and raises a cryptic
        ``UnicodeDecodeError`` (positions 4-7). That is exactly the silent failure
        the audit (2026-07-19) traced: a missing schema path → json fallback on
        Avro bytes → dead-letter → empty holdings.

        FAIL LOUD (audit 2026-07-19): we do NOT silently fall back to json.loads()
        on bytes that look like Confluent-Avro. If the schema path is unresolved
        or the Avro decode fails on a Confluent-framed payload, we raise a clear,
        explicit error so a future schema-name mismatch is immediately
        diagnosable instead of dead-lettering with a UnicodeDecodeError.

        The ONLY json path that remains is the local-dev convenience where the
        producer genuinely emits plain JSON (no Confluent magic byte 0x00) AND no
        schema path was resolved — that payload is unambiguously not Avro.
        """
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "manual_holdings_consumer_avro_deserialize_failed",
                    schema_path=schema_path,
                    error=str(exc),
                )
                raise
        # No schema path resolved. If the payload carries the Confluent-Avro
        # magic byte (0x00), a json.loads() here would raise a cryptic
        # UnicodeDecodeError and dead-letter the event — the original bug. Fail
        # loud with an actionable message instead.
        if raw[:1] == b"\x00":
            logger.error(  # type: ignore[no-any-return]
                "manual_holdings_consumer_avro_without_schema",
                topic=_TOPIC,
                expected_schema_file=_TOPIC_SCHEMA_FILES.get(_TOPIC),
                schema_dir=str(_SCHEMA_DIR),
            )
            raise MalformedDataError(
                f"Received Confluent-Avro payload for {_TOPIC!r} but no schema path "
                f"could be resolved (expected {_TOPIC_SCHEMA_FILES.get(_TOPIC)!r} in "
                f"{_SCHEMA_DIR}). Refusing to json.loads() Avro bytes."
            )
        return cast("dict[str, Any]", json.loads(raw))

    def get_schema_path(self, topic: str) -> str | None:
        """Return the canonical Avro schema path for *topic*, or fail loud.

        Resolution uses the EXPLICIT ``_TOPIC_SCHEMA_FILES`` map (mirroring the
        producer's serialization.py map) rather than a lossy string transform.
        The previous ``topic.replace('.', '_')`` derivation produced
        ``portfolio_holding_recompute_requested_v1.avsc`` (trailing ``_v1``) while
        the real file keeps the version dot
        (``portfolio_holding_recompute_requested.v1.avsc``) — the mismatch was the
        root cause of the empty-holdings bug (audit 2026-07-19).

        FAIL LOUD: if the topic is known but its schema file is absent from the
        schema dir (a packaging/deploy regression), we log at ERROR with the topic
        and the expected path and raise, so the failure is immediately
        diagnosable rather than silently returning None → json fallback →
        UnicodeDecodeError dead-letter.
        """
        schema_file = _TOPIC_SCHEMA_FILES.get(topic)
        if schema_file is None:
            # Unknown topic — this consumer only subscribes to _TOPIC, so this is
            # a wiring mistake. Log loudly and let the base consumer surface it.
            logger.error(  # type: ignore[no-any-return]
                "manual_holdings_consumer_unknown_topic_no_schema",
                topic=topic,
                known_topics=sorted(_TOPIC_SCHEMA_FILES),
            )
            return None
        path = _SCHEMA_DIR / schema_file
        if not path.exists():
            logger.error(  # type: ignore[no-any-return]
                "manual_holdings_consumer_schema_file_missing",
                topic=topic,
                expected_path=str(path),
            )
            raise FileNotFoundError(
                f"Avro schema file for topic {topic!r} not found at {path}. "
                f"This breaks holdings recomputation — deploy is missing the schema."
            )
        return str(path)

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
