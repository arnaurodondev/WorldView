"""Polymarket CLOB ``/prices-history`` adapter — emits PredictionHistoryFetchResult.

Responsibilities:
- Per market ``condition_id`` and its child CLOB ``token_ids`` (read from the
  ``source.config["markets"]`` work-list — PLAN-0056 Wave B4), fetch the price
  series.  The parent ``condition_id`` is threaded onto each fetch-result as
  ``market_id`` so S3 price rows JOIN to ``prediction_markets`` (keyed on
  conditionId) instead of the per-outcome ``token_id``.  A legacy flat
  ``token_ids`` list is still honoured with ``condition_id = None``.
- **Resolved-market fallback**: if the primary interval (``1h``) request returns
  HTTP 400 or an EMPTY series, retry once at the coarser ``fallback_interval``
  (``1d``) — resolved markets frequently have no fine-grained series (PRD-0033
  §4.4/§9.2).
- Backfill window (``backfill_days``) vs ongoing incremental window
  (``ongoing_window_hours``) chosen via the ``is_backfill`` flag → ``startTs``.
- Deduplication via ``fetch_log_exists_fn`` (token_id, snapshot_at).
- Raw bytes stored to MinIO bronze (non-fatal on failure).

Design notes:
- One ``PredictionHistoryFetchResult`` per token_id that returns ≥1 datapoint.
  Tokens with no data even at the fallback interval are skipped (no empty result).
- ``snapshot_at = fetched_at`` (rounded to the minute) for stable dedup.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import common.time
from content_ingestion.domain.entities import PredictionHistoryFetchResult
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_worklist import MarketWorkItem, parse_markets
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.config import PolymarketClobProviderSettings
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.polymarket_clob.client import PolymarketClobHistoryClient
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BRONZE_BUCKET = "worldview-bronze"


@dataclass(frozen=True, slots=True)
class MarketHistoryResult:
    """Outcome of one INCREMENTAL per-market CLOB history fetch (PLAN-0056 QA).

    Attributes:
        results: The NEW (post-cursor) per-token history fetch-results collected
            this cycle, each already trimmed to points newer than the cursor.
        new_cursor: The advanced per-market cursor to persist durably so the next
            cycle fetches only points newer than it — ``{"last_point_ts": int}``
            (Unix epoch-seconds of the newest point emitted). Left equal to the
            prior cursor when nothing new was collected this cycle.
    """

    results: list[PredictionHistoryFetchResult]
    new_cursor: dict[str, Any] | None


def _build_bronze_key(token_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for a CLOB price-history snapshot."""
    d = snapshot_at
    return (
        f"content-ingestion/polymarket-clob/{d.year}/{d.month:02d}/{d.day:02d}/"
        f"{token_id}_{snapshot_at.isoformat()}.json"
    )


def _round_to_minute(dt: datetime) -> datetime:
    """Round a UTC-aware datetime down to the nearest minute (stable dedup key)."""
    return dt.replace(second=0, microsecond=0)


class PolymarketClobHistoryAdapter:
    """S4 adapter that pulls CLOB price history for a set of token ids.

    Args:
        client: Low-level HTTP client for the CLOB prices-history API.
        fetch_log_exists_fn: Async callable ``(token_id, snapshot_at) -> bool``.
        settings: Provider configuration (intervals, windows, etc.).
        storage: Object storage backend (MinIO) for bronze-tier raw bytes.
        bucket: Target bucket name.
    """

    def __init__(
        self,
        client: PolymarketClobHistoryClient,
        fetch_log_exists_fn: Callable[[str, datetime], Awaitable[bool]],
        settings: PolymarketClobProviderSettings,
        storage: ObjectStorage,
        bucket: str = _BRONZE_BUCKET,
    ) -> None:
        self._client = client
        self._fetch_log_exists_fn = fetch_log_exists_fn
        self._settings = settings
        self._storage = storage
        self._bucket = bucket

    async def fetch(
        self,
        source: Source,
        *,
        is_backfill: bool = False,
        from_date: str = "",
    ) -> list[PredictionHistoryFetchResult]:
        """Fetch CLOB price history for each configured token id.

        The market work-list (parent ``condition_id`` + child ``token_ids``) is
        read from ``source.config["markets"]`` (PLAN-0056 Wave B4); a legacy flat
        ``token_ids`` list is honoured with an unknown parent. Returns one result
        per token that yields ≥1 datapoint, stamped with its parent ``market_id``.

        Args:
            source: The configured polling source (carries the ``markets`` work-list).
            is_backfill: When True use the ``backfill_days`` window, else the
                ``ongoing_window_hours`` incremental window.
            from_date: Unused (window derived from settings + is_backfill).
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        markets = self._extract_markets(source)
        token_count = sum(len(m.token_ids) for m in markets)
        if token_count == 0:
            logger.info("polymarket_clob_no_token_ids", source=source.name)
            return []

        if is_backfill:
            window = timedelta(days=self._settings.backfill_days)
        else:
            window = timedelta(hours=self._settings.ongoing_window_hours)
        start_ts = int((fetched_at - window).timestamp())

        results: list[PredictionHistoryFetchResult] = []
        for market in markets:
            for token_id in market.token_ids:
                # B4: thread the parent conditionId so the result carries market_id.
                result = await self._process_token(token_id, fetched_at, start_ts, market.condition_id)
                if result is not None:
                    results.append(result)

        logger.info(
            "polymarket_clob_fetch_complete",
            source=source.name,
            markets=len(markets),
            tokens=token_count,
            new=len(results),
        )
        return results

    # ── PLAN-0056 QA — INCREMENTAL + BOUNDED per-market history fetch ─────────
    #
    # ``fetch_market`` is the path the worker now drives (one market at a time,
    # round-robin windowed, committing a cursor per market). The legacy ``fetch``
    # above is retained for the flat-config / backfill callers and existing tests
    # but is NO LONGER on the steady-state cadence — it re-pulls the full
    # ``backfill_days`` depth for every token every cycle and, because the history
    # payload emits ONE outbox event per datapoint, was the source of the
    # ``market.prediction.history.v1`` firehose that starved the FIFO dispatcher.

    async def fetch_market(
        self,
        market: MarketWorkItem,
        cursor: dict[str, Any] | None,
        *,
        is_backfill: bool = False,
    ) -> MarketHistoryResult:
        """Fetch ONLY new price points for one market since ``cursor`` (bounded).

        Price history is append-only in time, so a per-market high-watermark
        (last-seen point timestamp) lets each cycle emit only what is new instead
        of re-emitting the full ``backfill_days`` depth for every token every
        cycle (the firehose that starved the outbox dispatcher).

        Bounds (all config-driven, no magic numbers):
        - the CLOB ``startTs`` window floor is the cursor (or the first-cycle
          ``now - backfill_days`` bounded-backfill floor),
        - ``max_points_per_market_per_cycle`` NEW points collected across the
          market's outcome tokens; a deeper backfill drains oldest-first over
          subsequent cycles rather than flooding a single cycle.

        Args:
            market: The market work-item (parent ``condition_id`` + child token ids).
            cursor: The persisted ``{"last_point_ts": int}`` or None (first cycle).
            is_backfill: Accepted for a uniform call signature; the window is
                always cursor/``backfill_days``-derived.

        Returns:
            :class:`MarketHistoryResult` with the new per-token results + cursor.
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        floor_ts = self._cursor_floor_ts(cursor, fetched_at)
        cap = self._settings.max_points_per_market_per_cycle

        collected: list[PredictionHistoryFetchResult] = []
        max_ts = floor_ts
        total_points = 0

        for token_id in market.token_ids:
            if total_points >= cap:
                break
            # Ask the API for points since the watermark; _process_token applies
            # the resolved-market 1h→1d fallback + writes bronze.
            result = await self._process_token(token_id, fetched_at, floor_ts, market.condition_id)
            if result is None:
                continue
            # Incremental: keep only points STRICTLY newer than the cursor floor.
            new_points = [p for p in result.points if int(p.timestamp.timestamp()) > floor_ts]
            if not new_points:
                continue
            # BOUNDED: cap the total NEW points collected for this market-cycle.
            # Points are chronological (oldest-first), so trimming to the first
            # ``remaining`` drains oldest-first and advances the cursor gradually —
            # the newer points are re-fetched next cycle (no permanent loss).
            remaining = cap - total_points
            if len(new_points) > remaining:
                new_points = new_points[:remaining]
            total_points += len(new_points)
            for p in new_points:
                ep = int(p.timestamp.timestamp())
                if ep > max_ts:
                    max_ts = ep
            collected.append(dataclasses.replace(result, points=new_points))

        # Advance the cursor to the newest emitted point; keep it unchanged when
        # nothing new arrived so a quiet cycle does not reset the watermark.
        new_cursor: dict[str, Any] | None
        new_cursor = {"last_point_ts": max_ts} if collected else cursor

        logger.info(
            "polymarket_clob_market_fetch_complete",
            condition_id=market.condition_id,
            tokens=len(market.token_ids),
            new_results=len(collected),
            new_points=total_points,
            floor_ts=floor_ts,
            new_cursor_ts=new_cursor.get("last_point_ts") if new_cursor else None,
        )
        return MarketHistoryResult(results=collected, new_cursor=new_cursor)

    def _cursor_floor_ts(self, cursor: dict[str, Any] | None, fetched_at: datetime) -> int:
        """Return the watermark floor epoch-seconds for an incremental fetch.

        Uses the persisted cursor when present; otherwise the first-cycle
        BOUNDED-backfill floor of ``now - backfill_days``.
        """
        if cursor and cursor.get("last_point_ts") is not None:
            return int(cursor["last_point_ts"])
        window = timedelta(days=self._settings.backfill_days)
        return int((fetched_at - window).timestamp())

    @staticmethod
    def _extract_markets(source: Source) -> list[MarketWorkItem]:
        """Read the CLOB market work-list (parent condition_id + child token_ids).

        Prefers the B4 ``markets`` work-list; falls back to a legacy flat
        ``token_ids`` / ``clob_token_ids`` list with an unknown parent
        (``condition_id = None``) for backward compatibility.
        """
        markets = parse_markets(source.config)
        if markets:
            return markets
        raw = source.config.get("token_ids") or source.config.get("clob_token_ids") or []
        if not isinstance(raw, list):
            return []
        tokens = [str(t) for t in raw if t]
        return [MarketWorkItem(condition_id=None, token_ids=tokens)] if tokens else []

    async def _process_token(
        self,
        token_id: str,
        fetched_at: datetime,
        start_ts: int,
        condition_id: str | None = None,
    ) -> PredictionHistoryFetchResult | None:
        """Fetch, dedup, parse and store one token's price history.

        Applies the resolved-market fallback (``1h`` → ``1d`` on HTTP 400 or an
        empty series). Returns ``None`` on dedup hit, parse error, or no data.
        """
        # Dedup check.
        try:
            if await self._fetch_log_exists_fn(token_id, fetched_at):
                logger.debug("polymarket_clob_dedup_skip", token_id=token_id)
                return None
        except Exception as exc:
            logger.warning("polymarket_clob_dedup_check_failed", token_id=token_id, error=str(exc))
            return None

        interval = self._settings.interval
        try:
            raw = await self._client.fetch_price_history(
                token_id=token_id,
                interval=interval,
                start_ts=start_ts,
                fidelity=self._settings.fidelity,
            )
        except AdapterError as exc:
            # Resolved-market fallback: HTTP 400 on the fine-grained interval →
            # retry at the coarser fallback interval. Any other status re-raises
            # (worker treats AdapterError as retryable).
            if exc.status_code == 400:
                logger.debug(
                    "polymarket_clob_fallback_on_400",
                    token_id=token_id,
                    fallback_interval=self._settings.fallback_interval,
                )
                interval = self._settings.fallback_interval
                raw = await self._client.fetch_price_history(
                    token_id=token_id,
                    interval=interval,
                    start_ts=start_ts,
                    fidelity=self._settings.fidelity,
                )
            else:
                raise

        # Empty series on the fine-grained interval → retry at the fallback.
        history = raw.get("history") if isinstance(raw, dict) else None
        if (not history) and interval != self._settings.fallback_interval:
            logger.debug(
                "polymarket_clob_fallback_on_empty",
                token_id=token_id,
                fallback_interval=self._settings.fallback_interval,
            )
            interval = self._settings.fallback_interval
            raw = await self._client.fetch_price_history(
                token_id=token_id,
                interval=interval,
                start_ts=start_ts,
                fidelity=self._settings.fidelity,
            )

        # Parse.
        try:
            result = PredictionHistoryFetchResult.from_api_response(
                token_id,
                raw,
                fetched_at,
                interval=interval,
                condition_id=condition_id,
            )
        except Exception:
            logger.warning("polymarket_clob_parse_failed", token_id=token_id, exc_info=True)
            return None

        # Skip tokens that genuinely have no datapoints even after the fallback.
        if not result.points:
            logger.debug("polymarket_clob_no_datapoints", token_id=token_id)
            return None

        # Store raw bytes to MinIO bronze (non-fatal on failure).
        minio_key = _build_bronze_key(token_id, fetched_at)
        try:
            raw_payload = json.dumps(raw).encode("utf-8")
            await self._storage.put_bytes(
                self._bucket,
                minio_key,
                raw_payload,
                content_type="application/json",
            )
            result = dataclasses.replace(result, minio_bronze_key=minio_key)
        except Exception:
            logger.warning("polymarket_clob_minio_store_failed", token_id=token_id, exc_info=True)
            # minio_bronze_key stays None — non-fatal.

        return result
