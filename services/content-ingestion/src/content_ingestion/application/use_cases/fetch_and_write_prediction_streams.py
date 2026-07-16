"""Fetch-and-write use case for the 4 deeper Polymarket streams (PLAN-0056 Wave B3).

Mirrors :class:`FetchAndWritePredictionMarketsUseCase` but generalises over the
four new fetch-result entity types produced by the B1 adapters:

    • ``PredictionEventFetchResult``   → ``market.prediction.event``  → MARKET_PREDICTION_EVENT
    • ``PredictionHistoryFetchResult`` → ``market.prediction.history``→ MARKET_PREDICTION_HISTORY
    • ``PredictionTradeFetchResult``   → ``market.prediction.trade``  → MARKET_PREDICTION_TRADE
    • ``PredictionOIFetchResult``      → ``market.prediction.oi``     → MARKET_PREDICTION_OI

For each fetch-result the use case, in a **single DB transaction** (R8 — never
DB + Kafka in separate txns):

1. Skips if ``(dedup_key, fetched_at)`` already exists in
   ``prediction_market_fetch_log`` (idempotent — the adapter dedup is the first
   pass, this is the authoritative second).
2. Builds one-or-more outbox payloads (history emits one per datapoint) matching
   the stream's ``market.prediction.{event,history,trade,oi}.v1`` Avro schema.
3. INSERTs the fetch-log row + the outbox row(s) then commits.

NEVER publishes directly to Kafka — the outbox dispatcher handles that.

Dedup keys (the ``market_id`` column of ``prediction_market_fetch_log`` is reused
as a generic natural-key column):

    • event   → ``event_id``
    • history → ``token_id``
    • trade   → ``trade_id``
    • oi      → ``market_id``

The S3 consumers additionally ``ON CONFLICT``-dedup on their own natural keys, so
at-least-once emission from here is safe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

import common.ids
import common.time as ct
from messaging.topics import (  # type: ignore[import-untyped]
    MARKET_PREDICTION_EVENT,
    MARKET_PREDICTION_HISTORY,
    MARKET_PREDICTION_OI,
    MARKET_PREDICTION_TRADE,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from content_ingestion.application.ports.repositories import OutboxPort, PredictionMarketFetchLogPort
    from content_ingestion.domain.entities import (
        PredictionEventFetchResult,
        PredictionHistoryFetchResult,
        PredictionOIFetchResult,
        PredictionTradeFetchResult,
    )

logger = get_logger(__name__)  # type: ignore[no-any-return]


# ── Payload builders (one Avro-shaped dict per schema) ─────────────────────────
#
# Each builder maps a B1 fetch-result entity to a dict whose keys match the
# corresponding ``.avsc`` field names EXACTLY.  ``is_backfill`` is accepted by
# every builder for a uniform signature; only the history builder uses it.


def build_prediction_event_payloads(
    result: PredictionEventFetchResult,
    is_backfill: bool = False,
) -> list[dict[str, Any]]:
    """Build the ``market.prediction.event.v1`` payload for one event group."""
    return [
        {
            "event_id": str(common.ids.new_uuid7()),
            "event_type": "market.prediction.event",
            "schema_version": 1,
            "occurred_at": ct.to_iso8601(result.fetched_at),
            # ``group_id`` is the Polymarket business key (Gamma /events id) →
            # prediction_events.event_id in S3.
            "group_id": result.event_id,
            "name": result.title,
            "category": result.category,
            "start_date": ct.to_iso8601(result.start_date) if result.start_date else None,
            "end_date": ct.to_iso8601(result.end_date) if result.end_date else None,
            "market_count": result.market_count,
            # PLAN-0056 Wave A3 completion: the child-market conditionIds so S3 can
            # backfill prediction_markets.event_id (market->event linkage). list()
            # because Avro arrays serialize from a list, not a tuple.
            "member_condition_ids": list(result.member_condition_ids),
            "correlation_id": None,
        }
    ]


def build_prediction_history_payloads(
    result: PredictionHistoryFetchResult,
    is_backfill: bool = False,
) -> list[dict[str, Any]]:
    """Build one ``market.prediction.history.v1`` payload PER price datapoint.

    ``market_id`` = the PARENT market ``conditionId`` (PLAN-0056 Wave B4:
    ``result.market_id``), so the S3 ``prediction_market_prices`` rows JOIN to
    ``prediction_markets`` (keyed on conditionId).  ``token_id`` is the per-outcome
    CLOB token.  Legacy fetch-results with no parent (``market_id is None``) fall
    back to the ``token_id`` surrogate to satisfy the non-null schema field.
    """
    return [
        {
            "event_id": str(common.ids.new_uuid7()),
            "event_type": "market.prediction.history",
            "schema_version": 1,
            "occurred_at": ct.to_iso8601(result.fetched_at),
            "market_id": result.market_id or result.token_id,
            "token_id": result.token_id,
            "outcome_name": None,
            "interval": result.interval,
            "window_start_ts": ct.to_iso8601(point.timestamp),
            "price": point.price,
            "source": "polymarket_clob",
            "is_backfill": is_backfill,
            "correlation_id": None,
        }
        for point in result.points
    ]


def build_prediction_trade_payloads(
    result: PredictionTradeFetchResult,
    is_backfill: bool = False,
) -> list[dict[str, Any]]:
    """Build the ``market.prediction.trade.v1`` payload for one fill.

    ``market_id`` = the PARENT market ``conditionId`` (PLAN-0056 Wave B4:
    ``result.market_id`` — the trades feed is polled per condition_id), so the S3
    ``prediction_market_trades`` rows JOIN to ``prediction_markets``.  ``token_id``
    is the per-outcome CLOB token.  Legacy trades with no parent
    (``market_id is None``) fall back to the ``token_id`` surrogate.
    """
    return [
        {
            "event_id": str(common.ids.new_uuid7()),
            "event_type": "market.prediction.trade",
            "schema_version": 1,
            "occurred_at": ct.to_iso8601(result.traded_at),
            "market_id": result.market_id or result.token_id,
            "trade_id": result.trade_id,
            "token_id": result.token_id,
            "price": result.price,
            "size_usd": result.size_usd,
            "side": result.side,
            "ts": ct.to_iso8601(result.traded_at),
            "correlation_id": None,
        }
    ]


def build_prediction_oi_payloads(
    result: PredictionOIFetchResult,
    is_backfill: bool = False,
) -> list[dict[str, Any]]:
    """Build the ``market.prediction.oi.v1`` payload for one daily OI snapshot."""
    return [
        {
            "event_id": str(common.ids.new_uuid7()),
            "event_type": "market.prediction.oi",
            "schema_version": 1,
            "occurred_at": ct.to_iso8601(result.fetched_at),
            "market_id": result.market_id,
            # Schema documents snapshot_date as YYYY-MM-DD.
            "snapshot_date": result.snapshot_date.date().isoformat(),
            "total_oi_usd": result.open_interest_usd,
            # ``double`` (non-null) in the schema — fall back to 0.0 when absent.
            "total_volume_24h_usd": result.volume_24h_usd if result.volume_24h_usd is not None else 0.0,
            "correlation_id": None,
        }
    ]


# ── Stream spec + generic use case ─────────────────────────────────────────────


@dataclass(frozen=True)
class PredictionStreamSpec:
    """Immutable per-stream wiring: event_type, topic, aggregate + callables."""

    event_type: str
    topic: str
    aggregate_type: str
    build_payloads: Callable[[Any, bool], list[dict[str, Any]]]
    dedup_key: Callable[[Any], str]


# Registry — one spec per deeper stream.  ``build_payloads`` accepts
# ``(result, is_backfill)`` uniformly (only history reads is_backfill).
PREDICTION_EVENT_SPEC = PredictionStreamSpec(
    event_type="market.prediction.event",
    topic=MARKET_PREDICTION_EVENT,
    aggregate_type="prediction_event",
    build_payloads=build_prediction_event_payloads,
    dedup_key=lambda r: r.event_id,
)
PREDICTION_HISTORY_SPEC = PredictionStreamSpec(
    event_type="market.prediction.history",
    topic=MARKET_PREDICTION_HISTORY,
    aggregate_type="prediction_history",
    build_payloads=build_prediction_history_payloads,
    dedup_key=lambda r: r.token_id,
)
PREDICTION_TRADE_SPEC = PredictionStreamSpec(
    event_type="market.prediction.trade",
    topic=MARKET_PREDICTION_TRADE,
    aggregate_type="prediction_trade",
    build_payloads=build_prediction_trade_payloads,
    dedup_key=lambda r: r.trade_id,
)
PREDICTION_OI_SPEC = PredictionStreamSpec(
    event_type="market.prediction.oi",
    topic=MARKET_PREDICTION_OI,
    aggregate_type="prediction_oi",
    build_payloads=build_prediction_oi_payloads,
    dedup_key=lambda r: r.market_id,
)


@dataclass(frozen=True)
class PredictionStreamFetchSummary:
    """Summary of a single deeper-stream fetch-and-write cycle."""

    fetched: int = 0
    emitted: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class FetchAndWritePredictionStreamUseCase:
    """Atomically write deeper-stream fetch-results to fetch_log + outbox.

    Args:
        fetch_log_repo: Repository for ``prediction_market_fetch_log`` dedup + writes.
        outbox_repo: Repository for transactional outbox events.
        spec: The :class:`PredictionStreamSpec` for the stream being written.
        commit_fn: Async callable to commit the DB session.
        rollback_fn: Async callable to roll back the DB session on error (M-02 —
            the shared session is poisoned after any exception unless rolled back
            before the next iteration).
    """

    def __init__(
        self,
        fetch_log_repo: PredictionMarketFetchLogPort,
        outbox_repo: OutboxPort,
        spec: PredictionStreamSpec,
        commit_fn: Callable[[], Coroutine[Any, Any, None]],
        rollback_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self._fetch_log = fetch_log_repo
        self._outbox = outbox_repo
        self._spec = spec
        self._commit_fn = commit_fn
        self._rollback_fn = rollback_fn

    async def execute(
        self,
        results: list[Any],
        source_id: UUID | None = None,
        *,
        is_backfill: bool = False,
    ) -> PredictionStreamFetchSummary:
        """Write each result atomically (fetch_log + outbox) and return a summary."""
        start = time.monotonic()
        fetched = 0
        emitted = 0
        skipped = 0
        failed = 0
        errors: list[str] = []
        spec = self._spec

        for result in results:
            key = spec.dedup_key(result)
            try:
                # Event-level idempotency (double-check — adapter dedup is first pass).
                if await self._fetch_log.exists_by_market_snapshot(key, result.fetched_at):
                    skipped += 1
                    continue

                payloads = spec.build_payloads(result, is_backfill)

                # Single transaction: fetch_log + outbox row(s) (R8 — outbox pattern).
                await self._fetch_log.create_market_fetch_log(
                    source_id=source_id,
                    market_id=key,
                    snapshot_at=result.fetched_at,
                    # No resolution semantics for deeper streams — carry the column
                    # default so the NOT NULL constraint is satisfied.
                    resolution_status="open",
                    fetched_at=result.fetched_at,
                )
                for payload in payloads:
                    await self._outbox.append(
                        aggregate_type=spec.aggregate_type,
                        aggregate_id=result.id,
                        event_type=spec.event_type,
                        topic=spec.topic,
                        payload=payload,
                    )
                await self._commit_fn()
                fetched += 1
                emitted += len(payloads)

            except Exception as exc:
                # M-02: roll back immediately so the shared session is not
                # poisoned for subsequent loop iterations.
                await self._rollback_fn()
                failed += 1
                errors.append(f"{key}: {type(exc).__name__}")
                logger.error(
                    "prediction_stream_write_failed",
                    event_type=spec.event_type,
                    dedup_key=key,
                    error=type(exc).__name__,
                )

        duration = time.monotonic() - start
        logger.info(
            "prediction_stream_cycle_complete",
            event_type=spec.event_type,
            fetched=fetched,
            emitted=emitted,
            skipped=skipped,
            failed=failed,
            duration_seconds=round(duration, 3),
        )
        return PredictionStreamFetchSummary(
            fetched=fetched,
            emitted=emitted,
            skipped=skipped,
            failed=failed,
            duration_seconds=round(duration, 3),
            errors=errors,
        )
