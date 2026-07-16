"""OHLCV materializer Kafka consumer."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from contracts.canonical.ohlcv import CanonicalOHLCVBar  # type: ignore[import-untyped]
from market_data.domain._ticker_normalize import _normalize_ticker
from market_data.domain.entities import Instrument, OHLCVBar, Quote, Security
from market_data.domain.enums import Provider, Timeframe
from market_data.domain.events import InstrumentDiscovered, InstrumentUpdated
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority
from market_data.infrastructure.messaging.consumers._quote_cache_fanout import schedule_quote_cache_fanout
from market_data.infrastructure.messaging.outbox.dispatcher import EVENT_TOPIC_MAP, event_to_outbox_payload
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    _ASYNCPG_CONN_ERRORS,
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.consumer.errors import (  # type: ignore[import-untyped]
    ConsumerError,
    MalformedDataError,
    StorageUnavailableError,
)
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
_DATASET_TYPE = "ohlcv"  # market-ingestion publishes lowercase DatasetType StrEnum values
_GROUP_ID = "market-data-ohlcv"

# Option B write-through freshness gate: only 1m batches whose latest bar is
# at most this old refresh the `quotes` row.  Historical replays (true
# backfills) carry old bar_dates and are excluded; live scheduler windows
# (which are mislabeled is_backfill=true by the range_start dedupe heuristic)
# pass.  30 min comfortably covers scheduler jitter + consumer lag while still
# rejecting anything that is not "current market" data.
_QUOTE_WRITE_THROUGH_MAX_AGE_SEC = 30 * 60

# Option B (consumer-local micro-batching) — default batch window size.
#
# Heartbeat / liveness reasoning (the controlling safety constraint):
#   ``ConsumerConfig`` defaults are ``max_poll_interval_ms = 600_000`` (600 s),
#   ``session_timeout_ms = 60_000`` (60 s), and the per-message processing
#   watchdog ``message_processing_timeout_s = 45`` s.  In the batched ``run()``
#   override the time *between* successive ``consume()`` calls is the whole
#   batch's processing time, so that window must stay comfortably under
#   ``max.poll.interval.ms`` or librdkafka kicks us out of the group.
#   The measured worst case is ~3 s/message (audit 2026-06-16); at the
#   conservative default of 50 messages that is ~150 s worst case — well under
#   the 600 s poll interval (a >4x safety margin) and the per-message watchdog
#   still dead-letters any single hung message at 45 s.  Override via
#   ``MARKET_DATA_OHLCV_BATCH_MAX`` only after confirming
#   ``batch_max * worst_case_per_msg_s`` stays under ``max.poll.interval.ms``.
_DEFAULT_BATCH_MAX = 50
_BATCH_MAX_ENV = "MARKET_DATA_OHLCV_BATCH_MAX"


def _parse_ohlcv_bytes(raw: bytes) -> list[CanonicalOHLCVBar]:
    """Parse JSONL-encoded OHLCV bytes into a list of CanonicalOHLCVBar."""
    lines = raw.decode().strip().split("\n")
    return [CanonicalOHLCVBar.from_dict(json.loads(line)) for line in lines if line.strip()]


# Provider-side aliases for timeframe strings that are NOT canonical Timeframe
# enum members.  S2 (Yahoo) publishes monthly bars as ``"1mo"`` while our enum
# uses ``ONE_MONTH = "1M"``; without this alias ``Timeframe("1mo")`` raises
# ValueError and the old code silently coerced it to ``ONE_DAY`` — poisoning the
# daily series with mislabeled monthly bars (BP: silent enum-coercion to a
# wrong-but-valid value).  Map the alias here BEFORE the enum lookup.
_TIMEFRAME_ALIASES: dict[str, Timeframe] = {
    "1mo": Timeframe.ONE_MONTH,
}


def _resolve_consumer_timeframe(timeframe_str: str) -> Timeframe:
    """Resolve a provider timeframe string to a canonical Timeframe.

    Accepts both canonical enum values (``"1d"``, ``"1M"`` …) and known
    provider aliases (``"1mo"`` → monthly).  Raises ``MalformedDataError`` for
    anything unknown so the message is dead-lettered (FatalError → DLQ) instead
    of being silently coerced to ``ONE_DAY`` and corrupting the daily series.
    """
    alias = _TIMEFRAME_ALIASES.get(timeframe_str)
    if alias is not None:
        return alias
    try:
        return Timeframe(timeframe_str)
    except ValueError as exc:
        raise MalformedDataError(
            f"Unknown OHLCV timeframe {timeframe_str!r} — refusing to coerce; dead-lettering"
        ) from exc


@dataclass(slots=True)
class _PendingFanout:
    """A quote-cache fan-out deferred until AFTER the shared batch commit.

    In the combined-batch path the Valkey/quote-cache side effects (a
    NON-transactional write) must never fire for a message whose SAVEPOINT was
    rolled back or whose data was not committed.  Instead of routing through
    ``uow.schedule_post_commit`` (whose hook list would also fire a rolled-back
    message's hook on the single outer commit), we collect the fan-out
    parameters locally per released message and fire them only once the outer
    ``uow.commit()`` has succeeded.
    """

    instrument_id: str
    symbol: str
    exchange: str
    quote: Quote


@dataclass(slots=True)
class _MessageOutcome:
    """Per-message result accumulated inside the shared batch transaction.

    Produced by :meth:`_materialize_into_batch` for every message whose SAVEPOINT
    released cleanly.  The bars are NOT upserted per message — they are buffered
    here and flushed in ONE combined ``bulk_upsert_with_priority`` after the
    per-message SAVEPOINT phase (the round-trip / Postgres-pressure win).  A
    duplicate (dedup hit) yields an outcome with ``duplicate=True`` and no bars.
    """

    event_id: str
    duplicate: bool = False
    bars: list[OHLCVBar] = field(default_factory=list)
    fanout: _PendingFanout | None = None


class OHLCVConsumer(ValkeyDedupMixin, BaseKafkaConsumer[dict]):
    """Materializes OHLCV datasets from object storage into the database.

    Dedup mixin is belt-and-braces over the consumer's natural-key
    ``create_if_not_exists()`` idempotency.  The mixin protects against expensive
    ML/HTTP work on Kafka rebalance re-delivery; the natural key protects rows.
    """

    # Option B: maximum number of messages drained per ``consume()`` cycle.
    # Class attribute so it is overridable in tests / subclasses; the env var
    # ``MARKET_DATA_OHLCV_BATCH_MAX`` overrides it at construction time.
    _batch_max_messages: int = _DEFAULT_BATCH_MAX

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        object_storage: ObjectStorage | None,
        config: ConsumerConfig | None = None,
        metrics: Any = None,
        dedup_client: ValkeyClient | None = None,
        price_snapshot_cache: Any = None,  # PriceSnapshotCache | None
    ) -> None:
        if config is None:
            config = ConsumerConfig(group_id=_GROUP_ID, topics=[_TOPIC])
        super().__init__(config, metrics)
        self._uow_factory = uow_factory
        self._object_storage = object_storage
        self._current_uow: UnitOfWork | None = None
        self._dedup_client = dedup_client
        self._dedup_prefix = f"market_data:dedup:{_GROUP_ID}"
        # Option B: per-cycle prefetch cache.  The batch ``run()`` override
        # downloads each message's S3 object concurrently and stashes the bytes
        # here keyed by event_id; ``process_message`` then consumes the cached
        # bytes instead of re-fetching, so the unchanged base ``_handle_message``
        # path (dedup, per-message UoW, timeout watchdog, metrics, mark_processed)
        # is reused verbatim while the slow S3 GET is amortised across the batch.
        self._prefetch_cache: dict[str, bytes] = {}
        self._price_snapshot_cache = price_snapshot_cache
        # Option B write-through: 1m bars also refresh the quotes table, so
        # this consumer needs the same QuoteCache invalidation hot-path as the
        # quotes consumer.  Built lazily from the (Valkey) dedup client.
        self._quote_cache: Any = None  # QuoteCache | None
        if dedup_client is not None:
            from market_data.infrastructure.cache.quote_cache import QuoteCache

            self._quote_cache = QuoteCache(dedup_client)

        # Option B: resolve the per-cycle batch window from the environment,
        # falling back to the conservative class default.  Clamp to >= 1 so a
        # mis-set env var (0, negative, non-numeric) can never wedge the loop
        # into draining nothing.
        env_batch_max = os.environ.get(_BATCH_MAX_ENV)
        if env_batch_max is not None:
            try:
                self._batch_max_messages = max(1, int(env_batch_max))
            except ValueError:
                logger.warning(
                    "ohlcv_consumer.invalid_batch_max_env",
                    value=env_batch_max,
                    fallback=self._batch_max_messages,
                )

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

    async def store_failure(self, failure: FailureInfo[dict]) -> dict:
        # BUG-2026-06-16: the failure write MUST use a FRESH, committed UoW — not
        # ``self._current_uow``.  ``_handle_failure`` runs AFTER the message's
        # ``_handle_message`` UoW has already exited (rolled back + closed its
        # session on the processing exception), so writing through that stale UoW
        # silently no-op'd; and ``PgFailedTaskRepository.create`` only ``execute``s
        # without committing.  Net effect: the OHLCV DLQ/retry audit row was never
        # persisted.  Open our own UoW and commit so the failed_tasks row is durable
        # (offset-blocking already guarantees redelivery; this restores the trail).
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="ohlcv_consumer", payload=payload)
            await uow.commit()
        return payload

    async def update_failure(self, failure: FailureInfo[dict]) -> None:
        pass  # retry tracking is handled by store_failure

    async def _dead_letter_impl(self, failure: FailureInfo[dict]) -> None:
        # Same fix as store_failure: persist the dead-letter row via a fresh
        # committed UoW (the per-message UoW is gone by the time we get here).
        payload = {
            "event_id": failure.event_id,
            "topic": failure.topic,
            "error": str(failure.last_error),
        }
        async with self._uow_factory() as uow:
            await uow.failed_tasks.create(task_type="ohlcv_consumer_dead", payload=payload, max_attempts=0)
            await uow.commit()

    async def get_pending_retries(self) -> list[FailureInfo[dict]]:
        return []

    async def process_message_from_failure(self, failure: FailureInfo[dict]) -> None:
        pass  # retry handled externally

    # ── Option B: split S3 fetch (network-bound, parallelizable) from the DB
    #    materialize (serial, per-UoW).  ``process_message`` stays a thin
    #    wrapper so the base ``_handle_message`` single-message path and every
    #    existing test continue to work unchanged.

    async def _prefetch_dataset(self, value: dict[str, Any]) -> bytes | None:
        """Fetch the claim-check S3 object for *value*, or ``None`` to skip.

        Returns ``None`` for non-OHLCV messages (they are filtered out and never
        materialized).  Raises :class:`StorageUnavailableError` if storage is not
        configured or the download fails — identical to the inline behaviour the
        materialize path previously had, so failure semantics are preserved.

        Hoisted OUT of the serial materialize so the batch ``run()`` override can
        run all of a batch's S3 GETs concurrently via :func:`asyncio.gather`
        BEFORE the serial DB writes.
        """
        if value.get("dataset_type", "") != _DATASET_TYPE:
            return None
        if self._object_storage is None:
            raise StorageUnavailableError("Object storage is not configured")
        bucket = value["canonical_ref_bucket"]
        object_key = value["canonical_ref_key"]
        try:
            return await self._object_storage.get_bytes(bucket, object_key)
        except Exception as exc:
            raise StorageUnavailableError(f"S3 download failed: {exc}") from exc

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Materialise OHLCV bars from the claim-check into the database.

        Thin wrapper around :meth:`_materialize`.  It only forwards a
        batch-prefetched S3 object (keyed by event_id) when one is present; the
        single-message path passes ``None`` and :meth:`_materialize` fetches
        inline AFTER the dedup checks — preserving the original dedup-before-fetch
        ordering byte-for-byte (a deduped message never triggers an S3 GET).
        """
        if value.get("dataset_type", "") != _DATASET_TYPE:
            return
        # Option B: reuse a batch-prefetched S3 object when present (keyed by
        # event_id).  Absent (single-message path / tests) → None, and
        # _materialize fetches inline only if the message survives dedup.
        event_id_raw = value.get("event_id")
        cache_key = str(event_id_raw) if event_id_raw else None
        prefetched: bytes | None = None
        if cache_key is not None and cache_key in self._prefetch_cache:
            prefetched = self._prefetch_cache.pop(cache_key)
        await self._materialize(key, value, headers, prefetched)

    async def _materialize(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
        prefetched: bytes | None,
    ) -> None:
        """Materialise OHLCV bytes into the database (serial, per-UoW).

        ``prefetched`` is the S3 object bytes already downloaded by the batch
        ``run()`` override (``None`` on the single-message path).  Dedup runs
        FIRST; the S3 fetch happens only AFTER a message survives dedup, falling
        back to an inline :meth:`_prefetch_dataset` when no prefetched bytes were
        supplied — identical to the original dedup-before-fetch ordering.
        """
        dataset_type = value.get("dataset_type", "")
        if dataset_type != _DATASET_TYPE:
            return

        uow = self._current_uow
        if uow is None:
            raise RuntimeError("process_message called without an active unit of work — this is a programming error")

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        # Returns True if newly inserted (new event), False if already processed (duplicate).
        # This replaces the separate is_duplicate() + mark_processed() pattern (BP-035).
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in message")
        event_id = str(event_id_raw)
        sha256 = value.get("canonical_ref_sha256") or ""

        # Content-hash dedup: check BEFORE inserting the event so that
        # exists_by_content_hash does not find the record we are about to insert
        # (BP-035 follow-up: create_if_not_exists stores sha256 immediately).
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("ohlcv_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            # Still record event_id so repeated deliveries are fast-path deduped.
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return

        # Atomic event-id dedup: INSERT … ON CONFLICT DO NOTHING … RETURNING.
        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("ohlcv_consumer.duplicate_event", event_id=str(event_id)[:8])
            return

        # PLAN-0089 F2 step 7: canonicalise ticker at the ingestion boundary so
        # the DB only ever holds the dot-form (BRK.B, not BRK-B/BRK/B).  Read
        # paths intentionally do NOT renormalise — they trust the DB form.
        symbol = _normalize_ticker(value["symbol"])
        exchange = value.get("exchange") or ""
        provider_str = value.get("provider", "unknown")
        timeframe_str = value.get("timeframe") or "1d"

        # S3 object bytes — supplied by the batch ``run()`` override's concurrent
        # prefetch, or fetched inline here on the single-message path.  The fetch
        # happens AFTER dedup so a duplicate/unchanged message never triggers an
        # S3 GET (preserves the original ordering and the "deduped → no download"
        # invariant the unit tests assert).
        raw = prefetched if prefetched is not None else await self._prefetch_dataset(value)
        if raw is None:
            # _prefetch_dataset only returns None for non-OHLCV, already filtered.
            raise StorageUnavailableError("OHLCV dataset bytes unavailable")

        # Parse
        try:
            bars = _parse_ohlcv_bytes(raw)
        except Exception as exc:
            raise MalformedDataError(f"OHLCV parse failed: {exc}") from exc

        # Resolve provider priority
        try:
            provider = Provider(provider_str)
        except ValueError:
            provider = Provider.UNKNOWN
        provider_priority = ProviderPriority.for_provider(provider)

        # Resolve or create instrument
        instrument: Instrument | None = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            security = await uow.securities.upsert(Security(name=symbol))
            instrument = Instrument(
                security_id=security.id,
                symbol=symbol,
                exchange=exchange,
                flags=InstrumentFlags(has_ohlcv=True),
            )
            instrument = await uow.instruments.upsert(instrument)
            # PLAN-0057 Wave D-2: emit ``market.instrument.discovered.v1`` instead
            # of ``market.instrument.created`` here.  At this stage we only know
            # symbol/exchange — the EODHD ``Name`` is not available, and emitting
            # ``InstrumentCreated(name=None)`` previously produced placeholder
            # canonicals like ``Instrument-019dbbdb`` in the knowledge graph
            # (audit finding F-CRIT-12).  ``fundamentals_consumer`` is now the
            # SOLE emitter of ``market.instrument.created`` (gated on a real Name).
            discovered_event = InstrumentDiscovered(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange or None,
            )
            await uow.outbox_events.create(
                event_type=discovered_event.event_type,
                topic=EVENT_TOPIC_MAP[discovered_event.event_type],
                payload=event_to_outbox_payload(discovered_event),
                # PLAN-0057-followup Wave B (F-DATA-06): pin every
                # ``market.instrument.discovered.v1`` event for a given
                # instrument to the same Kafka partition so the downstream
                # S7 ``InstrumentDiscoveredConsumer`` observes them in causal
                # order (discovered → created enrichment).
                partition_key=str(instrument.id),
            )
        elif not instrument.flags.has_ohlcv:
            updated_flags = InstrumentFlags(
                has_ohlcv=True,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
            )
            await uow.instruments.update_flags(instrument.id, updated_flags)
            updated_event = InstrumentUpdated(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange,
                has_ohlcv=True,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
                fields_updated=("has_ohlcv",),
            )
            await uow.outbox_events.create(
                event_type=updated_event.event_type,
                topic=EVENT_TOPIC_MAP[updated_event.event_type],
                payload=event_to_outbox_payload(updated_event),
                # F-DATA-06: keep all updates for this instrument on the same
                # partition so KG/S6 observe them in order.
                partition_key=str(instrument.id),
            )

        # Resolve timeframe — normalize provider aliases (e.g. "1mo" → "1M") and
        # dead-letter unknown timeframes instead of silently coercing to ONE_DAY.
        tf = _resolve_consumer_timeframe(timeframe_str)

        # Map canonical bars → domain entities
        domain_bars = [
            OHLCVBar(
                instrument_id=instrument.id,
                timeframe=tf,
                bar_date=(bar.date if bar.date.tzinfo is not None else bar.date.replace(tzinfo=UTC)),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=bar.volume,
                adjusted_close=(Decimal(str(bar.adjusted_close)) if bar.adjusted_close is not None else None),
                source=bar.source or provider_str,
                provider_priority=provider_priority,
                ingested_at=datetime.now(tz=UTC),
            )
            for bar in bars
        ]

        # Bulk upsert
        await uow.ohlcv.bulk_upsert_with_priority(domain_bars)

        # ── Option B write-through: 1m bars → quotes table ────────────────────
        # The Alpaca scheduler delivers 1m bars every ~60s (crypto 24/7,
        # equities during RTH), so the latest 1m close is the freshest price we
        # have.  Mirror it into the `quotes` table (last=close, bid/ask=None)
        # so the screener JOIN, S9 and the frontend keep reading fresh prices
        # without any contract change.  Skipped for:
        # - non-1m timeframes (1d closes are stale relative to live quotes)
        # - stale batches (historical replays must never overwrite the live
        #   quote row or touch the live caches — BUG-009 / BP-492)
        #
        # NOTE on is_backfill: the producer derives it as
        # ``task.range_start is not None`` (pipeline.py), and the intraday
        # scheduler sets range_start on EVERY incremental 1m task as a dedupe
        # bucket (FIX-INTRADAY-DEDUP) — verified live: 1895/1895 1m tasks are
        # flagged backfill.  The flag therefore cannot distinguish live ticks
        # from replays here, so the gate is the recency of the bars themselves:
        # genuinely historical batches carry old bar_dates and are skipped,
        # while live windows pass regardless of the mislabeled flag.  The
        # ``upsert_if_newer`` timestamp guard is the second line of defence.
        is_backfill = bool(value.get("is_backfill", False))
        # Use the most recent bar of the batch; `upsert_if_newer` guards
        # against out-of-order batches at the DB level as well.
        latest_bar = max(domain_bars, key=lambda b: b.bar_date) if domain_bars else None
        is_fresh = (
            latest_bar is not None
            and (datetime.now(tz=UTC) - latest_bar.bar_date).total_seconds() <= _QUOTE_WRITE_THROUGH_MAX_AGE_SEC
        )
        if tf == Timeframe.ONE_MIN and latest_bar is not None and not is_fresh:
            logger.debug(
                "ohlcv_consumer.skip_quote_write_through_stale",
                symbol=symbol,
                latest_bar_date=latest_bar.bar_date.isoformat(),
                is_backfill=is_backfill,
            )
        if tf == Timeframe.ONE_MIN and latest_bar is not None and is_fresh:
            quote = Quote(
                instrument_id=instrument.id,
                bid=None,  # 1m bars carry no bid/ask — preserve NULL (D-004)
                ask=None,
                last=latest_bar.close,
                volume=latest_bar.volume,
                timestamp=latest_bar.bar_date,
                updated_at=datetime.now(tz=UTC),
            )
            applied = await uow.quotes.upsert_if_newer(quote)
            if applied:
                # Same post-commit cache fan-out as the quotes consumer:
                # invalidate QuoteCache + warm PriceSnapshotCache (M-005).
                schedule_quote_cache_fanout(
                    uow,
                    instrument_id=instrument.id,
                    symbol=symbol,
                    exchange=exchange,
                    quote=quote,
                    quote_cache=self._quote_cache,
                    price_snapshot_cache=self._price_snapshot_cache,
                )
                logger.info(
                    "ohlcv_consumer.quote_write_through",
                    symbol=symbol,
                    exchange=exchange,
                    instrument_id=instrument.id,
                    bar_date=latest_bar.bar_date.isoformat(),
                )

        logger.info(
            "ohlcv_consumer.materialized",
            symbol=symbol,
            exchange=exchange,
            bar_count=len(domain_bars),
        )

    # ── Combined-batch path: per-message work inside ONE shared transaction ────

    async def _materialize_into_batch(
        self,
        uow: UnitOfWork,
        value: dict[str, Any],
        prefetched: bytes | None,
    ) -> _MessageOutcome:
        """Run one message's DB work inside the shared batch transaction.

        Mirrors :meth:`_materialize` EXCEPT it does NOT issue the OHLCV bulk
        upsert — it returns the parsed/validated domain bars in a
        :class:`_MessageOutcome` so the caller can flush ALL messages' bars in a
        single combined ``bulk_upsert_with_priority`` (the round-trip win).  The
        per-message ``quotes`` write-through (``upsert_if_newer``) DOES run here,
        inside the message's SAVEPOINT, so it is rolled back atomically with the
        rest of the message on failure; only the NON-transactional Valkey
        fan-out is deferred (returned in ``outcome.fanout``) to be fired by the
        caller AFTER the outer commit — never for a rolled-back message.

        The caller must invoke this INSIDE ``async with session.begin_nested():``
        so an exception here rolls back only this message's writes.  Dedup hits
        return early with ``duplicate=True`` and no bars/fan-out.
        """
        # Atomic event-id dedup — identical to the single-message path.
        event_id_raw = value.get("event_id")
        if not event_id_raw:
            raise MalformedDataError("Missing or null event_id in message")
        event_id = str(event_id_raw)
        sha256 = value.get("canonical_ref_sha256") or ""

        # Content-hash dedup BEFORE inserting the event row (BP-035 follow-up).
        if sha256 and await uow.ingestion_events.exists_by_content_hash(sha256, _DATASET_TYPE):
            logger.debug("ohlcv_consumer.skip_unchanged", sha256_prefix=sha256[:8])
            await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
            return _MessageOutcome(event_id=event_id, duplicate=True)

        is_new = await uow.ingestion_events.create_if_not_exists(event_id, _DATASET_TYPE, sha256 or None)
        if not is_new:
            logger.debug("ohlcv_consumer.duplicate_event", event_id=str(event_id)[:8])
            return _MessageOutcome(event_id=event_id, duplicate=True)

        symbol = _normalize_ticker(value["symbol"])
        exchange = value.get("exchange") or ""
        provider_str = value.get("provider", "unknown")
        timeframe_str = value.get("timeframe") or "1d"

        raw = prefetched if prefetched is not None else await self._prefetch_dataset(value)
        if raw is None:
            raise StorageUnavailableError("OHLCV dataset bytes unavailable")

        try:
            bars = _parse_ohlcv_bytes(raw)
        except Exception as exc:
            raise MalformedDataError(f"OHLCV parse failed: {exc}") from exc

        try:
            provider = Provider(provider_str)
        except ValueError:
            provider = Provider.UNKNOWN
        provider_priority = ProviderPriority.for_provider(provider)

        instrument = await self._resolve_or_create_instrument(uow, symbol, exchange)

        tf = _resolve_consumer_timeframe(timeframe_str)
        domain_bars = self._build_domain_bars(bars, instrument, tf, provider_priority, provider_str)

        outcome = _MessageOutcome(event_id=event_id, bars=domain_bars)

        # ── 1m quote write-through (DB write inside the SAVEPOINT) ─────────────
        # The ``quotes`` upsert runs here so it rolls back with the message on
        # failure.  Only the Valkey fan-out is deferred (returned) — it must
        # never fire for a rolled-back/uncommitted message.
        is_backfill = bool(value.get("is_backfill", False))
        latest_bar = max(domain_bars, key=lambda b: b.bar_date) if domain_bars else None
        is_fresh = (
            latest_bar is not None
            and (datetime.now(tz=UTC) - latest_bar.bar_date).total_seconds() <= _QUOTE_WRITE_THROUGH_MAX_AGE_SEC
        )
        if tf == Timeframe.ONE_MIN and latest_bar is not None and not is_fresh:
            logger.debug(
                "ohlcv_consumer.skip_quote_write_through_stale",
                symbol=symbol,
                latest_bar_date=latest_bar.bar_date.isoformat(),
                is_backfill=is_backfill,
            )
        if tf == Timeframe.ONE_MIN and latest_bar is not None and is_fresh:
            quote = Quote(
                instrument_id=instrument.id,
                bid=None,
                ask=None,
                last=latest_bar.close,
                volume=latest_bar.volume,
                timestamp=latest_bar.bar_date,
                updated_at=datetime.now(tz=UTC),
            )
            applied = await uow.quotes.upsert_if_newer(quote)
            if applied:
                outcome.fanout = _PendingFanout(
                    instrument_id=instrument.id,
                    symbol=symbol,
                    exchange=exchange,
                    quote=quote,
                )
                logger.info(
                    "ohlcv_consumer.quote_write_through",
                    symbol=symbol,
                    exchange=exchange,
                    instrument_id=instrument.id,
                    bar_date=latest_bar.bar_date.isoformat(),
                )

        logger.info(
            "ohlcv_consumer.materialized",
            symbol=symbol,
            exchange=exchange,
            bar_count=len(domain_bars),
        )
        return outcome

    async def _resolve_or_create_instrument(
        self,
        uow: UnitOfWork,
        symbol: str,
        exchange: str,
    ) -> Instrument:
        """Resolve an existing instrument or create one (+ emit outbox events).

        Shared by both the single-message and combined-batch paths.  In the batch
        path two messages for the SAME new symbol run in the SAME transaction, so
        the second finds the first's freshly-inserted instrument (the insert in
        the first message's SAVEPOINT is visible once released into the shared
        transaction).
        """
        instrument: Instrument | None = await uow.instruments.find_by_symbol_exchange(symbol, exchange)
        if instrument is None:
            security = await uow.securities.upsert(Security(name=symbol))
            instrument = Instrument(
                security_id=security.id,
                symbol=symbol,
                exchange=exchange,
                flags=InstrumentFlags(has_ohlcv=True),
            )
            instrument = await uow.instruments.upsert(instrument)
            discovered_event = InstrumentDiscovered(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange or None,
            )
            await uow.outbox_events.create(
                event_type=discovered_event.event_type,
                topic=EVENT_TOPIC_MAP[discovered_event.event_type],
                payload=event_to_outbox_payload(discovered_event),
                partition_key=str(instrument.id),
            )
        elif not instrument.flags.has_ohlcv:
            updated_flags = InstrumentFlags(
                has_ohlcv=True,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
            )
            await uow.instruments.update_flags(instrument.id, updated_flags)
            updated_event = InstrumentUpdated(
                instrument_id=instrument.id,
                symbol=symbol,
                exchange=exchange,
                has_ohlcv=True,
                has_quotes=instrument.flags.has_quotes,
                has_fundamentals=instrument.flags.has_fundamentals,
                fields_updated=("has_ohlcv",),
            )
            await uow.outbox_events.create(
                event_type=updated_event.event_type,
                topic=EVENT_TOPIC_MAP[updated_event.event_type],
                payload=event_to_outbox_payload(updated_event),
                partition_key=str(instrument.id),
            )
        return instrument

    @staticmethod
    def _build_domain_bars(
        bars: list[CanonicalOHLCVBar],
        instrument: Instrument,
        tf: Timeframe,
        provider_priority: ProviderPriority,
        provider_str: str,
    ) -> list[OHLCVBar]:
        """Map canonical bars → domain ``OHLCVBar`` entities (pure)."""
        return [
            OHLCVBar(
                instrument_id=instrument.id,
                timeframe=tf,
                bar_date=(bar.date if bar.date.tzinfo is not None else bar.date.replace(tzinfo=UTC)),
                open=Decimal(str(bar.open)),
                high=Decimal(str(bar.high)),
                low=Decimal(str(bar.low)),
                close=Decimal(str(bar.close)),
                volume=bar.volume,
                adjusted_close=(Decimal(str(bar.adjusted_close)) if bar.adjusted_close is not None else None),
                source=bar.source or provider_str,
                provider_priority=provider_priority,
                ingested_at=datetime.now(tz=UTC),
            )
            for bar in bars
        ]

    # ── Option B: consumer-local micro-batching run() override ─────────────────

    async def run(self) -> None:  # type: ignore[override]
        """Batch-consuming variant of the base poll loop (consumer-local).

        Mirrors :meth:`BaseKafkaConsumer.run` orchestration EXACTLY — same
        ``_init_kafka`` → retry-loop + connectivity-probe tasks (with identical
        crash done-callbacks) → ``finally`` that cancels both and calls
        ``_shutdown_kafka`` — but replaces the single-message ``poll()`` with a
        batched ``consume(num_messages=BATCH_MAX)``.  Per cycle it:

        1. drains up to ``self._batch_max_messages`` already-buffered messages,
        2. prefetches every OHLCV message's S3 object CONCURRENTLY
           (:func:`asyncio.gather`) before any DB work,
        3. materialises each partition's messages through ONE shared UnitOfWork
           with a per-message ``SAVEPOINT`` (so a poison message rolls back only
           its own writes), then issues ONE combined ``bulk_upsert_with_priority``
           for every released message's bars and a single outer ``commit()`` —
           see :meth:`_process_batch` for the full design,
        4. commits the highest CONTIGUOUS succeeded offset per partition ONCE,
        5. records consumer lag ONCE per batch.

        The shared ``BaseKafkaConsumer`` is intentionally left untouched.
        """
        self._init_kafka()
        retry_task = asyncio.create_task(self._retry_loop())
        probe_task = asyncio.create_task(self._connectivity_probe_loop())

        # Identical crash done-callbacks to the base: a retry-loop crash forces
        # sys.exit(1) so the orchestrator restarts us; a probe crash is logged
        # critical (the probe itself sys.exit(2)s on sustained failure).
        def _on_retry_task_done(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.critical("retry_task_crashed", exc_info=exc)
                sys.exit(1)

        retry_task.add_done_callback(_on_retry_task_done)

        def _on_probe_task_done(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.critical("connectivity_probe_crashed", exc_info=exc)

        probe_task.add_done_callback(_on_probe_task_done)

        try:
            loop = asyncio.get_event_loop()
            while not self._stop_event.is_set():
                # Same opt-in backpressure check as the base, once per cycle.
                self._maybe_apply_backpressure()

                # BP-700: mirror the base loop's transient-error RECONNECT +
                # liveness heartbeat in this batch override (the silent-consumer-
                # death incident was on THIS consumer).  Without it a transient
                # broker blip in ``consume()`` would escape and kill the loop, and
                # nothing would heartbeat ``/healthz`` so a dead loop looked
                # healthy.  The shared helpers live on ``BaseKafkaConsumer``.
                if self._consumer is None and not await self._reconnect_with_backoff():
                    continue
                try:
                    # Batched consume: drain up to BATCH_MAX buffered messages in
                    # one broker round-trip instead of one message per poll().
                    messages = await loop.run_in_executor(
                        None,
                        self._consumer.consume,
                        self._batch_max_messages,
                        self._config.poll_timeout_seconds,
                    )
                except Exception as consume_exc:
                    if self._is_transient_broker_error(consume_exc):
                        logger.warning(
                            "kafka_consume_transient_error_reconnecting",
                            group_id=self._config.group_id,
                            error=str(consume_exc),
                            error_type=type(consume_exc).__name__,
                        )
                        await self._reconnect_with_backoff()
                    else:
                        logger.exception("kafka_consume_unexpected_error", error=str(consume_exc))
                    continue
                # Healthy consume cycle (idle OR batch) → heartbeat + reset the
                # reconnect counter so an isolated blip does not erode the
                # terminal-stop budget over the consumer's lifetime.
                self._record_progress()
                self._reconnect_attempts = 0
                if not messages:
                    continue

                await self._process_batch(loop, messages)
        finally:
            retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry_task
            probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await probe_task
            self._shutdown_kafka()

    async def _process_batch(self, loop: Any, messages: list[Any]) -> None:
        """Process one drained batch with ONE shared UoW + per-message SAVEPOINTs.

        ``messages`` is the raw list returned by ``Consumer.consume``.  Poll
        errors are handled per the base loop (skip ``_PARTITION_EOF``, log+skip
        others).

        Design (combined-batch materialization, confirmed 2026-06-16):

        * **One shared UoW / session / transaction per partition.**  All of a
          partition's messages run inside a single ``async with uow:`` so the
          batch costs ONE Postgres write connection and ONE ``BEGIN``/``COMMIT``
          round-trip instead of N (the session-pressure win the audit targeted).
        * **Per-message SAVEPOINT.**  Each message runs inside
          ``async with session.begin_nested():`` (a real Postgres ``SAVEPOINT``).
          On success the savepoint releases; on exception only that message's
          writes are undone (``ROLLBACK TO SAVEPOINT``), the message is routed to
          the DLQ via :meth:`_handle_failure` (which persists via its OWN fresh
          committed UoW — durable even though the batch may later roll back), and
          the partition's contiguous prefix is BROKEN (``break``).
        * **One combined upsert.**  Every released message's bars are buffered
          and flushed with a SINGLE ``bulk_upsert_with_priority`` across all
          symbols, then a single ``uow.commit()`` makes the dedup rows +
          instrument rows/outbox + the combined upsert atomic.  If the combined
          upsert or the outer commit fails, NOTHING commits → no offsets advance
          → the whole partition redelivers (idempotent via the DB dedup rows).
        * **Deferred side effects.**  The Valkey quote-cache fan-out and the
          per-message Valkey dedup mark are NON-transactional, so they fire ONCE
          after the outer commit succeeds, only for committed messages — never
          for a rolled-back/duplicate message (else a crash between fan-out and
          commit would corrupt caches).
        * **Per-message behaviour preserved.**  Because this bypasses the base
          ``_handle_message`` (which opens a per-message UoW), the dedup mixin
          ``is_duplicate`` gate, the ``message_processing_timeout_s`` watchdog,
          the success metrics, and the ``_ASYNCPG_CONN_ERRORS`` reconnect-retry
          are all re-implemented inline below.

        Lock-hold tradeoff: one transaction holds its touched rows' locks for the
        whole batch (~2-5 s at the 50-message bound) rather than ~tens of ms per
        message.  This is comfortably within ``max_poll_interval_ms=600_000`` and
        the ``_batch_max_messages`` (50) bound caps the lock footprint.
        """
        from confluent_kafka import KafkaError, TopicPartition

        # Filter out poll-level errors exactly like the base single-message loop.
        valid: list[Any] = []
        for msg in messages:
            err = msg.error()
            if err is not None:
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("kafka_poll_error", error=str(err))
                continue
            valid.append(msg)
        if not valid:
            return

        # Process each partition's messages in strict offset order so the
        # contiguous-commit barrier is well defined.  Group by (topic, partition).
        by_partition: dict[tuple[str, int], list[Any]] = {}
        for msg in valid:
            by_partition.setdefault((msg.topic(), msg.partition()), []).append(msg)

        # ── Phase 1: prefetch all S3 objects concurrently (network-bound) ─────
        # Deserialize each message once (cheap) so we can both prefetch by value
        # and stash bytes keyed by event_id for the materialize phase.
        prefetch_targets: list[tuple[Any, dict[str, Any]]] = []
        for msg in valid:
            try:
                value = self.deserialize_value(msg.value(), self.get_schema_path(msg.topic()))
            except Exception as exc:
                # Malformed envelope — skip prefetch and let the per-message
                # _handle_message path surface and DLQ it (it re-deserializes and
                # raises there).  Logged at debug so it is not lost silently.
                logger.debug("ohlcv_consumer.prefetch_deserialize_failed", error=str(exc))
                continue
            if value.get("dataset_type", "") == _DATASET_TYPE:
                prefetch_targets.append((msg, value))

        if prefetch_targets:
            results = await asyncio.gather(
                *(self._prefetch_dataset(value) for _msg, value in prefetch_targets),
                return_exceptions=True,
            )
            for (_msg, value), result in zip(prefetch_targets, results, strict=True):
                event_id_raw = value.get("event_id")
                if not event_id_raw:
                    continue
                if isinstance(result, bytes):
                    # Cache the bytes so process_message reuses them; a fetch
                    # exception is intentionally NOT cached — _handle_message will
                    # re-run the inline fetch and raise the same error into the
                    # normal failure/DLQ path, preserving today's semantics.
                    self._prefetch_cache[str(event_id_raw)] = result

        # ── Phase 2: per-partition shared-UoW materialize + combined commit ───
        for (topic, partition), part_msgs in by_partition.items():
            part_msgs.sort(key=lambda m: m.offset())
            last_committable_offset = await self._process_partition_batch(part_msgs)
            if last_committable_offset is not None and not self._config.enable_auto_commit:
                # confluent-kafka commit-by-offset: the committed offset is the
                # NEXT offset to read, i.e. last-processed + 1.  ``offsets`` and
                # ``asynchronous`` are keyword-only on Consumer.commit, so wrap in
                # a lambda before hopping onto the executor (synchronous commit so
                # an error surfaces here rather than silently on the next poll).
                tp = TopicPartition(topic, partition, last_committable_offset + 1)
                await loop.run_in_executor(
                    None,
                    lambda tp=tp: self._consumer.commit(offsets=[tp], asynchronous=False),
                )

        # Clear any prefetch bytes left over (e.g. duplicates that returned early
        # before consuming the cache entry) so the cache never grows unbounded.
        self._prefetch_cache.clear()

        # ── Phase 3: record lag ONCE per batch (not per message) ──────────────
        await loop.run_in_executor(None, self._record_consumer_lag)

    async def _process_partition_batch(self, part_msgs: list[Any]) -> int | None:
        """Materialize one partition's (offset-sorted) messages in ONE transaction.

        Returns the highest CONTIGUOUS succeeded offset for the partition (so the
        caller can commit ``offset + 1``), or ``None`` if nothing committed.

        Flow: open ONE shared UoW → per message run a SAVEPOINT that accumulates
        bars + a deferred fan-out (skipping duplicates, breaking the contiguous
        prefix on failure) → ONE combined ``bulk_upsert_with_priority`` → ONE
        ``commit()`` → fire deferred fan-outs + Valkey dedup marks for committed
        messages.  On a combined-upsert / commit failure NOTHING commits and the
        whole partition redelivers.
        """
        last_committable_offset: int | None = None
        accumulated_bars: list[OHLCVBar] = []
        committed_fanouts: list[_PendingFanout] = []
        committed_event_ids: list[str] = []
        timeout_s = self._config.message_processing_timeout_s

        async with self._uow_factory() as uow:
            # Expose the shared UoW to ``self._current_uow`` for parity with the
            # single-message path (some helpers read it); the batch code itself
            # always passes ``uow`` explicitly.
            self._current_uow = uow
            session = uow.get_write_session()

            for msg in part_msgs:
                # Deserialize + dedup-gate BEFORE opening a savepoint (a dup or a
                # malformed envelope needs no nested transaction).
                try:
                    value = self.deserialize_value(msg.value(), self.get_schema_path(msg.topic()))
                except Exception as exc:
                    # Include the exception TYPE — truncated-Avro failures often
                    # have an empty ``str(exc)`` and would otherwise write a DLQ
                    # row with no diagnosable cause.
                    _detail = str(exc).strip() or repr(exc)
                    await self._handle_failure(
                        msg,
                        MalformedDataError(f"deserialization failed: {type(exc).__name__}: {_detail}"),
                    )
                    break

                # Non-OHLCV messages are a successful no-op — they advance the
                # offset without any DB work (matches the single-message filter).
                if value.get("dataset_type", "") != _DATASET_TYPE:
                    last_committable_offset = msg.offset()
                    continue

                event_id = self.extract_event_id(value)

                # ValkeyDedupMixin fast-path dedup (belt-and-braces over the DB
                # natural-key dedup).  A Valkey hit is a successful no-op: skip
                # without a savepoint, advance the offset, do NOT re-mark.
                if await self.is_duplicate(event_id):
                    logger.debug("ohlcv_consumer.valkey_duplicate", event_id=event_id)
                    last_committable_offset = msg.offset()
                    continue

                prefetched: bytes | None = self._prefetch_cache.pop(event_id, None)

                outcome = await self._run_message_savepoint(uow, session, msg, value, prefetched, timeout_s)
                if outcome is None:
                    # Failure: savepoint already rolled back, DLQ written via a
                    # fresh committed UoW, contiguous prefix broken.
                    break

                if not outcome.duplicate:
                    accumulated_bars.extend(outcome.bars)
                    if outcome.fanout is not None:
                        committed_fanouts.append(outcome.fanout)
                    committed_event_ids.append(outcome.event_id)
                last_committable_offset = msg.offset()

            if last_committable_offset is None:
                # Nothing to commit (every message failed/filtered to nothing).
                return None

            # ── ONE combined upsert for all released messages' bars ───────────
            if accumulated_bars:
                await uow.ohlcv.bulk_upsert_with_priority(accumulated_bars)

            # ── Deferred quote-cache fan-out, gated on the outer commit ───────
            # Schedule the NON-transactional Valkey fan-out for ONLY committed
            # messages onto the UoW's post-commit hook list.  ``commit()`` fires
            # these AFTER the DB write is durable, each isolated per F-DS-015,
            # and a rolled-back/duplicate message never reaches ``committed_fanouts``
            # so it can never warm a cache for data that was not committed.
            for fanout in committed_fanouts:
                schedule_quote_cache_fanout(
                    uow,
                    instrument_id=fanout.instrument_id,
                    symbol=fanout.symbol,
                    exchange=fanout.exchange,
                    quote=fanout.quote,
                    quote_cache=self._quote_cache,
                    price_snapshot_cache=self._price_snapshot_cache,
                )

            # ── ONE outer commit (released savepoints + combined upsert) ──────
            # If this raises, the whole partition's transaction rolls back, NO
            # offset is committed (we re-raise after logging), the scheduled
            # fan-outs never fire, and the batch redelivers — idempotent via the
            # DB dedup rows.  Valkey dedup marks are also NOT applied.
            try:
                await uow.commit()
            except Exception:
                logger.exception(
                    "ohlcv_consumer.batch_commit_failed",
                    partition_message_count=len(part_msgs),
                    accumulated_bar_count=len(accumulated_bars),
                )
                raise

            # Post-commit, non-transactional: mark committed messages in Valkey
            # ONLY after the DB commit succeeded (a mark ahead of the commit could
            # skip a never-committed message on redelivery and lose data).  Still
            # inside the ``async with`` so this never runs if the commit raised.
            for event_id in committed_event_ids:
                await self.mark_processed(event_id)

            # Per-message success metrics (re-implemented from the bypassed base
            # ``_handle_message``) — one increment per committed message.
            for _ in committed_event_ids:
                self._record_consumed_metric()

        return last_committable_offset

    async def _run_message_savepoint(
        self,
        uow: UnitOfWork,
        session: Any,
        msg: Any,
        value: dict[str, Any],
        prefetched: bytes | None,
        timeout_s: float,
    ) -> _MessageOutcome | None:
        """Run one message inside a SAVEPOINT; return its outcome or ``None``.

        ``None`` signals a handled failure (savepoint rolled back, DLQ written,
        contiguous prefix must break).  Re-implements the base watchdog
        (``asyncio.timeout``) and the ``_ASYNCPG_CONN_ERRORS`` single reconnect
        retry, since this path bypasses ``_handle_message``.
        """

        async def _attempt() -> _MessageOutcome:
            async with session.begin_nested():
                if timeout_s > 0:
                    async with asyncio.timeout(timeout_s):
                        return await self._materialize_into_batch(uow, value, prefetched)
                return await self._materialize_into_batch(uow, value, prefetched)

        try:
            try:
                return await _attempt()
            except _ASYNCPG_CONN_ERRORS as conn_exc:
                logger.warning(
                    "consumer_db_connection_lost_retrying",
                    error=str(conn_exc),
                    error_type=type(conn_exc).__name__,
                    topic=msg.topic(),
                    partition=msg.partition(),
                    offset=msg.offset(),
                )
                await asyncio.sleep(1.0)
                return await _attempt()
        except TimeoutError as exc:
            # Watchdog: savepoint already rolled back by begin_nested __aexit__.
            import faulthandler

            faulthandler.dump_traceback(file=sys.stderr)
            await self._handle_failure(msg, exc)
            return None
        except ConsumerError as exc:
            await self._handle_failure(msg, exc)
            return None
        except Exception as exc:
            logger.exception("kafka_unexpected_error", error=str(exc))
            await self._handle_failure(msg, exc)
            return None

    def _record_consumed_metric(self) -> None:
        """Increment the per-message consumed counters (mirrors the base path)."""
        from messaging.kafka.consumer.base import KAFKA_CONSUMER_MESSAGES  # type: ignore[import-untyped]

        self._metrics.kafka_messages_consumed_total.labels(
            topic=_TOPIC,
            consumer_group=self._config.group_id,
        ).inc()
        KAFKA_CONSUMER_MESSAGES.labels(
            service=self._metrics.service_name if self._metrics is not None else self._config.group_id,
            topic=_TOPIC,
            consumer_group=self._config.group_id,
        ).inc()
