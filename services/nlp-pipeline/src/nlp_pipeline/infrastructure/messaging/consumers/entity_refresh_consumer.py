"""Entity refresh consumer for the NLP Pipeline (S6) — REQ-003 / TASK-W0-06.

Consumes ``entity.refresh.v1`` events emitted by S7
``TriggerEntityRefreshUseCase`` when a user manually triggers
``POST /api/v1/entities/{entity_id}/refresh`` at the gateway.

Side-effect (idempotent): marks the relevant ``entity_embedding_state`` rows
as due for refresh by setting ``next_refresh_at = now()``.  S7's
``DefinitionRefreshWorker`` polls ``WHERE next_refresh_at < now()`` on a 90-day
cadence (configurable), so flipping the column forwards the row into the
"due" set immediately.

Dirty-flag mechanism (chosen after grepping S7 workers):
- ``entity_embedding_state.next_refresh_at`` already exists as the periodic
  refresh signal for both Definition + Narrative + Fundamentals views; no new
  column or table is introduced (R24 — DDL stays in intelligence-migrations).
- For ``refresh_type='description'``: update the row WHERE view_type='definition'.
- For ``refresh_type='narrative'``: update the row WHERE view_type='narrative'.
- For ``refresh_type='all'``: update all view rows for the entity.

Idempotency:
- ``UPDATE ... SET next_refresh_at = now()`` is naturally idempotent —
  re-delivery flips it to ``now()`` again, which is a no-op for the worker
  (it was already due).  No dedup table needed; we follow the watchlist
  consumer's pattern (BaseKafkaConsumer ``is_duplicate`` returning False).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TOPIC = "entity.refresh.v1"
_SCHEMA_PATH = get_schema_path("entity.refresh.v1.avsc")

# Allowed refresh_type values — must mirror
# knowledge_graph.application.use_cases.trigger_entity_refresh.ALLOWED_REFRESH_TYPES.
_REFRESH_DESCRIPTION = "description"
_REFRESH_NARRATIVE = "narrative"
_REFRESH_ALL = "all"

# entity_embedding_state.view_type values — must match the
# intelligence_db.entity_embedding_state table.
_VIEW_DEFINITION = "definition"
_VIEW_NARRATIVE = "narrative"


class _NoOpUnitOfWork:
    """Minimal UoW stub — this consumer manages its own session inside process_message."""

    async def __aenter__(self) -> _NoOpUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class EntityRefreshConsumer(BaseKafkaConsumer[None]):
    """Consumes entity.refresh.v1 and marks entity_embedding_state rows as due.

    Args:
        config:                      Standard Kafka consumer config.
        intelligence_session_factory: Sessionmaker for intelligence_db; used
                                     to UPDATE entity_embedding_state rows.
                                     S6 has read access to this DB already
                                     (entity_resolution Stage 4 reads from it);
                                     this is the same connection pool.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        intelligence_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(config)
        self._intel_sf = intelligence_session_factory

    # ── UoW (no-op — session managed directly inside process_message) ───────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    # ── Core processing ─────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Mark entity_embedding_state rows as due for refresh.

        Re-uses the existing ``next_refresh_at`` column as a "dirty flag" so
        no schema migration is needed (R24).  Setting ``next_refresh_at = now()``
        immediately satisfies the condition ``next_refresh_at < now()`` used by
        ``DefinitionRefreshWorker.get_due_for_refresh()`` on its next cycle.
        """
        raw_entity_id = value.get("entity_id") or ""
        refresh_type = (value.get("refresh_type") or _REFRESH_ALL).strip().lower()

        if not raw_entity_id:
            logger.warning(  # type: ignore[no-any-return]
                "entity_refresh_event_missing_entity_id",
                event_id=value.get("event_id"),
            )
            return

        try:
            entity_id = UUID(str(raw_entity_id))
        except ValueError:
            logger.warning(  # type: ignore[no-any-return]
                "entity_refresh_event_invalid_entity_id",
                raw_entity_id=raw_entity_id,
            )
            return

        # Map refresh_type → which view rows to flip.
        if refresh_type == _REFRESH_DESCRIPTION:
            view_types: tuple[str, ...] = (_VIEW_DEFINITION,)
        elif refresh_type == _REFRESH_NARRATIVE:
            view_types = (_VIEW_NARRATIVE,)
        elif refresh_type == _REFRESH_ALL:
            view_types = (_VIEW_DEFINITION, _VIEW_NARRATIVE)
        else:
            # Forward-compat: an older S6 build receives a new refresh_type value
            # added later (e.g. "fundamentals").  Log + skip rather than crash.
            logger.warning(  # type: ignore[no-any-return]
                "entity_refresh_unknown_refresh_type",
                refresh_type=refresh_type,
                entity_id=str(entity_id),
            )
            return

        # Single UPDATE batches both view rows when applicable.  Using
        # ``next_refresh_at = now()`` (and NOT a past timestamp) is sufficient
        # because the worker query uses ``< now()`` and the next poll runs
        # microseconds later.
        async with self._intel_sf() as session:
            result = await session.execute(
                text(
                    "UPDATE entity_embedding_state "
                    "SET next_refresh_at = now() "
                    "WHERE entity_id = CAST(:entity_id AS uuid) "
                    "AND view_type = ANY(CAST(:view_types AS text[]))",
                ),
                {"entity_id": str(entity_id), "view_types": list(view_types)},
            )
            await session.commit()
            rows = result.rowcount if result.rowcount is not None else 0  # type: ignore[attr-defined]

        logger.info(  # type: ignore[no-any-return]
            "entity_refresh_processed",
            entity_id=str(entity_id),
            refresh_type=refresh_type,
            view_types=list(view_types),
            rows_flipped=int(rows),
            event_id=value.get("event_id"),
        )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        # The processing path is a single idempotent UPDATE; retries are
        # safe.  We log + skip rather than build a retry path.
        logger.warning(  # type: ignore[no-any-return]
            "entity_refresh_consumer_retry_skipped",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    # ── Idempotency (at-least-once; UPDATE next_refresh_at=now() is naturally idempotent) ──

    async def is_duplicate(self, event_id: str) -> bool:
        return False  # UPDATE next_refresh_at=now() is idempotent — safe under re-delivery

    async def mark_processed(self, event_id: str) -> None:
        return None  # No dedup store needed

    # ── Failure tracking (log-only — no DB persistence) ─────────────────────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "entity_refresh_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "entity_refresh_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "entity_refresh_consumer_dead_lettered",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ───────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Confluent-Avro or JSON payload.

        S7 outbox dispatcher publishes entity.refresh.v1 as Confluent Avro
        (5-byte header: magic 0x00 + 4-byte schema_id).  Fall back to JSON
        for plain payloads (integration tests producing raw dicts).
        """
        if raw and raw[0:1] == b"\x00":
            from messaging.kafka.serialization_utils import (  # type: ignore[import-untyped]
                deserialize_confluent_avro,
            )

            return deserialize_confluent_avro(_SCHEMA_PATH, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _TOPIC:
            return _SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
