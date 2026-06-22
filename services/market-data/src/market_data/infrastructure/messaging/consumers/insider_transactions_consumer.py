"""Kafka consumer that materialises EODHD insider transactions into Postgres.

PLAN-0089 Wave L-4b (T-WL4B-02).

WHY A DEDICATED CONSUMER (not extending FundamentalsConsumer):
  ``insider_transactions`` is a passthrough dataset on the shared
  ``market.dataset.fetched`` topic (see ``DatasetType.INSIDER_TRANSACTIONS``
  in market-ingestion). The fundamentals consumer ignores any message whose
  ``dataset_type != "fundamentals"`` — adding the insider branch there would
  bloat an already 700-line file and tangle two unrelated payloads. The
  passthrough envelope shape is simpler than the multi-section fundamentals
  payload, so a small focused consumer is preferable.

TOPIC: ``market.dataset.fetched`` (shared with fundamentals/quotes/OHLCV);
DISCRIMINATOR: ``value["dataset_type"] == "insider_transactions"``.

IDEMPOTENCY:
  * Event-level: ``ingestion_events.create_if_not_exists(event_id, ...)``
    (ON CONFLICT DO NOTHING) protects against Kafka redelivery.
  * Row-level: every INSERT uses ``ON CONFLICT DO NOTHING`` on the natural
    key ``(instrument_id, filer_name, transaction_date, transaction_type,
    shares)``. EODHD does not expose a stable transaction id, so the
    natural key is the only handle.

DEDUPLICATION PATH (not the legacy ``BaseKafkaConsumer.is_duplicate`` hook):
  * Dedup is enforced inside ``process_message`` via
    ``ingestion_events.create_if_not_exists(event_id, ...)`` (Postgres
    ON CONFLICT DO NOTHING) — see the call near the top of ``process_message``.
  * Per-message UoW reset happens in ``get_unit_of_work`` (this file,
    around line 151), so ``_current_uow`` is always fresh and a prior
    message's session never leaks into the next call (BP-590).
  * Row-level idempotency is doubly enforced by the UNIQUE constraint on
    ``(instrument_id, filer_name, transaction_date, transaction_type, shares)``
    with ON CONFLICT DO NOTHING on every INSERT.
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
_DATASET_TYPE = "insider_transactions"
_GROUP_ID = "market-data-insider-transactions"

# EODHD ``transactionType`` field uses single-letter codes — see
# https://eodhd.com/financial-apis/stock-market-insider-transactions/.
# Anything else collapses into ``OTHER`` (CHECK constraint admits 4 values).
_TYPE_MAP: dict[str, str] = {
    "P": "BUY",  # Purchase
    "S": "SELL",  # Sale
    "G": "GIFT",  # Gift
    "BUY": "BUY",
    "SELL": "SELL",
    "GIFT": "GIFT",
}


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


def _coerce_transaction_type(raw: Any) -> str:
    """Map raw EODHD transaction code to our CHECK-constraint vocabulary."""
    if not isinstance(raw, str):
        return "OTHER"
    return _TYPE_MAP.get(raw.strip().upper(), "OTHER")


def _coerce_date(value: Any) -> date | None:
    """Parse an ISO-8601 date string; tolerate empty / None / non-string."""
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _compute_net_value(
    *,
    shares: Decimal | None,
    price_per_share: Decimal | None,
    transaction_type: str,
) -> Decimal | None:
    """Compute ``net_value_usd`` = shares * price, sign by direction.

    BUY → positive (cash out, position up); SELL/GIFT → negative. OTHER
    keeps the raw sign (no flip). Returns ``None`` if either input is None
    so the column stays NULL rather than storing a misleading 0.
    """
    if shares is None or price_per_share is None:
        return None
    abs_value = (shares * price_per_share).quantize(Decimal("0.01"))
    if transaction_type in ("SELL", "GIFT"):
        return -abs_value
    return abs_value


class InsiderTransactionsConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Materialises insider transactions from object storage into Postgres.

    Filters the shared ``market.dataset.fetched`` topic to
    ``dataset_type=insider_transactions``. Every other dataset is no-oped.
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
        # ``_handle_message`` before ``_handle_failure`` dispatches here). The
        # stale-UoW write left the backend ``idle in transaction`` (uncommitted).
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="insider_transactions_consumer", payload=payload)
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
                task_type="insider_transactions_consumer_dead",
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
        """Materialise one insider-transactions envelope into the database."""
        # ── 1. Dataset gate ──────────────────────────────────────────────────
        # The fundamentals/quotes/ohlcv envelopes also arrive on this topic;
        # silently skip everything that is not ours.
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
            logger.debug("insider_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("insider_consumer.duplicate_event", event_id=str(event_id)[:8])
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
            raise MalformedDataError(f"Insider envelope parse failed: {exc}") from exc

        payload = envelope.get("payload")
        if not isinstance(payload, list):
            # EODHD always returns a JSON array. Empty list is normal (no
            # recent insider activity). Non-list → malformed.
            if payload in (None, {}):
                logger.info(
                    "insider_consumer.empty_payload",
                    symbol=value.get("symbol"),
                )
                return
            raise MalformedDataError(f"Insider payload must be a list, got {type(payload).__name__}")

        # ── 4. Resolve the instrument by ticker+exchange ─────────────────────
        # The envelope carries ``symbol`` from the ingestion task. Insider
        # tasks are always exchange="US" today (see initial_seeds.py); fall
        # back to the envelope exchange so the consumer also works if
        # market-ingestion eventually expands to other venues.
        symbol = _normalize_ticker(value.get("symbol") or "")
        exchange = value.get("exchange") or "US"
        if not symbol:
            raise MalformedDataError("Insider envelope missing symbol")

        instrument = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            # Surface as a warning but do not dead-letter — the instrument may
            # be created shortly by a parallel consumer (OHLCV / fundamentals);
            # next refresh will succeed.
            logger.warning(
                "insider_consumer.instrument_not_found",
                symbol=symbol,
                exchange=exchange,
            )
            return

        # ── 5. Build typed rows + delegate to the repo ──────────────────────
        # The repo's insert_batch handles UUIDv7 id generation and the
        # ON CONFLICT DO NOTHING clause. Anything we cannot parse is skipped
        # (counter only) rather than dead-lettering the whole envelope.
        envelope_source = str(envelope.get("source") or "EODHD")[:32]
        rows_to_insert: list[dict[str, Any]] = []
        skipped_malformed = 0
        for row in payload:
            if not isinstance(row, dict):
                skipped_malformed += 1
                continue

            tx_date = _coerce_date(row.get("transactionDate") or row.get("date"))
            shares = _coerce_decimal(row.get("transactionAmount") or row.get("shares"))
            price = _coerce_decimal(row.get("transactionPrice") or row.get("price"))
            tx_type = _coerce_transaction_type(row.get("transactionCode") or row.get("transactionType"))
            filer_name_raw = row.get("ownerName") or row.get("filerName") or ""
            filer_title = row.get("ownerRelationship") or row.get("ownerCikRelationship")

            # Natural-key fields must all be present for ON CONFLICT to work.
            if tx_date is None or shares is None or not filer_name_raw:
                skipped_malformed += 1
                continue

            net = _compute_net_value(shares=shares, price_per_share=price, transaction_type=tx_type)
            rows_to_insert.append(
                {
                    "id": common.ids.new_uuid7(),
                    "instrument_id": instrument.id,
                    "filer_name": str(filer_name_raw)[:255],
                    "filer_title": (str(filer_title)[:255] if filer_title else None),
                    "transaction_date": tx_date,
                    "transaction_type": tx_type,
                    "shares": shares,
                    "price_per_share": price,
                    "net_value_usd": net,
                    "source": envelope_source,
                }
            )

        inserted = await uow.insider_transactions.insert_batch(rows_to_insert)  # type: ignore[attr-defined]

        # R10: structlog only; counters are also handy for the daily worker.
        logger.info(
            "insider_consumer.batch_ingested",
            symbol=symbol,
            exchange=exchange,
            inserted=inserted,
            skipped_malformed=skipped_malformed,
            fetched_at=envelope.get("fetched_at") or datetime.now(tz=UTC).isoformat(),
        )
