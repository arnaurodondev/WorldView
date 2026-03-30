"""Fundamentals materializer Kafka consumer."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from market_data.domain.entities import FundamentalsRecord, Instrument, Security
from market_data.domain.enums import FundamentalsSection, PeriodType
from market_data.domain.events import InstrumentCreated, InstrumentUpdated
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.db.metric_extractor import extract_metrics
from market_data.infrastructure.messaging.outbox.dispatcher import EVENT_TOPIC_MAP, event_to_outbox_payload
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError, StorageUnavailableError  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)

_SCHEMA_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "infra/kafka/schemas"
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "fundamentals"  # market-ingestion: DatasetType.FUNDAMENTALS = "fundamentals" (lowercase)
_GROUP_ID = "market-data-fundamentals"

# Mapping from raw payload section keys → FundamentalsRepository method names
_SECTION_HANDLERS: dict[str, str] = {
    "income_statement": "upsert_income_statement",
    "balance_sheet": "upsert_balance_sheet",
    "cash_flow": "upsert_cash_flow",
    "highlights": "upsert_highlights",  # FIX-F10
    "valuation_ratios": "upsert_valuation_ratios",
    "technicals_snapshot": "upsert_technicals_snapshot",
    "share_statistics": "upsert_share_statistics",
    "splits_dividends": "upsert_splits_dividends",
    "analyst_consensus": "upsert_analyst_consensus",
    "earnings_history": "upsert_earnings_history",
    "earnings_trend": "upsert_earnings_trend",
    "earnings_annual_trend": "upsert_earnings_annual_trend",
    "dividend_history": "upsert_dividend_history",
    "outstanding_shares": "upsert_outstanding_shares",
    "company_profile": "upsert_company_profile",  # FIX-F4
    "institutional_holders": "upsert_institutional_holders",  # FIX-F6
    "fund_holders": "upsert_fund_holders",  # FIX-F6
    "insider_transactions_snapshot": "upsert_insider_transactions_snapshot",  # FIX-F7
}

# Sections that use merge-upsert semantics (additive, not replace)
_MERGE_UPSERT_SECTIONS: frozenset[str] = frozenset({"analyst_consensus"})

# Map section key → FundamentalsSection enum value
_SECTION_ENUM_MAP: dict[str, FundamentalsSection] = {
    "income_statement": FundamentalsSection.INCOME_STATEMENT,
    "balance_sheet": FundamentalsSection.BALANCE_SHEET,
    "cash_flow": FundamentalsSection.CASH_FLOW,
    "highlights": FundamentalsSection.HIGHLIGHTS,
    "valuation_ratios": FundamentalsSection.VALUATION_RATIOS,
    "technicals_snapshot": FundamentalsSection.TECHNICALS_SNAPSHOT,
    "share_statistics": FundamentalsSection.SHARE_STATISTICS,
    "splits_dividends": FundamentalsSection.SPLITS_DIVIDENDS,
    "analyst_consensus": FundamentalsSection.ANALYST_CONSENSUS,
    "earnings_history": FundamentalsSection.EARNINGS_HISTORY,
    "earnings_trend": FundamentalsSection.EARNINGS_TREND,
    "earnings_annual_trend": FundamentalsSection.EARNINGS_ANNUAL_TREND,
    "dividend_history": FundamentalsSection.DIVIDEND_HISTORY,
    "outstanding_shares": FundamentalsSection.OUTSTANDING_SHARES,
    "company_profile": FundamentalsSection.COMPANY_PROFILE,
    "institutional_holders": FundamentalsSection.INSTITUTIONAL_HOLDERS,
    "fund_holders": FundamentalsSection.FUND_HOLDERS,
    "insider_transactions_snapshot": FundamentalsSection.INSIDER_TRANSACTIONS_SNAPSHOT,
}

# Sections whose EODHD payload is {"quarterly": {date: row}, "yearly": {date: row}}
_FINANCIAL_STATEMENT_SECTIONS: frozenset[str] = frozenset(
    {
        "income_statement",
        "balance_sheet",
        "cash_flow",
    }
)

# Sections whose payload is a dict-of-dicts keyed by period code with explicit "date" field
_EARNINGS_TREND_SECTIONS: frozenset[str] = frozenset(
    {
        "earnings_trend",
    }
)

# Sections whose payload is a date-keyed flat dict → one row per date entry
_DATE_KEYED_SERIES_SECTIONS: frozenset[str] = frozenset(
    {
        "earnings_history",
        "earnings_annual_trend",
        "outstanding_shares",
        "dividend_history",
    }
)


def _parse_fundamentals_bytes(raw: bytes) -> dict[str, Any]:
    """Parse JSON-encoded fundamentals bytes into a raw dict."""
    return json.loads(raw.decode())  # type: ignore[no-any-return]


async def _upsert_metrics_for_record(uow: Any, record: FundamentalsRecord) -> None:
    """Extract metrics from a FundamentalsRecord and upsert into fundamental_metrics.

    Uses the same write session (same transaction) as the section upsert.
    Silently skips sections not in the metric catalog.
    """
    # C-008: use isinstance instead of hasattr for explicit type coercion
    as_of_date = (
        record.period_end.date()
        if isinstance(record.period_end, datetime)
        else date.fromisoformat(str(record.period_end))
    )
    metric_rows = extract_metrics(
        instrument_id=record.security_id,  # domain field maps to instrument_id
        section=record.section,
        period_type=str(record.period_type),
        as_of_date=as_of_date,
        data=record.data,
        ingested_at=record.ingested_at,
    )
    if metric_rows:
        await uow.fundamental_metrics.upsert_metrics(metric_rows)


class FundamentalsConsumer(BaseKafkaConsumer[dict]):
    """Materializes fundamentals datasets from object storage into the database."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._current_uow: UnitOfWork | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        if schema_path:
            try:
                return cast("dict[str, Any]", deserialize_confluent_avro(schema_path, raw))
            except Exception:
                logger.debug("avro_deserialize_failed_falling_back_to_json", schema_path=schema_path)
        return cast("dict[str, Any]", json.loads(raw.decode()))

    def get_schema_path(self, topic: str) -> str | None:
        path = _SCHEMA_DIR / "market.dataset.fetched.avsc"
        return str(path) if path.exists() else None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value["event_id"])

    async def is_duplicate(self, event_id: str) -> bool:
        # Dedup is handled atomically via create_if_not_exists at the start of
        # process_message (BP-035). Always return False here so the base class
        # proceeds to process_message regardless.
        return False

    async def mark_processed(self, event_id: str) -> None:
        # No-op: the event_id was already recorded by create_if_not_exists inside
        # process_message before any data was written.
        pass

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        if self._current_uow is None:
            raise RuntimeError("store_failure called outside of processing context — this is a programming error")
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        await self._current_uow.failed_tasks.create(task_type="fundamentals_consumer", payload=payload)
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def dead_letter(self, failure: FailureInfo[dict]) -> None:
        if self._current_uow is not None:
            payload = {
                "event_id": failure.event_id,
                "topic": failure.topic,
                "error": str(failure.last_error),
            }
            await self._current_uow.failed_tasks.create(
                task_type="fundamentals_consumer_dead", payload=payload, max_attempts=0
            )

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Materialise fundamentals sections from the claim-check into the database."""
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            return

        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        # Returns True if newly inserted (new event), False if already processed (duplicate).
        # This replaces the separate is_duplicate() + mark_processed() pattern (BP-035).
        event_id = value.get("event_id", "")
        sha256 = value.get("canonical_ref_sha256") or ""
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("fundamentals_consumer.duplicate_event", event_id=str(event_id)[:8])
            return

        # Content-hash dedup: skip download + DB write when canonical object unchanged.
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("fundamentals_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            return

        bucket = value["canonical_ref_bucket"]
        object_key = value["canonical_ref_key"]
        symbol = value["symbol"]
        exchange = value.get("exchange") or ""
        provider_str = value.get("provider", "unknown")

        # Download from object storage
        if self._object_storage is None:
            raise StorageUnavailableError("Object storage is not configured")
        try:
            raw = await self._object_storage.get_bytes(bucket, object_key)
        except Exception as exc:
            raise StorageUnavailableError(f"S3 download failed: {exc}") from exc

        # Parse as raw dict (multi-section fundamentals payload)
        try:
            payload = _parse_fundamentals_bytes(raw)
        except Exception as exc:
            raise MalformedDataError(f"Fundamentals parse failed: {exc}") from exc

        # Extract company profile metadata early so InstrumentCreated can carry name/isin
        general = payload.get("company_profile") or {}
        company_name: str | None = general.get("Name") if isinstance(general, dict) else None
        company_isin: str | None = general.get("ISIN") if isinstance(general, dict) else None

        # Resolve or create instrument
        instrument: Instrument | None = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            security = await uow.securities.upsert(Security(name=symbol))
            instrument = Instrument(
                security_id=security.id,
                symbol=symbol,
                exchange=exchange,
                flags=InstrumentFlags(has_fundamentals=True),
            )
            instrument = await uow.instruments.upsert(instrument)
            created_event = InstrumentCreated(
                instrument_id=instrument.id,
                security_id=instrument.security_id,
                symbol=symbol,
                exchange=exchange,
                name=company_name,
                isin=company_isin,
            )
            await uow.outbox_events.create(
                event_type=created_event.event_type,
                topic=EVENT_TOPIC_MAP[created_event.event_type],
                payload=event_to_outbox_payload(created_event),
            )
        elif not instrument.flags.has_fundamentals:
            updated_flags = InstrumentFlags(
                has_ohlcv=instrument.flags.has_ohlcv,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=True,
            )
            await uow.instruments.update_flags(instrument.id, updated_flags)
            updated_event = InstrumentUpdated(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange,
                has_ohlcv=instrument.flags.has_ohlcv,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=True,
                fields_updated=("has_fundamentals",),
            )
            await uow.outbox_events.create(
                event_type=updated_event.event_type,
                topic=EVENT_TOPIC_MAP[updated_event.event_type],
                payload=event_to_outbox_payload(updated_event),
            )

        # instrument.id is used as security_id in FundamentalsRecord
        instrument_id = instrument.id
        ingested_at = datetime.now(tz=UTC)

        # Dispatch each section in the payload to the appropriate repo method
        section_count = 0
        for section_key, handler_name in _SECTION_HANDLERS.items():
            section_data = payload.get(section_key)
            if section_data is None:
                continue

            section_enum = _SECTION_ENUM_MAP[section_key]
            handler = getattr(uow.fundamentals, handler_name)

            # ── financial statement sections: one row per fiscal period ──────
            if section_key in _FINANCIAL_STATEMENT_SECTIONS and isinstance(section_data, dict):
                for period_label, period_type_enum in (
                    ("quarterly", PeriodType.QUARTERLY),
                    ("yearly", PeriodType.ANNUAL),
                ):
                    sub: dict = section_data.get(period_label) or {}
                    for date_str, row_data in sub.items():
                        try:
                            period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
                        except (ValueError, TypeError):
                            logger.warning(
                                "fundamentals_consumer.skip_bad_date",
                                section=section_key,
                                date_str=date_str,
                            )
                            continue
                        record = FundamentalsRecord(
                            security_id=instrument_id,
                            section=section_enum,
                            period_end=period_end,
                            period_type=period_type_enum,
                            data=row_data if isinstance(row_data, dict) else {"value": row_data},
                            source=provider_str,
                            ingested_at=ingested_at,
                        )
                        await handler(record)
                        await _upsert_metrics_for_record(uow, record)
                        section_count += 1

            # ── earnings trend: period-code-keyed dict with "date" field ────
            elif section_key in _EARNINGS_TREND_SECTIONS and isinstance(section_data, dict):
                for _period_code, entry in section_data.items():
                    if not isinstance(entry, dict):
                        continue
                    date_str = entry.get("date") or ""
                    try:
                        period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
                    except (ValueError, TypeError):
                        period_end = ingested_at
                    record = FundamentalsRecord(
                        security_id=instrument_id,
                        section=section_enum,
                        period_end=period_end,
                        period_type=PeriodType.QUARTERLY,
                        data=entry,
                        source=provider_str,
                        ingested_at=ingested_at,
                    )
                    await handler(record)
                    await _upsert_metrics_for_record(uow, record)
                    section_count += 1

            # ── date-keyed flat series: one row per date key ────────────────
            elif section_key in _DATE_KEYED_SERIES_SECTIONS and isinstance(section_data, dict):
                for date_str, row_data in section_data.items():
                    try:
                        period_end = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
                    except (ValueError, TypeError):
                        # FIX-F5: year-only strings like "2024" → treat as year-end
                        try:
                            period_end = datetime(int(date_str), 12, 31, tzinfo=UTC)
                        except (ValueError, TypeError):
                            continue
                    period_type_enum = PeriodType.QUARTERLY if section_key == "earnings_history" else PeriodType.ANNUAL
                    record = FundamentalsRecord(
                        security_id=instrument_id,
                        section=section_enum,
                        period_end=period_end,
                        period_type=period_type_enum,
                        data=row_data if isinstance(row_data, dict) else {"value": row_data},
                        source=provider_str,
                        ingested_at=ingested_at,
                    )
                    await handler(record)
                    await _upsert_metrics_for_record(uow, record)
                    section_count += 1

            # ── snapshot sections: single row, period_end = ingested_at ─────
            else:
                record = FundamentalsRecord(
                    security_id=instrument_id,
                    section=section_enum,
                    period_end=ingested_at,
                    period_type=PeriodType.SNAPSHOT,
                    data=section_data if isinstance(section_data, dict) else {"value": section_data},
                    source=provider_str,
                    ingested_at=ingested_at,
                )
                await handler(record)
                await _upsert_metrics_for_record(uow, record)
                section_count += 1

        # ── FIX-F4: Extract company_profile metadata into instruments table ──
        # Note: `general` was already extracted above for InstrumentCreated enrichment.
        if general and isinstance(general, dict):
            await uow.instruments.update_metadata(
                instrument_id,
                {
                    "isin": general.get("ISIN"),
                    "name": general.get("Name"),
                    "sector": general.get("Sector"),
                    "industry": general.get("Industry"),
                    "country": general.get("CountryISO"),
                    "currency_code": general.get("CurrencyCode"),
                },
            )
            # Also enrich the parent Security if we have usable data
            company_name = general.get("Name")
            if company_name:
                existing_security = await uow.securities.find_by_id(instrument.security_id)
                if existing_security is not None:
                    from dataclasses import replace as dc_replace

                    enriched = dc_replace(
                        existing_security,
                        name=company_name,
                        isin=general.get("ISIN") or existing_security.isin,
                        sector=general.get("Sector") or existing_security.sector,
                        industry=general.get("Industry") or existing_security.industry,
                        country=general.get("CountryISO") or existing_security.country,
                        currency=general.get("CurrencyCode") or existing_security.currency,
                    )
                    await uow.securities.upsert(enriched)

        logger.info(
            "fundamentals_consumer.materialized",
            symbol=symbol,
            exchange=exchange,
            instrument_id=instrument_id,
            sections_processed=section_count,
        )
