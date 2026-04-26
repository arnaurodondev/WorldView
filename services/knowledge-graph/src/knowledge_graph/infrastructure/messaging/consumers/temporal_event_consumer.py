"""Consumer 13D-9: TemporalEventConsumer (PRD-0018 §6.5).

Consumer group: ``kg-temporal-event-group``.
Consumes: ``intelligence.temporal_event.v1`` (Confluent Avro wire format).

Processing per message:
  1. Avro deserialise (Confluent magic-byte detection).
  2. Convert Avro empty-string sentinels to ``None`` (region, description,
     source_url, active_until — per PRD §6.5 Avro contract).
  3. Parse ISO-8601 strings → UTC-aware datetimes.
  4. Upsert ``temporal_events`` via ``TemporalEventRepository``.
  5. For each ``ExposedEntity`` in ``exposed_entities[]``:
     - GLOBAL scope: query ``canonical_entities.entity_type``; skip entities
       whose type is not ``sector`` or ``industry`` (PRD-0018 §6.2).
     - All other scopes: upsert ``entity_event_exposures`` row.
  6. Commit intelligence_db transaction.
  7. Mark event processed in Valkey dedup store (BP-124 compliance).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from common.ids import new_uuid7  # type: ignore[import-untyped]
from knowledge_graph.domain.enums import EventScope
from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
    EntityEventExposureRepository,
    TemporalEventRepository,
)
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


# Walk up the directory tree to find infra/kafka/schemas/ — works both in development
# (repo root is a few levels up) and in Docker (schemas copied to /app/infra/kafka/schemas/).
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()
_TEMPORAL_EVENT_SCHEMA_PATH = str(_SCHEMA_DIR / "intelligence.temporal_event.v1.avsc")

# Entity types that qualify for GLOBAL-scope event exposure (PRD-0018 §6.2).
# GLOBAL events must ONLY link sector/industry canonical entities — company
# exposure is inferred at query time via ``is_in_sector`` traversal.
# Seeded entity_type values from migration 0003 are 'sector' and 'industry_group'.
# 'industry' does not exist in canonical_entities — use 'industry_group' (PRD-0018 §6.2).
_GLOBAL_ALLOWED_ENTITY_TYPES: frozenset[str] = frozenset({"sector", "industry_group"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _or_none(s: str) -> str | None:
    """Convert empty string to ``None`` (Avro empty-string convention)."""
    return s if s else None


def _parse_utc(s: str) -> datetime:
    """Parse ISO-8601 UTC string → timezone-aware :class:`~datetime.datetime`."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _get_entity_type(session: AsyncSession, entity_id: UUID) -> str | None:
    """Look up ``entity_type`` for *entity_id* in ``canonical_entities``.

    Used by the GLOBAL-scope entity type guard to reject non-sector/industry
    entities from being linked to global temporal events.

    Returns ``None`` when the entity is not found.
    """
    result = await session.execute(
        text("SELECT entity_type FROM canonical_entities WHERE entity_id = :entity_id LIMIT 1"),
        {"entity_id": str(entity_id)},
    )
    row = result.fetchone()
    return str(row[0]) if row else None


# ---------------------------------------------------------------------------
# No-op UoW (consumer manages its own session in process_message)
# ---------------------------------------------------------------------------


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------


class TemporalEventConsumer(BaseKafkaConsumer[None]):
    """Consumes ``intelligence.temporal_event.v1`` and upserts temporal data.

    Deduplication is performed via Valkey before ``process_message`` is called
    (BP-124 compliance).  The consumer is idempotent: re-delivering the same
    event produces the same DB state due to ON CONFLICT semantics in both
    ``TemporalEventRepository`` and ``EntityEventExposureRepository``.

    Args:
    ----
        config:          Consumer configuration (group_id, topics, bootstrap_servers).
        session_factory: async_sessionmaker for ``intelligence_db``.
        dedup_client:    Optional Valkey client for event-id deduplication.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:temporal:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Upsert ``temporal_events`` + ``entity_event_exposures`` from message."""
        event_id = UUID(str(value["event_id"]))
        temporal_event_type = str(value["temporal_event_type"])
        scope = str(value["scope"])
        region = _or_none(str(value.get("region", "")))
        title = str(value["title"])
        description = _or_none(str(value.get("description", "")))
        source_article_ids: list[str] = [str(a) for a in (value.get("source_article_ids") or [])]
        source_url = _or_none(str(value.get("source_url", "")))
        active_from = _parse_utc(str(value["active_from"]))
        active_until_raw = _or_none(str(value.get("active_until", "")))
        active_until = _parse_utc(active_until_raw) if active_until_raw else None
        residual_impact_days = int(value.get("residual_impact_days", 90))
        confidence = float(value["confidence"])
        exposed_entities: list[dict[str, Any]] = list(value.get("exposed_entities") or [])
        is_global = scope == EventScope.GLOBAL

        async with self._sf() as session:
            te_repo = TemporalEventRepository(session)
            ee_repo = EntityEventExposureRepository(session)

            # Step 1: Upsert temporal_events
            db_event_id = await te_repo.upsert_by_natural_key(
                event_id=event_id,
                event_type=temporal_event_type,
                scope=scope,
                region=region,
                title=title,
                description=description,
                source_article_ids=source_article_ids if source_article_ids else None,
                source_url=source_url,
                active_from=active_from,
                active_until=active_until,
                residual_impact_days=residual_impact_days,
                confidence=confidence,
            )

            # Step 2: Upsert entity_event_exposures
            exposure_count = 0
            for entity_info in exposed_entities:
                entity_id_val = UUID(str(entity_info["entity_id"]))
                exposure_type = str(entity_info["exposure_type"])
                exposure_confidence = float(entity_info["confidence"])

                # GLOBAL scope: enforce sector/industry-only entity linking (PRD-0018 §6.2).
                # Company-level exposure for GLOBAL events is inferred at query time via
                # ``is_in_sector`` traversal — no per-company rows are created here.
                if is_global:
                    entity_type = await _get_entity_type(session, entity_id_val)
                    if entity_type not in _GLOBAL_ALLOWED_ENTITY_TYPES:
                        logger.warning(  # type: ignore[no-any-return]
                            "temporal_event_global_scope_entity_type_rejected",
                            event_id=str(db_event_id),
                            entity_id=str(entity_id_val),
                            entity_type=entity_type,
                        )
                        continue

                await ee_repo.upsert(
                    exposure_id=new_uuid7(),
                    event_id=db_event_id,
                    entity_id=entity_id_val,
                    exposure_type=exposure_type,
                    confidence=exposure_confidence,
                )
                exposure_count += 1

            await session.commit()

        logger.info(  # type: ignore[no-any-return]
            "temporal_event_processed",
            event_id=str(db_event_id),
            scope=scope,
            exposures_created=exposure_count,
        )

    # ------------------------------------------------------------------
    # Idempotency (BP-124)
    # ------------------------------------------------------------------

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        return bool(await self._dedup_client.exists(key))

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        await self._dedup_client.set(key, "1", ex=86400)

    # ------------------------------------------------------------------
    # Failure tracking (DLQ)
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "temporal_event_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "temporal_event_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "temporal_event_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "temporal_event_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialise Confluent Avro wire-format or fall back to JSON."""
        if raw and raw[0:1] == b"\x00" and schema_path:
            from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

            return deserialize_confluent_avro(schema_path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == "intelligence.temporal_event.v1":
            return _TEMPORAL_EVENT_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
