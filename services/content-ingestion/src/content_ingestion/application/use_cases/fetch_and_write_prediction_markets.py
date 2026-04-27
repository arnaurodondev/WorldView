"""Fetch-and-write use case for prediction market snapshots.

For each ``PredictionMarketFetchResult``:
1. Skip if (market_id, snapshot_at) already in ``prediction_market_fetch_log`` (idempotent).
2. Build outbox payload matching ``market.prediction.v1`` Avro schema exactly.
3. In a **single DB transaction**: INSERT ``prediction_market_fetch_log`` +
   INSERT ``outbox_events`` (topic='market.prediction.v1').
4. Commit.

NEVER publish directly to Kafka — the outbox dispatcher handles that (R8).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

import common.ids
import common.time as ct
from messaging.topics import MARKET_PREDICTION  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from content_ingestion.application.ports.repositories import OutboxPort, PredictionMarketFetchLogPort
    from content_ingestion.domain.entities import PredictionMarketFetchResult

logger = get_logger(__name__)  # type: ignore[no-any-return]


def build_prediction_market_payload(result: PredictionMarketFetchResult) -> dict[str, Any]:
    """Build outbox payload matching ``market.prediction.v1.avsc`` field names exactly."""
    return {
        "event_id": str(common.ids.new_uuid7()),
        "event_type": "market.prediction.snapshot",
        "schema_version": 1,
        "occurred_at": ct.to_iso8601(result.fetched_at),
        "market_id": result.market_id,
        "source": result.source_type.value,
        "question": result.question,
        "description": result.description,
        "outcomes": [{"name": o.name, "token_id": o.token_id, "price": o.price} for o in result.outcomes],
        "volume_24h": result.volume_24h,
        "liquidity": result.liquidity,
        "close_time": ct.to_iso8601(result.close_time) if result.close_time else None,
        "resolution_status": result.resolution_status,
        "resolved_answer": result.resolved_answer,
        "minio_bronze_key": result.minio_bronze_key,
        # WHY `or None`: empty string "" is a falsy sentinel meaning "no slug";
        # the Avro schema declares this field as ["null", "string"] with default null.
        # Sending "" would be valid Avro but misleading — null is the correct absent signal.
        "market_slug": result.market_slug or None,
        "correlation_id": None,
    }


@dataclass(frozen=True)
class PredictionMarketFetchSummary:
    """Summary of a single prediction market fetch-and-write cycle."""

    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class FetchAndWritePredictionMarketsUseCase:
    """Atomically write prediction market snapshots to fetch_log + outbox.

    Args:
        fetch_log_repo: Repository for prediction_market_fetch_log dedup + writes.
        outbox_repo: Repository for transactional outbox events.
        commit_fn: Async callable to commit the DB session.
        rollback_fn: Async callable to roll back the DB session on error.
            MUST be provided; the shared session is poisoned after any
            exception unless rolled back before the next iteration (M-02).
    """

    def __init__(
        self,
        fetch_log_repo: PredictionMarketFetchLogPort,
        outbox_repo: OutboxPort,
        commit_fn: Callable[[], Coroutine[Any, Any, None]],
        rollback_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self._fetch_log = fetch_log_repo
        self._outbox = outbox_repo
        self._commit_fn = commit_fn
        self._rollback_fn = rollback_fn

    async def execute(
        self,
        results: list[PredictionMarketFetchResult],
        source_id: UUID | None = None,
    ) -> PredictionMarketFetchSummary:
        """Write each result atomically (fetch_log + outbox) and return a summary.

        Args:
            results: List of parsed prediction market snapshots from the adapter.
            source_id: Optional source UUID for the fetch_log row.
        """
        start = time.monotonic()
        fetched = 0
        skipped = 0
        failed = 0
        errors: list[str] = []

        for result in results:
            try:
                # Event-level idempotency (double-check — adapter dedup is first pass)
                if await self._fetch_log.exists_by_market_snapshot(result.market_id, result.fetched_at):
                    skipped += 1
                    continue

                payload = build_prediction_market_payload(result)

                # Single transaction: fetch_log + outbox (R8 — outbox pattern)
                await self._fetch_log.create_market_fetch_log(
                    source_id=source_id,
                    market_id=result.market_id,
                    snapshot_at=result.fetched_at,
                    resolution_status=result.resolution_status,
                    fetched_at=result.fetched_at,
                )
                await self._outbox.append(
                    aggregate_type="prediction_market",
                    aggregate_id=result.id,
                    event_type="market.prediction.snapshot",
                    topic=MARKET_PREDICTION,
                    payload=payload,
                )
                await self._commit_fn()
                fetched += 1

            except Exception as exc:
                # M-02: roll back immediately so the shared session is not
                # poisoned for subsequent loop iterations.
                await self._rollback_fn()
                failed += 1
                errors.append(f"{result.market_id}: {type(exc).__name__}")
                logger.error(
                    "prediction_market_write_failed",
                    market_id=result.market_id,
                    error=type(exc).__name__,
                )

        duration = time.monotonic() - start
        logger.info(
            "prediction_market_cycle_complete",
            fetched=fetched,
            skipped=skipped,
            failed=failed,
            duration_seconds=round(duration, 3),
        )
        return PredictionMarketFetchSummary(
            fetched=fetched,
            skipped=skipped,
            failed=failed,
            duration_seconds=round(duration, 3),
            errors=errors,
        )
