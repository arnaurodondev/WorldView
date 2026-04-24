"""Consumer 13D-6: Economic Events dataset ingestion via Kafka.

Consumer group: ``kg-economic-events-dataset-group``.
Consumes: ``market.dataset.fetched`` WHERE dataset_type='economic_events'.

Processing:
  1. Filter messages to dataset_type='economic_events'.
  2. Download canonical NDJSON envelope from MinIO (claim-check pattern).
  3. Parse the passthrough envelope: ``{"dataset_type": ..., "symbol": ...,
     "source": "eodhd", "payload": [...], "fetched_at": "..."}``.
  4. Apply the same upsert logic as the former EconomicEventsWorker (13D-6):
     - Skip unreleased events (actual=None).
     - Compute surprise magnitude for description.
     - Upsert into ``temporal_events`` with event_type=MACRO, scope=NATIONAL.
     - Link to country canonical entity via ``entity_event_exposures``.

Symbol format from S2: ``EVENTS.USA`` or ``EVENTS.US`` — the country code
is the suffix after the first dot.  Both 2-letter (alpha-2) and 3-letter
(alpha-3) suffixes are handled; alpha-3 codes are trimmed to their first
2 chars as a fallback (EODHD economic-events API uses alpha-2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from knowledge_graph.domain.enums import EventScope, EventType, ExposureType
from knowledge_graph.infrastructure.metrics.prometheus import s7_economic_events_ingested_total
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

_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "infra" / "kafka" / "schemas"
_DATASET_FETCHED_SCHEMA_PATH = str(_SCHEMA_DIR / "market.dataset.fetched.avsc")

# Macro events carry a 30-day residual impact window (replicated from EconomicEventsWorker)
_RESIDUAL_IMPACT_DAYS = 30

# EODHD structured data has full confidence (no NLP uncertainty)
_EODHD_CONFIDENCE = 1.0


def _parse_event_date(date_str: str) -> datetime | None:
    """Parse an EODHD date string to a UTC-aware datetime.

    Accepts ISO-8601 with or without time component.
    Returns ``None`` if the string cannot be parsed.

    Replicated from the former EconomicEventsWorker.
    """
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str[:19], fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_country_from_symbol(symbol: str) -> str:
    """Extract the country code from a market-ingestion symbol.

    S2 uses symbol format ``EVENTS.USA`` or ``EVENTS.US``.
    The country code is everything after the first dot.

    Examples:
    - ``"EVENTS.USA"`` → ``"USA"`` (alpha-3, passed through as-is)
    - ``"EVENTS.US"``  → ``"US"``  (alpha-2)

    The EODHD economic-events API uses alpha-2 codes.  S2 sends the
    same symbol it used when calling the API, so this is normally alpha-2.
    If an alpha-3 is encountered, it is returned unchanged — callers use
    it for entity lookups which may handle both.
    """
    parts = symbol.split(".", 1)
    if len(parts) == 2:
        return parts[1]
    return symbol  # Fallback: return symbol as-is


class _NoOpUoW:
    """Minimal UoW shim — economic events consumer manages sessions directly."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class EconomicEventsDatasetConsumer(BaseKafkaConsumer[None]):
    """Consumer 13D-6: Ingest economic events from market.dataset.fetched Kafka topic.

    Replaces the former APScheduler-based EconomicEventsWorker.  Instead of
    calling EODHD directly, this consumer receives pre-fetched data from S2
    (market-ingestion) via the claim-check pattern and applies identical DB
    upsert logic.

    Processing per message:
    1. Filter: only ``dataset_type='economic_events'`` is processed.
    2. Download canonical NDJSON envelope from MinIO.
    3. Parse envelope → extract raw EODHD event list from ``payload``.
    4. Upsert each released event into ``temporal_events``; link to country entity.

    Args:
        config:          Consumer configuration (bootstrap servers, group ID, topics).
        session_factory: async_sessionmaker for intelligence_db (read/write).
        storage_client:  Object storage client for MinIO claim-check downloads.
        dedup_client:    Optional Valkey dedup client (idempotency across restarts).
    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        storage_client: Any | None = None,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._storage = storage_client
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:eco_events:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Process a market.dataset.fetched event for economic events data."""
        dataset_type = str(value.get("dataset_type", ""))
        if dataset_type != "economic_events":
            return  # Not an economic events message — skip silently

        symbol = str(value.get("symbol", ""))
        bucket = value.get("canonical_ref_bucket")
        object_key = value.get("canonical_ref_key")

        # Download the canonical NDJSON envelope from MinIO
        envelope = await self._download_envelope(bucket, object_key, symbol=symbol)
        if envelope is None:
            return

        # envelope["payload"] is the raw EODHD response (list of event dicts)
        events = envelope.get("payload")
        if not isinstance(events, list) or not events:
            logger.debug(  # type: ignore[no-any-return]
                "economic_events_consumer_empty_payload",
                symbol=symbol,
            )
            return

        # Derive country from symbol (e.g. "EVENTS.US" → "US")
        country = _extract_country_from_symbol(symbol)

        await self._process_events(events, country, symbol)

    async def _process_events(
        self,
        events: list[dict[str, Any]],
        country: str,
        symbol: str,
    ) -> None:
        """Upsert all released events for one country into temporal_events."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
            EntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
            TemporalEventRepository,
        )

        ingested = 0

        async with self._sf() as session:
            event_repo = TemporalEventRepository(session)
            exposure_repo = EntityEventExposureRepository(session)
            entity_repo = EntityRepository(session)

            country_entity_id = await entity_repo.find_country_entity(country)
            if country_entity_id is None:
                logger.debug(  # type: ignore[no-any-return]
                    "economic_events_consumer_country_entity_missing",
                    country=country,
                    symbol=symbol,
                )

            for ev in events:
                upserted = await self._upsert_event(
                    ev=ev,
                    country=country,
                    event_repo=event_repo,
                    exposure_repo=exposure_repo,
                    country_entity_id=country_entity_id,
                )
                if upserted:
                    ingested += 1

            await session.commit()

        if ingested:
            s7_economic_events_ingested_total.labels(country=country).inc(ingested)

        logger.info(  # type: ignore[no-any-return]
            "economic_events_consumer_processed",
            symbol=symbol,
            country=country,
            ingested=ingested,
            total_events=len(events),
        )

    async def _upsert_event(
        self,
        ev: dict[str, Any],
        country: str,
        event_repo: Any,
        exposure_repo: Any,
        country_entity_id: UUID | None,
    ) -> bool:
        """Process a single EODHD economic event dict.

        Returns ``True`` if the event was upserted; ``False`` if skipped.

        Skips events where ``actual`` is ``None`` (unreleased scheduled events).

        Logic replicated 1:1 from the former EconomicEventsWorker._upsert_event().
        """
        from datetime import timedelta

        actual = ev.get("actual")
        if actual is None:
            return False  # Unreleased event — skip

        # Build event title (natural key component)
        ev_type = str(ev.get("type", "Economic Event"))
        period = str(ev.get("period", ""))
        title = f"{ev_type} ({country}) — {period}"
        if len(title) > 500:
            title = title[:497] + "..."

        # Build description with surprise magnitude
        previous = ev.get("previous")
        description_parts = [f"Actual: {actual}, Previous: {previous}"]

        estimate = ev.get("estimate")
        if estimate is not None:
            try:
                surprise = float(actual) - float(estimate)
                direction = "beat" if surprise > 0 else "missed"
                change_pct = ev.get("change_percentage")
                if change_pct is not None:
                    description_parts.append(f"Estimate {direction} by {abs(surprise):.2f} ({float(change_pct):.1f}%)")
                else:
                    description_parts.append(f"Estimate {direction} by {abs(surprise):.2f}")
            except (TypeError, ValueError):
                pass

        description = "; ".join(description_parts)

        # Parse event date — skip if unparseable
        active_from = _parse_event_date(str(ev.get("date", "")))
        if active_from is None:
            logger.warning(  # type: ignore[no-any-return]
                "economic_events_consumer_invalid_date",
                country=country,
                raw_date=ev.get("date"),
            )
            return False

        active_until = active_from + timedelta(hours=24)

        event_id = new_uuid7()
        # On conflict the repo returns the EXISTING row's UUID (natural-key upsert).
        # The exposure FK must reference this canonical DB event_id.
        db_event_id = await event_repo.upsert_by_natural_key(
            event_id=event_id,
            event_type=EventType.MACRO,
            scope=EventScope.NATIONAL,
            region=country,
            title=title,
            description=description,
            active_from=active_from,
            active_until=active_until,
            residual_impact_days=_RESIDUAL_IMPACT_DAYS,
            confidence=_EODHD_CONFIDENCE,
        )

        # Link to the country's canonical entity (if found)
        if country_entity_id is not None:
            exposure_id = new_uuid7()
            await exposure_repo.upsert(
                exposure_id=exposure_id,
                event_id=db_event_id,
                entity_id=country_entity_id,
                exposure_type=ExposureType.DIRECTLY_AFFECTED,
                confidence=_EODHD_CONFIDENCE,
            )

        logger.debug(  # type: ignore[no-any-return]
            "economic_events_consumer_event_upserted",
            country=country,
            title=title,
        )
        return True

    async def _download_envelope(
        self,
        bucket: str | None,
        object_key: str | None,
        *,
        symbol: str = "",
    ) -> dict[str, Any] | None:
        """Download and parse the canonical NDJSON envelope from MinIO.

        The passthrough envelope is a single NDJSON line:
        ``{"dataset_type": "economic_events", "symbol": "...",
           "source": "eodhd", "payload": [...], "fetched_at": "..."}``.
        """
        if not bucket or not object_key or not self._storage:
            return None
        try:
            raw: bytes = await self._storage.get_bytes(bucket, object_key)
            line = raw.decode("utf-8").strip()
            if not line:
                return None
            envelope: dict[str, Any] = json.loads(line)
            return envelope
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "economic_events_consumer_storage_error",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # Idempotency
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
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "economic_events_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )
        return None

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "economic_events_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "economic_events_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "economic_events_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialise Confluent Avro wire-format or fall back to JSON.

        BP-122: market.dataset.fetched messages use the Confluent Avro wire
        format (5-byte header: magic 0x00 + 4-byte schema ID).
        """
        if raw and raw[0:1] == b"\x00" and schema_path:
            from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

            return deserialize_confluent_avro(schema_path, raw)  # type: ignore[no-any-return]
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == "market.dataset.fetched":
            return _DATASET_FETCHED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
