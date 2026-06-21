"""Fundamentals materializer Kafka consumer."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text

from market_data.domain._ticker_normalize import _normalize_ticker
from market_data.domain.entities import FundamentalsRecord, Instrument, Security
from market_data.domain.enums import FundamentalsSection, PeriodType
from market_data.domain.events import InstrumentCreated
from market_data.domain.value_objects import InstrumentFlags
from market_data.infrastructure.db.fundamentals_snapshot_writer import (
    _most_recent_financial_row_with_period,
    derive_fundamentals_snapshot,
    fetch_next_earnings_date,
    upsert_snapshot,
)
from market_data.infrastructure.db.metric_extractor import extract_metrics
from market_data.infrastructure.messaging.outbox.dispatcher import EVENT_TOPIC_MAP, event_to_outbox_payload
from market_data.infrastructure.metrics.prometheus import fundamentals_consumer_processing_ms
from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig, FailureInfo  # type: ignore[import-untyped]
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import MalformedDataError, StorageUnavailableError  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import find_schema_dir  # type: ignore[import-untyped]
from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_data.application.ports.uow import UnitOfWork
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)

# PLAN-0057 QA-iter1 F-SEC-01: format regexes for the EODHD identifier suite
# extracted by ``_g`` below. Module-scoped so they compile once and avoid the
# per-message function-local recompile (also keeps ruff N806 happy).
_CUSIP_RE_PAT = re.compile(r"^[A-Z0-9]{9}$")
_FIGI_RE_PAT = re.compile(r"^[A-Z0-9]{12}$")
_LEI_RE_PAT = re.compile(r"^[A-Z0-9]{20}$")
_PRIMARY_TICKER_RE_PAT = re.compile(r"^[A-Z0-9.\-:]{1,20}$")
_ISIN_RE_PAT = re.compile(r"^[A-Z0-9]{12}$")


_SCHEMA_DIR = find_schema_dir()
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


class FundamentalsConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Materializes fundamentals datasets from object storage into the database.

    Dedup mixin is belt-and-braces over the consumer's natural-key
    ``create_if_not_exists()`` idempotency.  The mixin protects against expensive
    ML/HTTP work on Kafka rebalance re-delivery; the natural key protects rows.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
        dedup_client: ValkeyClient | None = None,
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._current_uow: UnitOfWork | None = None
        self._dedup_client = dedup_client
        self._dedup_prefix = f"market_data:dedup:{_GROUP_ID}"
        # S3 prefetch scratch-pad: bytes downloaded BEFORE the UoW is entered so
        # the DB connection is not held during S3 network I/O (100-500 ms).
        # Set by _handle_message, consumed and cleared by _process_message_inner.
        self._prefetched_bytes: bytes | None = None

    # ── abstract implementations ──────────────────────────────────────────────

    async def _handle_message(self, msg: Any) -> None:  # type: ignore[override]
        """Pre-fetch S3 object BEFORE acquiring the UoW so the DB connection is
        not held during S3 network I/O (100-500 ms per message).

        Strategy:
        1. Deserialize the raw Kafka value (duplicate of what the base class
           does, but cheap — it is a JSON/Avro parse, not a network call).
        2. If this is a fundamentals dataset message, download the S3 object
           and store the raw bytes in ``_prefetched_bytes``.
        3. Delegate to the base-class ``_handle_message`` which opens the UoW,
           runs dedup, and calls ``process_message``.
        4. ``_process_message_inner`` reads ``_prefetched_bytes`` and skips the
           ``get_bytes`` call that would otherwise hold the connection.
        5. Clear ``_prefetched_bytes`` after use (or on any exit path).
        """
        topic: str = msg.topic()
        schema_path = self.get_schema_path(topic)
        raw_value: bytes = msg.value()
        self._prefetched_bytes = None  # reset for every message

        try:
            value: dict[str, Any] = self.deserialize_value(raw_value, schema_path)
        except Exception:
            # Let the base class handle the deserialization error on its own
            # re-parse; we just fall through without pre-fetching.
            await super()._handle_message(msg)
            return

        if value.get("dataset_type") == _DATASET_TYPE and self._object_storage is not None:
            bucket = value.get("canonical_ref_bucket", "")
            object_key = value.get("canonical_ref_key", "")
            if bucket and object_key:
                try:
                    self._prefetched_bytes = await self._object_storage.get_bytes(bucket, object_key)
                    logger.debug(
                        "fundamentals_consumer.s3_prefetched",
                        bucket=bucket,
                        key=object_key,
                        size=len(self._prefetched_bytes),
                    )
                except Exception as exc:
                    raise StorageUnavailableError(f"S3 prefetch failed: {exc}") from exc

        try:
            await super()._handle_message(msg)
        finally:
            self._prefetched_bytes = None

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

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        # F-004 (idle-in-transaction leak): write via a FRESH, committed UoW —
        # NOT ``self._current_uow`` (already rolled-back + closed by base
        # ``_handle_message`` before ``_handle_failure`` dispatches here). The
        # stale-UoW write left the backend ``idle in transaction`` (uncommitted).
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="fundamentals_consumer", payload=payload)
            await uow.commit()
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:
        # F-004: persist the dead-letter row via a fresh committed UoW.
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="fundamentals_consumer_dead", payload=payload, max_attempts=0)
            await uow.commit()

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
        """Materialise fundamentals sections from the claim-check into the database.

        PLAN-0102 T-W6-03 / BP-617: wall-clock wrapper that records every
        per-message processing duration into the
        ``fundamentals_consumer_processing_ms`` histogram so we can chart the
        tail and pre-empt the next DLQ wave instead of discovering it post-hoc.
        We use ``time.monotonic()`` (not ``time.time()``) so wall-clock jumps
        (NTP step / VM resume) cannot poison the histogram. The metric is
        recorded in BOTH success and failure paths because a 90 s timeout
        re-raise is precisely the data point we want to capture.
        """
        start = time.monotonic()
        try:
            await self._process_message_inner(key, value, headers)
        finally:
            elapsed_ms = (time.monotonic() - start) * 1_000.0
            fundamentals_consumer_processing_ms.observe(elapsed_ms)

    async def _process_message_inner(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Inner processing — see ``process_message`` docstring for timing rationale."""
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

        # Content-hash dedup: check BEFORE inserting so exists_by_content_hash
        # does not find the record we are about to insert (BP-035 follow-up).
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("fundamentals_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("fundamentals_consumer.duplicate_event", event_id=str(event_id)[:8])
            return

        bucket = value["canonical_ref_bucket"]
        object_key = value["canonical_ref_key"]
        # PLAN-0089 F2 step 7: canonicalise ticker at the ingestion boundary.
        # See market_data.domain._ticker_normalize for rationale.
        symbol = _normalize_ticker(value["symbol"])
        exchange = value.get("exchange") or ""
        provider_str = value.get("provider", "unknown")

        # Use pre-fetched S3 bytes (downloaded before the UoW was opened by
        # _handle_message so the DB connection was not held during S3 I/O).
        # Fall back to a direct download only when the prefetch was skipped
        # (e.g. tests that call _process_message_inner directly).
        if self._prefetched_bytes is not None:
            raw = self._prefetched_bytes
        else:
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

        # ── Extract company profile metadata early so InstrumentCreated can ──
        # carry the full EODHD identifier suite into S7 / S1.  PLAN-0057 Wave
        # C-2 (closes F-CRIT-04 / F-CRIT-11) extends the previous v2 extraction
        # (Name / ISIN / Description) with the four EODHD General fields that
        # are available on this account: CUSIP, OpenFigi (mapped to ``figi``
        # because the schema uses the OpenFIGI consortium-neutral name), LEI
        # and PrimaryTicker.
        #
        # Reality check: SEDOL is intentionally NOT extracted — the EODHD
        # General endpoint on this account does not expose it.
        general = payload.get("company_profile") or {}

        def _g(key: str) -> str | None:
            """Return ``general[key]`` only if it is a non-empty *string* value.

            EODHD sometimes returns empty strings or unrelated falsy values for
            optional identifiers; we coerce all of those to ``None`` so the
            downstream Avro union[null, string] is emitted correctly and S7 /
            S1 don't materialise empty-string aliases.

            PLAN-0057 QA-iter1 F-SEC-01 / F-QA-02: only accept genuine string
            inputs. Non-string types (numbers, booleans, lists, dicts) are
            rejected to avoid the ``str([1,2,3]).strip() == "[1, 2, 3]"``
            class of poison-alias bugs and to keep blast radius bounded if
            EODHD's response shape mutates.
            """
            if not isinstance(general, dict):
                return None
            value = general.get(key)
            if not isinstance(value, str):
                return None
            text_value = value.strip()
            return text_value or None

        # PLAN-0057 QA-iter1 F-SEC-01: format-validate the EODHD identifiers.
        # An attacker controlling the EODHD response (or an EODHD response shape
        # bug) can otherwise inject arbitrary alias text into the entity
        # resolution graph. CUSIP/FIGI/LEI have well-defined formats; we reject
        # anything that doesn't match. Names/descriptions are length-bounded
        # because they are truncated downstream anyway. Regex constants are
        # defined at module scope (see file top) and referenced here.
        def _vfmt(value: str | None, regex: re.Pattern[str], field: str) -> str | None:
            if value is None:
                return None
            up = value.upper()
            if not regex.fullmatch(up):
                logger.warning(
                    "fundamentals_invalid_identifier",
                    field=field,
                    value=value[:64],  # bound log payload
                    symbol=symbol,
                )
                return None
            return up

        def _bound(value: str | None, max_len: int) -> str | None:
            if value is None:
                return None
            return value[:max_len]

        company_name: str | None = _bound(_g("Name"), 500)
        company_isin: str | None = _vfmt(_g("ISIN"), _ISIN_RE_PAT, "isin")
        company_description: str | None = _bound(_g("Description"), 4000)
        # Wave C-2 additions — all nullable, all flow through to S7 alias suite.
        company_cusip: str | None = _vfmt(_g("CUSIP"), _CUSIP_RE_PAT, "cusip")
        # EODHD calls it "OpenFigi", schema calls it "figi"
        company_figi: str | None = _vfmt(_g("OpenFigi"), _FIGI_RE_PAT, "figi")
        company_lei: str | None = _vfmt(_g("LEI"), _LEI_RE_PAT, "lei")
        company_primary_ticker: str | None = _vfmt(_g("PrimaryTicker"), _PRIMARY_TICKER_RE_PAT, "primary_ticker")

        # Resolve or create instrument.
        #
        # PLAN-0057 QA-iter1 F-DS-02 / F-DATA-02 / F-DS-07: ``market.instrument.created``
        # MUST be emitted on every False→True transition of ``has_fundamentals``,
        # not only when the instrument row is freshly inserted. In the dominant
        # production ordering (ohlcv/quotes arrive before fundamentals), the
        # instrument already exists with ``has_fundamentals=False`` and the
        # legacy elif branch emitted only ``InstrumentUpdated`` — KG never
        # received the enrichment payload, so the placeholder canonical seeded
        # by InstrumentDiscoveredConsumer (Wave D-2) stayed un-enriched
        # forever and the rich alias suite (NAME / CUSIP / FIGI / LEI /
        # PRIMARY_TICKER) was never inserted.
        #
        # We additionally gate the emission on a real EODHD ``Name`` — without
        # one, KG's ``synthesised_name`` path would re-create the placeholder
        # state we are trying to escape.
        instrument: Instrument | None = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        is_first_fundamentals = instrument is None or not instrument.flags.has_fundamentals
        if instrument is None:
            security = await uow.securities.upsert(Security(name=symbol))
            instrument = Instrument(
                security_id=security.id,
                symbol=symbol,
                exchange=exchange,
                flags=InstrumentFlags(has_fundamentals=True),
            )
            instrument = await uow.instruments.upsert(instrument)
        elif not instrument.flags.has_fundamentals:
            updated_flags = InstrumentFlags(
                has_ohlcv=instrument.flags.has_ohlcv,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=True,
            )
            await uow.instruments.update_flags(instrument.id, updated_flags)

        if is_first_fundamentals:
            if company_name and company_name.strip():
                created_event = InstrumentCreated(
                    instrument_id=instrument.id,
                    security_id=instrument.security_id,
                    symbol=symbol,
                    exchange=exchange,
                    name=company_name,
                    isin=company_isin,
                    description=company_description,
                    cusip=company_cusip,
                    figi=company_figi,
                    lei=company_lei,
                    primary_ticker=company_primary_ticker,
                )
                await uow.outbox_events.create(
                    event_type=created_event.event_type,
                    topic=EVENT_TOPIC_MAP[created_event.event_type],
                    payload=event_to_outbox_payload(created_event),
                    # PLAN-0057-followup Wave B (F-DATA-06): pin every
                    # ``market.instrument.created`` event for a given
                    # instrument to the same Kafka partition so the S7
                    # KG consumer observes the enrichment payload in causal
                    # order with the earlier discovered.v1 event.
                    partition_key=str(instrument.id),
                )
            else:
                # No real Name — defer enrichment publication to a later
                # fundamentals refresh (FundamentalsRefreshWorker re-runs).
                # KG canonical (if seeded by discovered.v1) stays in
                # placeholder state until that next refresh provides a real
                # company name.
                logger.warning(
                    "fundamentals_skipped_no_name",
                    instrument_id=str(instrument.id),
                    symbol=symbol,
                    exchange=exchange,
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

        # PLAN-0096 T-W1-02 / BP-545: bump per-instrument fundamentals freshness
        # column inside the same UoW as the section writes. Only bump when at
        # least one section was actually processed — a malformed payload that
        # produced zero rows should not lie about freshness. No outbox event:
        # the column is observational, not a domain event.
        if section_count > 0:
            await uow.instruments.touch_fundamentals_ingest_at(instrument_id, ingested_at)

        # ── F-Q1-03: UPSERT instrument_fundamentals_snapshot ──────────────────
        # WHY here (not in a separate consumer): the snapshot is a derived
        # projection of section data already present in `payload`.  Computing
        # and writing it in the same transaction (same UoW) is the cheapest
        # path and avoids a second DB round-trip in a follow-up consumer.
        #
        # Best-effort: any exception is caught and logged so a snapshot
        # failure never dead-letters the Kafka message.  The outer try/except
        # also protects against errors raised by subclass/test overrides.
        try:
            await self._upsert_fundamentals_snapshot(uow, str(instrument_id), payload)
        except Exception as exc:
            logger.warning(
                "fundamentals_consumer.snapshot_upsert_failed",
                instrument_id=instrument_id,
                error=str(exc),
            )

    async def _upsert_fundamentals_snapshot(
        self,
        uow: Any,
        instrument_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Derive and UPSERT the instrument_fundamentals_snapshot row.

        Separated from process_message so tests can mock or override this method
        without needing a live SQLAlchemy session.  Any exception raised here is
        caught by the caller (process_message) which logs it and continues — the
        snapshot is best-effort.

        WHY protected (not private): test overrides can intercept call arguments
        without touching the DB.
        """
        snap_highlights = payload.get("highlights") or {}
        # PLAN-0095 T-W1-04 / BP-542: capture which periodicity each source row
        # came from so the snapshot writer can record it in the new
        # ``period_type_*`` columns. ``_most_recent_financial_row_with_period``
        # returns ``(row, "ANNUAL" | "QUARTERLY" | None)``.
        snap_cash_flow, _pt_cash_flow = _most_recent_financial_row_with_period(payload.get("cash_flow"))
        snap_income, _pt_income = _most_recent_financial_row_with_period(payload.get("income_statement"))
        snap_balance, _pt_balance = _most_recent_financial_row_with_period(payload.get("balance_sheet"))
        snap_technicals = payload.get("technicals_snapshot") or {}
        # ── WL-4a (PLAN-0089) sections ───────────────────────────────────────
        # Two additional flat-dict sections feed the four new L-4a snapshot
        # columns (analyst_target_price, analyst_consensus_rating,
        # institutional_ownership_pct, short_percent). Both are sparse —
        # small-cap and non-US listings frequently omit either or both.
        snap_analyst_consensus = payload.get("analyst_consensus") or {}
        snap_share_statistics = payload.get("share_statistics") or {}
        # PLAN-0089 Wave L-5c: pass the splits_dividends section so the
        # snapshot writer can extract ``next_dividend_date`` from EODHD
        # ``SplitsDividends.DividendDate``. Absent on ETFs / non-payers.
        snap_splits_dividends = payload.get("splits_dividends") or {}

        # Only derive + upsert when at least one source section is present.
        # Include the new WL-4a + L-5c sections so a payload carrying ONLY
        # analyst, ownership, or calendar data (rare but possible — partial
        # provider re-poll) still triggers the upsert.
        if not (
            snap_highlights
            or snap_cash_flow
            or snap_income
            or snap_balance
            or snap_technicals
            or snap_analyst_consensus
            or snap_share_statistics
            or snap_splits_dividends
        ):
            return

        snap = derive_fundamentals_snapshot(
            highlights=snap_highlights,
            cash_flow=snap_cash_flow,
            income=snap_income,
            balance=snap_balance,
            technicals=snap_technicals,
            analyst_consensus=snap_analyst_consensus,
            share_statistics=snap_share_statistics,
            splits_dividends=snap_splits_dividends,
        )
        # PLAN-0095 T-W1-04 / BP-542: attach the source periodicity tags so the
        # writer persists them into instrument_fundamentals_snapshot.period_type_*.
        snap = {
            **snap,
            "period_type_income": _pt_income,
            "period_type_cash_flow": _pt_cash_flow,
            "period_type_balance": _pt_balance,
        }
        # Access write session via concrete UoW — we are inside the
        # infrastructure layer; the cast is safe here (SLF001).
        write_session_fn = getattr(uow, "_write", None)
        if write_session_fn is None:
            # Mock UoW in unit tests — skip the DB write.
            logger.debug(
                "fundamentals_consumer.snapshot_skip_no_write_session",
                instrument_id=instrument_id,
            )
            return

        # EODHD Technicals rarely includes AverageVolume; fall back to
        # computing it from the last 30 daily OHLCV bars when missing.
        if snap.get("avg_volume_30d") is None:
            row = (
                await write_session_fn().execute(
                    text(
                        "SELECT ROUND(AVG(volume)::numeric, 0)::bigint AS avg_vol "
                        "FROM (SELECT volume FROM ohlcv_bars "
                        "WHERE instrument_id = :iid AND timeframe = '1d' "
                        "ORDER BY bar_date DESC LIMIT 30) sub"
                    ),
                    {"iid": instrument_id},
                )
            ).one_or_none()
            if row and row.avg_vol is not None:
                snap = {**snap, "avg_volume_30d": int(row.avg_vol)}

        # PLAN-0089 Wave L-5c: look up the next future earnings report date
        # in the ``earnings_calendar`` table (best-effort). Until L-5b ships
        # the worker that populates this table, the query typically returns
        # NULL — that is correct and the COALESCE-based UPSERT preserves any
        # previously-recorded value.
        try:
            next_earn = await fetch_next_earnings_date(write_session_fn(), instrument_id)
        except Exception as exc:  # — best-effort lookup; never fail the snapshot
            logger.debug(
                "fundamentals_consumer.next_earnings_lookup_failed",
                instrument_id=instrument_id,
                error=str(exc),
            )
            next_earn = None
        snap = {**snap, "next_earnings_date": next_earn}

        await upsert_snapshot(write_session_fn(), instrument_id, snap)
        logger.info(
            "fundamentals_consumer.snapshot_upserted",
            instrument_id=instrument_id,
            eps_ttm=snap.get("eps_ttm"),
            beta=snap.get("beta"),
            fcf=snap.get("free_cash_flow"),
        )
