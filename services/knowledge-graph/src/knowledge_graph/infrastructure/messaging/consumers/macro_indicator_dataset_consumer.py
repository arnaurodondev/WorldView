"""Consumer 13D-7: Macro Indicator dataset enrichment via Kafka.

Consumer group: ``kg-macro-indicator-dataset-group``.
Consumes: ``market.dataset.fetched`` WHERE dataset_type='macro_indicator'.

Processing:
  1. Filter messages to dataset_type='macro_indicator'.
  2. Download canonical NDJSON envelope from MinIO (claim-check pattern).
  3. Parse the passthrough envelope to extract indicator code and country from symbol.
  4. Apply the same hash-comparison + metadata patch logic as the former
     MacroIndicatorWorker (13D-7):
     - Build macro_data dict from the payload (single indicator result list).
     - Compute SHA-256 of new data; skip if unchanged.
     - Update ``canonical_entities.metadata["macro_indicators"]`` on change.
     - Produce ``entity.dirtied.v1`` to trigger re-embedding.

Symbol format from S2: ``GDPCAP.USA`` (indicator_code.ISO3_country).
The indicator code is everything before the last dot; the country is after.

Note: S2 fetches one indicator per symbol call.  Each Kafka message therefore
contains one indicator's data for one country.  The consumer accumulates
the macro_data dict by merging the incoming indicator into the stored metadata
and then comparing the full updated hash — this is a departure from the batch
approach in the former worker, which fetched all 6 indicators in one run and
stored them together.

However, for simplicity and correctness, this consumer stores only the
indicator present in the incoming message and marks the entity dirty so
the downstream embedding worker re-processes it.  The consumer is idempotent:
the DB JSONB merge operation is commutative, and the hash guard prevents
unnecessary re-embeddings.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.metrics.prometheus import s7_macro_indicator_updates_total
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
_DATASET_FETCHED_SCHEMA_PATH = str(_SCHEMA_DIR / "market.dataset.fetched.avsc")

# World Bank indicator codes that S2 fetches (replicated from former MacroIndicatorWorker)
MACRO_INDICATORS: tuple[str, ...] = (
    "gdp_current_usd",
    "gdp_growth_annual",
    "inflation_consumer_prices_annual",
    "real_interest_rate",
    "unemployment_total_pct",
    "current_account_balance_bop_usd",
)

# Mapping of ISO 3166-1 alpha-3 → alpha-2 for entity lookups.
# The Macro Indicator API uses alpha-3 codes; entity_repository.find_country_entity()
# expects alpha-2 (stored in the entity's metadata as ``country_iso``).
_ISO3_TO_ISO2: dict[str, str] = {
    "USA": "US",
    "GBR": "GB",
    "DEU": "DE",
    "JPN": "JP",
    "CHN": "CN",
    "FRA": "FR",
    "ITA": "IT",
    "CAN": "CA",
    "AUS": "AU",
    "BRA": "BR",
    "IND": "IN",
    "RUS": "RU",
    "KOR": "KR",
    "MEX": "MX",
    "IDN": "ID",
}


def _sha256_hex(s: str) -> str:
    """Return the SHA-256 hex digest of the UTF-8 encoded string *s*."""
    return hashlib.sha256(s.encode()).hexdigest()


def _parse_symbol(symbol: str) -> tuple[str, str]:
    """Parse a macro indicator symbol into (indicator_code, iso3_country).

    S2 uses the format ``ISO3_COUNTRY.INDICATOR_CODE``, e.g.:
    - ``"USA.gdp_current_usd"`` → ``("gdp_current_usd", "USA")``
    - ``"EUR.inflation_consumer_prices_annual"`` → ``("inflation_consumer_prices_annual", "EUR")``

    The indicator code is normalised to lower-case to match MACRO_INDICATORS.
    If parsing fails, returns the full symbol as the indicator_code and an
    empty string for the country.
    """
    country, sep, indicator_code = symbol.partition(".")
    if sep:
        return indicator_code.lower(), country
    return symbol.lower(), ""


class _NoOpUoW:
    """Minimal UoW shim — macro indicator consumer manages sessions directly."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class MacroIndicatorDatasetConsumer(BaseKafkaConsumer[None]):
    """Consumer 13D-7: Enrich country entity metadata with macro indicator data.

    Replaces the former APScheduler-based MacroIndicatorWorker.  Instead of
    calling EODHD directly, this consumer receives pre-fetched data from S2
    (market-ingestion) via the claim-check pattern and applies identical hash
    comparison + metadata patch logic.

    Processing per message:
    1. Filter: only ``dataset_type='macro_indicator'`` is processed.
    2. Download canonical NDJSON envelope from MinIO.
    3. Parse symbol to extract indicator_code and ISO3 country.
    4. Build macro_data entry from the payload (most-recent value).
    5. Compare hash of merged macro_indicators dict — skip if unchanged.
    6. Update ``canonical_entities.metadata["macro_indicators"]`` on change.
    7. Produce ``entity.dirtied.v1`` (best-effort, non-blocking).

    Args:
    ----
        config:               Consumer configuration.
        session_factory:      async_sessionmaker for intelligence_db (read/write).
        storage_client:       Object storage client for MinIO claim-check downloads.
        direct_producer:      Optional Kafka producer for entity.dirtied.v1.
        entity_dirtied_topic: Topic name for entity.dirtied.v1 events.
        dedup_client:         Optional Valkey dedup client.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        storage_client: Any | None = None,
        direct_producer: Any | None = None,
        entity_dirtied_topic: str = "entity.dirtied.v1",
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._storage = storage_client
        self._producer = direct_producer
        self._dirtied_topic = entity_dirtied_topic
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:macro:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Process a market.dataset.fetched event for macro indicator data."""
        dataset_type = str(value.get("dataset_type", ""))
        if dataset_type != "macro_indicator":
            return  # Not a macro indicator message — skip silently

        symbol = str(value.get("symbol", ""))
        bucket = value.get("canonical_ref_bucket")
        object_key = value.get("canonical_ref_key")

        # Download the canonical NDJSON envelope from MinIO
        envelope = await self._download_envelope(bucket, object_key, symbol=symbol)
        if envelope is None:
            return

        # envelope["payload"] is the raw EODHD macro indicator response (list of dicts)
        payload = envelope.get("payload")
        if not isinstance(payload, list) or not payload:
            logger.debug(  # type: ignore[no-any-return]
                "macro_indicator_consumer_empty_payload",
                symbol=symbol,
            )
            return

        # Parse symbol to get indicator code and country (e.g. "gdp_current_usd.USA")
        indicator_code, iso3 = _parse_symbol(symbol)
        if not iso3:
            logger.warning(  # type: ignore[no-any-return]
                "macro_indicator_consumer_unparseable_symbol",
                symbol=symbol,
            )
            return

        # Map ISO3 → ISO2 for entity lookups
        iso2 = _ISO3_TO_ISO2.get(iso3, iso3[:2] if len(iso3) >= 2 else iso3)

        # Most-recent value is the first element (results sorted date descending)
        latest = payload[0]
        incoming_entry = {
            "value": latest.get("Value"),
            "year": latest.get("Period"),
        }

        await self._process_indicator(iso3, iso2, indicator_code, incoming_entry)

    async def _process_indicator(
        self,
        iso3: str,
        iso2: str,
        indicator_code: str,
        incoming_entry: dict[str, Any],
    ) -> None:
        """Update the country entity's macro_indicators metadata for one indicator.

        Strategy:
        - Load the existing macro_indicators dict from entity metadata.
        - Merge the incoming indicator into it.
        - Compare SHA-256 of the merged dict vs the stored hash.
        - Update and dirty the entity only when changed.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
            EntityRepository,
        )

        async with self._sf() as session:
            entity_repo = EntityRepository(session)
            country_entity_id = await entity_repo.find_country_entity(iso2)

            if country_entity_id is None:
                logger.debug(  # type: ignore[no-any-return]
                    "macro_indicator_consumer_country_entity_missing",
                    iso3=iso3,
                    iso2=iso2,
                )
                return

            # Load existing macro_indicators from stored metadata (may be None)
            existing_meta: dict[str, Any] = (
                await entity_repo.get_metadata_field(country_entity_id, "macro_indicators") or {}
            )

            # Merge the new indicator into the existing dict
            merged: dict[str, Any] = {**existing_meta, indicator_code: incoming_entry}

            new_hash = _sha256_hex(json.dumps(merged, sort_keys=True))
            old_hash = await entity_repo.get_metadata_hash(country_entity_id, "macro_indicators")

            if old_hash == new_hash:
                logger.debug(  # type: ignore[no-any-return]
                    "macro_indicator_consumer_no_change",
                    iso3=iso3,
                    iso2=iso2,
                    indicator_code=indicator_code,
                )
                return

            await entity_repo.update_metadata(country_entity_id, {"macro_indicators": merged})
            await session.commit()

        # Produce entity.dirtied.v1 outside DB session — best-effort
        if self._producer is not None:
            self._producer.produce_bytes(
                topic=self._dirtied_topic,
                key=str(country_entity_id).encode(),
                value=json.dumps(
                    {
                        "event_id": str(new_uuid7()),
                        "event_type": "entity.dirtied",
                        "schema_version": 1,
                        "occurred_at": utc_now().isoformat(),
                        "entity_id": str(country_entity_id),
                        "dirty_reason": "macro_indicators_updated",
                        "source_doc_id": None,
                        "correlation_id": None,
                    },
                ).encode(),
            )

        s7_macro_indicator_updates_total.labels(country=iso2).inc()
        logger.info(  # type: ignore[no-any-return]
            "macro_indicator_consumer_updated",
            iso3=iso3,
            iso2=iso2,
            indicator_code=indicator_code,
            entity_id=str(country_entity_id),
        )

    async def _download_envelope(
        self,
        bucket: str | None,
        object_key: str | None,
        *,
        symbol: str = "",
    ) -> dict[str, Any] | None:
        """Download and parse the canonical NDJSON passthrough envelope from MinIO."""
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
                "macro_indicator_consumer_malformed_envelope",
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
                "macro_indicator_consumer_storage_error",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            raise

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
        # TTL = 7 days (604,800 s) — covers the longest polling interval in the
        # system to prevent dedup-key expiry causing re-delivered offsets to be
        # processed twice.
        await self._dedup_client.set(key, "1", ex=7 * 86400)

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "macro_indicator_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "macro_indicator_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "macro_indicator_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "macro_indicator_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialise Confluent Avro wire-format or fall back to JSON (BP-122)."""
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
