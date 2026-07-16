"""Kafka consumer that materialises the EODHD earnings calendar into Postgres.

fix/data-coverage-warns — populate the ``earnings_calendar`` table (0 rows on
prod) that already feeds the screener ``next_earnings_date`` column via
``fundamentals_snapshot_writer.fetch_next_earnings_date``.

WHY A DEDICATED CONSUMER (mirrors InsiderTransactionsConsumer):
  ``earnings_calendar`` is a passthrough dataset on the shared
  ``market.dataset.fetched`` topic (``DatasetType.EARNINGS_CALENDAR`` in
  market-ingestion). The fundamentals consumer ignores any message whose
  ``dataset_type != "fundamentals"``. A small focused consumer keeps the two
  unrelated payloads untangled.

CRITICAL — GLOBAL FETCH (differs from the insider consumer):
  EODHD ``/calendar/earnings`` is a SINGLE global fetch: ONE message contains
  MANY companies. ``envelope["payload"]`` is a DICT shaped like::

      {"type": "Earnings",
       "earnings": [
           {"code": "AAPL.US", "report_date": "2026-02-01",
            "date": "2025-12-31", "before_after_market": "AfterMarket",
            "currency": "USD", "estimate": 2.1, "actual": null}, ...]}

  Each row carries its OWN ``code`` (``TICKER.EXCHANGE``) — we resolve EACH
  row to an instrument, not a single envelope symbol. Rows whose instrument
  is not in our universe are SKIPPED (counter only), NEVER dead-lettered.

IDEMPOTENCY:
  * Event-level: ``ingestion_events.create_if_not_exists(event_id, ...)``
    (ON CONFLICT DO NOTHING) protects against Kafka redelivery, plus a
    content-hash short-circuit for unchanged re-fetches (BP-035).
  * Row-level: every upsert uses ON CONFLICT (instrument_id, report_date)
    DO UPDATE with COALESCE (see PgEarningsCalendarRepository) — report_date
    is the natural upsert key.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, cast

import common.ids  # type: ignore[import-untyped]
from market_data.domain._ticker_normalize import _normalize_ticker
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

_SCHEMA_DIR = find_schema_dir()
_TOPIC = "market.dataset.fetched"
_DATASET_TYPE = "earnings_calendar"
_GROUP_ID = "market-data-earnings-calendar"


def _coerce_decimal(value: Any) -> Decimal | None:
    """Best-effort coercion of an EODHD numeric to Decimal.

    EODHD ships strings, ints, floats, ``None`` and the occasional empty
    string. Returns ``None`` for any unparseable input rather than raising
    so a single malformed row does not poison the rest of the payload.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _coerce_date(value: Any) -> date | None:
    """Parse an ISO-8601 date string; tolerate empty / None / non-string."""
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_code(code: Any) -> tuple[str, str] | None:
    """Split an EODHD ``code`` (``TICKER.EXCHANGE``) into ``(symbol, exchange)``.

    EODHD earnings rows carry codes like ``"AAPL.US"`` or ``"BRK-B.US"``. We
    split on the LAST ``"."`` so multi-class dot-form tickers (already handled
    by ``_normalize_ticker``) survive — only the trailing exchange suffix is
    peeled off. The suffix is passed straight through as the exchange
    (EODHD ``US`` -> instrument exchange ``US``); other suffixes pass through
    unchanged. Returns ``None`` for missing / malformed / suffix-less codes.
    """
    if not isinstance(code, str) or "." not in code:
        return None
    raw_ticker, _, suffix = code.rpartition(".")
    symbol = _normalize_ticker(raw_ticker)
    exchange = suffix.strip().upper()
    if not symbol or not exchange:
        return None
    return symbol, exchange


class EarningsCalendarConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Materialises the global earnings calendar from object storage into Postgres.

    Filters the shared ``market.dataset.fetched`` topic to
    ``dataset_type=earnings_calendar``. Every other dataset is no-oped.
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

    # ── abstract implementations ──────────────────────────────────────────────

    async def get_unit_of_work(self) -> Any:  # type: ignore[override]
        # BP-590: reset to a fresh UoW per message so that a failed previous
        # message does not leak a stale session into the next call.
        uow = self._uow_factory()
        self._current_uow = uow
        return uow

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        # The envelope is published as Avro on confluent-format topics; fall
        # back to plain JSON for unit tests and dev producers.
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
        # ``_handle_message`` before ``_handle_failure`` dispatches here).
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="earnings_calendar_consumer", payload=payload)
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
            await uow.failed_tasks.create(
                task_type="earnings_calendar_consumer_dead",
                payload=payload,
                max_attempts=0,
            )
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
        """Materialise one global earnings-calendar envelope into the database."""
        # ── 1. Dataset gate ──────────────────────────────────────────────────
        # The fundamentals/quotes/ohlcv/insider envelopes also arrive on this
        # topic; silently skip everything that is not ours.
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            return

        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active UoW")

        # ── 2. Event-level dedup (BP-035) ────────────────────────────────────
        event_id = value.get("event_id", "")
        sha256 = value.get("canonical_ref_sha256") or ""
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("earnings_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("earnings_consumer.duplicate_event", event_id=str(event_id)[:8])
            return

        # ── 3. Pull the claim-check payload from object storage ─────────────
        bucket = value.get("canonical_ref_bucket")
        object_key = value.get("canonical_ref_key")
        if not bucket or not object_key:
            raise MalformedDataError("Missing canonical_ref_bucket / canonical_ref_key in envelope")
        if self._object_storage is None:
            raise StorageUnavailableError("Object storage is not configured")
        try:
            raw = await self._object_storage.get_bytes(bucket, object_key)
        except Exception as exc:
            raise StorageUnavailableError(f"S3 download failed: {exc}") from exc

        # The canonical envelope is one NDJSON line wrapping the EODHD payload.
        try:
            envelope = json.loads(raw.decode().splitlines()[0])
        except (ValueError, IndexError) as exc:
            raise MalformedDataError(f"Earnings envelope parse failed: {exc}") from exc

        # ── 4. Parse rows + resolve each row's code to an instrument ─────────
        rows_to_insert = await self._build_rows(uow, envelope)
        inserted = await uow.earnings_calendar.insert_batch(rows_to_insert)  # type: ignore[attr-defined]

        # R10: structlog only.
        logger.info(
            "earnings_consumer.batch_ingested",
            inserted=inserted,
            fetched_at=envelope.get("fetched_at") or datetime.now(tz=UTC).isoformat(),
        )

    async def _build_rows(self, uow: UnitOfWork, envelope: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse ``envelope["payload"]["earnings"]`` into repo rows.

        Extracted from ``process_message`` so the parsing/resolution logic is
        unit-testable in isolation with a fake UoW (no Kafka / S3 needed).
        Rows whose ``code`` cannot be parsed, whose ``report_date`` is missing,
        or whose instrument is not in our universe are SKIPPED (counters).
        """
        payload = envelope.get("payload")
        # EODHD returns ``{"type": "Earnings", "earnings": [...]}``. Empty /
        # missing earnings list is a normal quiet-window case, not malformed.
        if not isinstance(payload, dict):
            if payload in (None, [], ""):
                logger.info("earnings_consumer.empty_payload")
                return []
            raise MalformedDataError(f"Earnings payload must be a dict, got {type(payload).__name__}")
        earnings = payload.get("earnings")
        if not isinstance(earnings, list):
            if earnings in (None, {}):
                logger.info("earnings_consumer.empty_payload")
                return []
            raise MalformedDataError(f"Earnings list must be a list, got {type(earnings).__name__}")

        # Per-message instrument-resolution cache: distinct codes are resolved
        # once (a code repeats across scheduled report/estimate variants), so a
        # 5000-row global fetch does at most ``len(distinct codes)`` DB reads.
        # ``None`` value = resolved-and-absent (not in our universe).
        resolved: dict[tuple[str, str], str | None] = {}
        rows_to_insert: list[dict[str, Any]] = []
        skipped_malformed = 0
        skipped_unknown = 0

        for row in earnings:
            if not isinstance(row, dict):
                skipped_malformed += 1
                continue

            parsed = _parse_code(row.get("code"))
            report_date = _coerce_date(row.get("report_date"))
            if parsed is None or report_date is None:
                # Missing code or report_date → cannot form the natural key.
                skipped_malformed += 1
                continue

            symbol, exchange = parsed
            cache_key = (symbol, exchange)
            if cache_key not in resolved:
                instrument = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
                resolved[cache_key] = instrument.id if instrument is not None else None
            instrument_id = resolved[cache_key]
            if instrument_id is None:
                # Instrument not in our universe — skip, never dead-letter.
                skipped_unknown += 1
                continue

            before_after = row.get("before_after_market")
            currency = row.get("currency")
            rows_to_insert.append(
                {
                    "id": common.ids.new_uuid7(),
                    "instrument_id": instrument_id,
                    "report_date": report_date,
                    "fiscal_date": _coerce_date(row.get("date")),
                    "eps_estimate": _coerce_decimal(row.get("estimate")),
                    "eps_actual": _coerce_decimal(row.get("actual")),
                    "before_after": (str(before_after)[:20] if before_after else None),
                    "currency": (str(currency)[:10] if currency else None),
                }
            )

        logger.info(
            "earnings_consumer.rows_parsed",
            total_rows=len(earnings),
            resolved=len(rows_to_insert),
            skipped_malformed=skipped_malformed,
            skipped_unknown_instrument=skipped_unknown,
        )
        return rows_to_insert
