"""Consumer 13D-9: Earnings Calendar dataset ingestion via Kafka.

Consumer group: ``kg-earnings-calendar-dataset-group``.
Consumes: ``market.dataset.fetched`` WHERE dataset_type='earnings_calendar'.

Processing:
  1. Filter messages to dataset_type='earnings_calendar'.
  2. Download canonical NDJSON envelope from MinIO (claim-check pattern).
  3. Parse the passthrough envelope: ``{"dataset_type": ..., "symbol": "CALENDAR",
     "source": "finnhub", "payload": {"earningsCalendar": [...]}, "fetched_at": "..."}``.
  4. Upsert each earnings event into ``temporal_events`` with event_type=CORPORATE,
     scope=LOCAL, region=ticker symbol.

Envelope shape from Finnhub (S2 canonical adapter):
  The canonical_ref payload for earnings_calendar contains the raw Finnhub
  ``/calendar/earnings`` response body, or a wrapper dict with an "earningsCalendar" key.
  Each item in the list has fields like:
    - symbol      (str)  company ticker e.g. "AAPL"
    - name        (str)  company name
    - reportDate  (str)  ISO date "2026-05-01"
    - epsEstimate (float | None) expected EPS
    - epsActual   (float | None) reported EPS (None if not yet released)
    - hour        (str)  "bmo" (before market open), "amc" (after market close), ""

WHY filter on epsEstimate is None:
  When epsEstimate is None the earnings date is tentative — Finnhub has no firm
  date yet. These events are not useful for the calendar widget. We skip them to
  avoid cluttering temporal_events with placeholder rows.

Idempotency:
  Natural key = (event_type='corporate', region=ticker, title, active_from::date).
  upsert_by_natural_key handles duplicate ingestion runs safely.

PLAN-0068 Wave A-1.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.ids import new_uuid7  # type: ignore[import-untyped]
from knowledge_graph.domain.enums import EventScope, EventType, ExposureType
from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_earnings_calendar_events_ingested_total,  # type: ignore[attr-defined]
)
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


_DATASET_FETCHED_SCHEMA_PATH = get_schema_path("market.dataset.fetched.avsc")

# Earnings events carry a 7-day residual impact window — company earnings
# typically affect the stock price for several trading days post-release.
_RESIDUAL_IMPACT_DAYS = 7

# Structured data from Finnhub API has full confidence (no NLP uncertainty).
_FINNHUB_CONFIDENCE = 1.0


def _parse_report_date(date_str: str) -> datetime | None:
    """Parse a Finnhub report date string to a UTC-aware datetime.

    Finnhub returns dates in "YYYY-MM-DD" format. The time component is set to
    00:00:00 UTC since Finnhub doesn't always include the exact time — the
    `hour` field ('bmo' / 'amc') can be used to infer AM/PM but we normalise
    to midnight UTC here for the natural-key dedup index, which only uses
    date_trunc('day', ...).

    Returns None if the string cannot be parsed (malformed / empty).
    """
    if not date_str:
        return None
    # Handle both "YYYY-MM-DD" and ISO datetime formats from different Finnhub
    # API versions (some newer responses include "T00:00:00+00:00" suffixes).
    # WHY slice [:10]: regardless of whether the input is a date-only string or
    # a full ISO datetime, the first 10 chars are always "YYYY-MM-DD".
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")  # noqa: DTZ007
        return dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _build_title(symbol: str, name: str, report_date: str, hour: str) -> str:
    """Build a human-readable title for an earnings event.

    Format: "{SYMBOL} Earnings — {report_date} ({timing})"
    Example: "AAPL Earnings — 2026-05-01 (BMO)"

    WHY include both symbol and name: the symbol is needed for the dashboard
    ticker column, the name provides display context. We embed the timing
    (before/after market) because it affects pre-market/after-hours volatility
    and traders need to see it at a glance.
    """
    # Normalise hour code to human-readable string
    timing_map = {
        "bmo": "BMO",  # Before Market Open
        "amc": "AMC",  # After Market Close
        "dmh": "DMH",  # During Market Hours
    }
    timing = timing_map.get(str(hour).lower().strip(), "") if hour else ""
    title = f"{symbol} Earnings — {report_date} ({timing})" if timing else f"{symbol} Earnings — {report_date}"
    # Guard against pathologically long titles (DB constraint: <= 500 chars).
    if len(title) > 500:
        title = title[:497] + "..."
    return title


def _build_description(
    name: str,
    eps_estimate: float | None,
    eps_actual: float | None,
    hour: str,
) -> str:
    """Build a structured description for an earnings event.

    Includes: company name, EPS estimate, EPS actual (if known), market timing.
    Example: "Apple Inc. Earnings Report; EPS Estimate: 1.52; BMO"
    """
    parts: list[str] = []
    if name:
        parts.append(f"{name} Earnings Report")
    if eps_estimate is not None:
        parts.append(f"EPS Estimate: {eps_estimate:.4g}")
    if eps_actual is not None:
        # Compute EPS surprise for enrichment when both values are known
        try:
            surprise = eps_actual - eps_estimate if eps_estimate is not None else None
            direction = "beat" if surprise is not None and surprise >= 0 else "missed"
            if surprise is not None:
                parts.append(f"EPS Actual: {eps_actual:.4g} ({direction} by {abs(surprise):.4g})")
            else:
                parts.append(f"EPS Actual: {eps_actual:.4g}")
        except (TypeError, ValueError):
            parts.append(f"EPS Actual: {eps_actual:.4g}")

    timing_map = {"bmo": "Before Market Open", "amc": "After Market Close", "dmh": "During Market Hours"}
    timing = timing_map.get(str(hour).lower().strip(), "") if hour else ""
    if timing:
        parts.append(timing)

    description = "; ".join(parts)
    return description[:2000]  # Guard against malformed data


class _NoOpUoW:
    """Minimal UoW shim — earnings consumer manages sessions directly."""

    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class EarningsCalendarDatasetConsumer(BaseKafkaConsumer[None]):
    """Consumer 13D-9: Ingest earnings calendar events from market.dataset.fetched.

    Mirrors EconomicEventsDatasetConsumer pattern. Receives pre-fetched Finnhub
    earnings calendar data via the claim-check pattern and upserts rows into
    temporal_events with event_type=CORPORATE, scope=LOCAL.

    Processing per message:
    1. Filter: only ``dataset_type='earnings_calendar'`` is processed.
    2. Download canonical NDJSON envelope from MinIO.
    3. Parse envelope → extract raw Finnhub earningsCalendar list.
    4. Upsert each event into temporal_events; link to company entity by ticker.

    Args:
    ----
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
        self._dedup_prefix = f"kg:earnings_calendar:{config.group_id}"

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Process a market.dataset.fetched event for earnings calendar data."""
        dataset_type = str(value.get("dataset_type", ""))
        if dataset_type != "earnings_calendar":
            # Not an earnings calendar message — skip silently.
            # This consumer shares the market.dataset.fetched topic with other
            # consumers (economic events, fundamentals, OHLCV, etc.), so most
            # messages will not be for us.
            return

        symbol = str(value.get("symbol", ""))
        bucket = value.get("canonical_ref_bucket")
        object_key = value.get("canonical_ref_key")

        # Download the canonical NDJSON envelope from MinIO (claim-check pattern)
        envelope = await self._download_envelope(bucket, object_key, symbol=symbol)
        if envelope is None:
            return

        # The envelope payload may be:
        #   (a) A list directly: [{"symbol": "AAPL", ...}, ...]
        #   (b) A dict with "earningsCalendar" key: {"earningsCalendar": [...]}
        #   (c) A dict with "payload" key (canonical wrapper): {"payload": [...]}
        # We handle all three shapes defensively.
        raw_payload = envelope.get("payload", envelope)
        if isinstance(raw_payload, dict):
            # Shape (b): Finnhub raw response wrapped in the canonical envelope
            events: list[dict[str, Any]] = raw_payload.get("earningsCalendar", [])
        elif isinstance(raw_payload, list):
            # Shape (a) or (c) unwrapped: direct list
            events = raw_payload
        else:
            events = []

        if not events:
            logger.debug(  # type: ignore[no-any-return]
                "earnings_calendar_consumer_empty_payload",
                symbol=symbol,
            )
            return

        await self._process_events(events, symbol)

    async def _process_events(
        self,
        events: list[dict[str, Any]],
        source_symbol: str,
    ) -> None:
        """Upsert all earnings events into temporal_events."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import (
            EntityRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
            EntityEventExposureRepository,
            TemporalEventRepository,
        )

        ingested = 0
        ingested_by_ticker: dict[str, int] = {}

        async with self._sf() as session:
            event_repo = TemporalEventRepository(session)
            exposure_repo = EntityEventExposureRepository(session)
            entity_repo = EntityRepository(session)

            for ev in events:
                ticker = self._upserted_ticker(ev)
                if ticker is None:
                    continue  # No ticker — can't form a natural key

                upserted = await self._upsert_event(
                    ev=ev,
                    ticker=ticker,
                    event_repo=event_repo,
                    exposure_repo=exposure_repo,
                    entity_repo=entity_repo,
                )
                if upserted:
                    ingested += 1
                    ingested_by_ticker[ticker] = ingested_by_ticker.get(ticker, 0) + 1

            await session.commit()

        # Increment per-ticker Prometheus counters outside the session
        for ticker, count in ingested_by_ticker.items():
            s7_earnings_calendar_events_ingested_total.labels(ticker=ticker).inc(count)

        logger.info(  # type: ignore[no-any-return]
            "earnings_calendar_consumer_processed",
            source_symbol=source_symbol,
            ingested=ingested,
            total_events=len(events),
        )

    def _upserted_ticker(self, ev: dict[str, Any]) -> str | None:
        """Extract and validate the ticker symbol from an earnings event dict.

        Returns None if ticker is absent or empty.
        """
        ticker = ev.get("symbol") or ev.get("ticker") or ""
        if not isinstance(ticker, str) or not ticker.strip():
            return None
        return ticker.strip().upper()

    async def _upsert_event(
        self,
        ev: dict[str, Any],
        ticker: str,
        event_repo: Any,
        exposure_repo: Any,
        entity_repo: Any,
    ) -> bool:
        """Process a single Finnhub earnings event dict.

        Returns True if the event was upserted; False if skipped.

        Skip conditions:
          - epsEstimate is None (tentative date — no confirmed reporting schedule)
          - reportDate is missing or unparseable

        The natural key is: (event_type='corporate', region=ticker, title, active_from::date).
        This ensures one row per ticker per earnings date, with UPSERT semantics
        on repeated ingestion.
        """
        # Skip tentative events where no EPS estimate is provided yet.
        # These indicate Finnhub has a placeholder but no confirmed report date.
        eps_estimate = ev.get("epsEstimate")
        if eps_estimate is None:
            return False

        # Parse the report date — required for natural key and display
        report_date_str = str(ev.get("reportDate") or ev.get("date") or "")
        active_from = _parse_report_date(report_date_str)
        if active_from is None:
            logger.warning(  # type: ignore[no-any-return]
                "earnings_calendar_consumer_invalid_date",
                ticker=ticker,
                raw_date=ev.get("reportDate"),
            )
            return False

        # Build title (natural key component) and description
        name = str(ev.get("name") or ticker)
        hour = str(ev.get("hour") or "")
        title = _build_title(ticker, name, report_date_str[:10], hour)

        eps_actual: float | None = ev.get("epsActual")
        description = _build_description(name, eps_estimate, eps_actual, hour)

        # active_until: 1 trading day after the report (earnings volatility window)
        from datetime import timedelta

        active_until = active_from + timedelta(hours=24)

        event_id = new_uuid7()
        # upsert_by_natural_key returns the canonical DB event_id (existing or new).
        # The exposure FK must reference this id.
        db_event_id: UUID = await event_repo.upsert_by_natural_key(
            event_id=event_id,
            event_type=EventType.CORPORATE,  # type: ignore[attr-defined]
            scope=EventScope.LOCAL,
            region=ticker,  # ticker is the local identifier for company events
            title=title,
            description=description,
            active_from=active_from,
            active_until=active_until,
            residual_impact_days=_RESIDUAL_IMPACT_DAYS,
            confidence=_FINNHUB_CONFIDENCE,
        )

        # Link to the company's canonical entity if it exists in the KG.
        # WHY find_instrument_by_ticker: earnings events are company-specific
        # (LOCAL scope), so we link to the company entity directly. This enables
        # the entity exposure filter on GET /api/v1/temporal-events (entity_id
        # query param → join entity_event_exposures).
        instrument_record = await entity_repo.find_instrument_by_ticker(ticker)
        company_entity_id: UUID | None = instrument_record.entity_id if instrument_record is not None else None
        if company_entity_id is not None:
            exposure_id = new_uuid7()
            await exposure_repo.upsert(
                exposure_id=exposure_id,
                event_id=db_event_id,
                entity_id=company_entity_id,
                exposure_type=ExposureType.DIRECTLY_AFFECTED,
                confidence=_FINNHUB_CONFIDENCE,
            )

        logger.debug(  # type: ignore[no-any-return]
            "earnings_calendar_consumer_event_upserted",
            ticker=ticker,
            title=title,
            eps_estimate=eps_estimate,
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
        ``{"dataset_type": "earnings_calendar", "symbol": "CALENDAR",
           "source": "finnhub", "payload": {"earningsCalendar": [...]},
           "fetched_at": "..."}``.
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
                "earnings_calendar_consumer_malformed_envelope",
                bucket=bucket,
                object_key=object_key,
                symbol=symbol,
                error=str(exc),
            )
            return None
        except Exception as exc:
            # Transient storage errors (network, timeout) — re-raise so
            # BaseKafkaConsumer does NOT commit the offset.
            logger.warning(  # type: ignore[no-any-return]
                "earnings_calendar_consumer_storage_error",
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
        # TTL = 7 days — earnings calendars are polled weekly; 7 days covers
        # two polling cycles and prevents duplicate processing on restart.
        await self._dedup_client.set(key, "1", ex=7 * 86400)

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "earnings_calendar_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "earnings_calendar_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "earnings_calendar_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "earnings_calendar_consumer_retry_not_supported",
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
