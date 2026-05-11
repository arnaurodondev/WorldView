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
is the suffix after the first dot.  Alpha-3 codes (e.g. "USA", "JPN") are
normalised to alpha-2 via ``_ISO3_TO_ISO2`` before entity lookups.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar
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
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]


_DATASET_FETCHED_SCHEMA_PATH = get_schema_path("market.dataset.fetched.avsc")

# Macro events carry a 30-day residual impact window (replicated from EconomicEventsWorker)
_RESIDUAL_IMPACT_DAYS = 30

# EODHD structured data has full confidence (no NLP uncertainty)
_EODHD_CONFIDENCE = 1.0

# Map EODHD 3-letter country codes (used in S2 symbols like "EVENTS.USA") to the
# alpha-2 codes stored in canonical_entities.metadata['country_iso'].
# Covers all seeds from 0002_initial_seeds + 0007_expand_economic_event_countries.
_ISO3_TO_ISO2: dict[str, str] = {
    "USA": "US",
    "GBR": "GB",
    "EUR": "EU",  # Euro Area — "EU" is non-standard but consistent with seeds
    "JPN": "JP",
    "CHN": "CN",
    "CAN": "CA",
    "AUS": "AU",
    "DEU": "DE",
    "FRA": "FR",
    "ITA": "IT",
}


def _parse_event_date(date_str: str) -> datetime | None:
    """Parse an EODHD date string to a UTC-aware datetime.

    Accepts ISO-8601 with or without time component.
    Returns ``None`` if the string cannot be parsed.

    Replicated from the former EconomicEventsWorker.
    """
    if not date_str:
        return None
    # PLAN-0052 platform-QA fix (2026-05-01): EODHD EU economic events
    # arrive with a space separator ("2026-04-30 12:15:00") instead of
    # the ISO-T form. Without this normalization, 100% of EU events were
    # silently dropped via the strptime fallthrough — confirmed live
    # (`worldview-knowledge-graph-economic-events-dataset-consumer-1`
    # logged 81 EU events at 12:25:55 with `ingested=0`). Replace the
    # FIRST space (between date and time) with `T` so the existing
    # `%Y-%m-%dT%H:%M:%S` pattern matches both shapes.
    normalized = date_str.replace(" ", "T", 1)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(normalized[:19], fmt)  # noqa: DTZ007
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _extract_country_from_symbol(symbol: str) -> str:
    """Extract the alpha-2 country code from a market-ingestion symbol.

    S2 uses symbol format ``EVENTS.USA`` or ``EVENTS.US``.  The suffix is
    mapped to alpha-2 via ``_ISO3_TO_ISO2``; unknown codes fall back to the
    first two characters.  The returned value is used for entity lookups in
    ``canonical_entities.metadata['country_iso']`` which stores alpha-2 codes.

    Examples
    --------
    - ``"EVENTS.USA"`` → ``"US"``
    - ``"EVENTS.JPN"`` → ``"JP"``
    - ``"EVENTS.US"``  → ``"US"`` (already alpha-2)

    """
    _, sep, code = symbol.partition(".")
    if not sep:
        return symbol  # Fallback: malformed symbol
    # Normalise alpha-3 → alpha-2 using the lookup table; if not found fall back
    # to the first 2 chars (handles any future EODHD codes not yet in the map).
    return _ISO3_TO_ISO2.get(code, code[:2] if len(code) >= 2 else code)


class _NoOpUoW:
    """Minimal UoW shim — economic events consumer manages sessions directly."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class EconomicEventsDatasetConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
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
    ----
        config:          Consumer configuration (bootstrap servers, group ID, topics).
        session_factory: async_sessionmaker for intelligence_db (read/write).
        storage_client:  Object storage client for MinIO claim-check downloads.
        dedup_client:    Optional Valkey dedup client (idempotency across restarts).

    """

    # ValkeyDedupMixin: 7-day TTL covers the longest polling interval in the
    # system (insider_transactions weekly) to prevent dedup-key expiry causing
    # a re-delivered offset to be processed twice.
    _dedup_prefix: str = "kg:dedup:economic_events_dataset_consumer"
    _dedup_ttl_seconds: ClassVar[int] = 7 * 86400

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

        description = "; ".join(description_parts)[:2000]  # guard against malformed payloads

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
        except json.JSONDecodeError as exc:
            # Malformed JSON is a data quality issue — log and skip (non-retryable).
            logger.warning(  # type: ignore[no-any-return]
                "economic_events_consumer_malformed_envelope",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            return None
        except Exception as exc:
            # Transient storage errors (network, timeout) — re-raise so BaseKafkaConsumer
            # does NOT commit the offset.  The message will be redelivered on restart.
            logger.warning(  # type: ignore[no-any-return]
                "economic_events_consumer_storage_error",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "economic_events_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "economic_events_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
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
