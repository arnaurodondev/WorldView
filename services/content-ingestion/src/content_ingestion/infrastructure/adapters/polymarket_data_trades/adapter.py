"""Polymarket Data-API ``/trades`` adapter — emits PredictionTradeFetchResult.

Responsibilities:
- Per market ``condition_id`` (read from the ``source.config["markets"]`` work-list
  — PLAN-0056 Wave B4 — or a legacy flat ``condition_ids`` list), offset-paginate
  the trades feed (up to ``max_pages_per_cycle`` pages).
- Deduplication per trade via ``fetch_log_exists_fn`` (trade_id, snapshot_at).
- Raw bytes stored to MinIO bronze (non-fatal on failure).
- Parse errors logged and skipped (non-fatal).

Design notes:
- One ``PredictionTradeFetchResult`` per new (non-duplicate) trade, stamped with
  its parent ``market_id = condition_id`` so S3 trade rows JOIN to
  ``prediction_markets`` (keyed on conditionId) — PLAN-0056 Wave B4.
- ``snapshot_at = fetched_at`` (rounded to the minute) is passed to the dedup
  callback; the natural dedup key is ``trade_id`` (globally unique).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import common.time
from content_ingestion.domain.entities import PredictionTradeFetchResult
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_worklist import parse_markets
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.config import PolymarketTradesProviderSettings
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.polymarket_data_trades.client import PolymarketTradesClient
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BRONZE_BUCKET = "worldview-bronze"


@dataclass(frozen=True, slots=True)
class MarketTradesResult:
    """Outcome of one INCREMENTAL per-market trades fetch (PLAN-0056 QA).

    Attributes:
        results: The NEW (post-cursor) trade fetch-results collected this cycle.
        new_cursor: The advanced per-market cursor to persist durably so the next
            cycle fetches only trades newer than it — ``{"last_trade_ts": int,
            "last_trade_id": str}``. ``None`` when nothing new was collected AND
            there was no prior cursor (leave the stored cursor untouched).
    """

    results: list[PredictionTradeFetchResult]
    new_cursor: dict[str, Any] | None


def _build_bronze_key(trade_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for a single Polymarket trade (legacy path)."""
    d = snapshot_at
    return f"content-ingestion/polymarket-trades/{d.year}/{d.month:02d}/{d.day:02d}/{trade_id}.json"


def _build_batch_bronze_key(condition_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for ONE batched market-cycle trade payload.

    PLAN-0056 QA: the incremental path writes a SINGLE bronze object per
    market-cycle holding all new raw trades (mirroring how the CLOB/history
    adapter writes one object per token-cycle), instead of one object per trade.
    A per-trade object for ~350k trades was the dominant cost driver behind the
    900s timeout deadlock; the Kafka trade event + the S3 trades table are the
    authoritative silver/gold copies, so a batched bronze snapshot is sufficient.
    """
    d = snapshot_at
    return (
        f"content-ingestion/polymarket-trades/{d.year}/{d.month:02d}/{d.day:02d}/"
        f"{condition_id}_{snapshot_at.isoformat()}.json"
    )


def _round_to_minute(dt: datetime) -> datetime:
    """Round a UTC-aware datetime down to the nearest minute (stable dedup key)."""
    return dt.replace(second=0, microsecond=0)


class PolymarketTradesAdapter:
    """S4 adapter that pulls the trades feed for a set of markets.

    Args:
        client: Low-level HTTP client for the Data-API trades endpoint.
        fetch_log_exists_fn: Async callable ``(trade_id, snapshot_at) -> bool``.
        settings: Provider configuration (page_size, max_pages_per_cycle, etc.).
        storage: Object storage backend (MinIO) for bronze-tier raw bytes.
        bucket: Target bucket name.
    """

    def __init__(
        self,
        client: PolymarketTradesClient,
        fetch_log_exists_fn: Callable[[str, datetime], Awaitable[bool]],
        settings: PolymarketTradesProviderSettings,
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
    ) -> list[PredictionTradeFetchResult]:
        """Fetch trades for each configured market condition id.

        Condition ids are read from the ``source.config["markets"]`` work-list
        (PLAN-0056 Wave B4), or a legacy flat ``condition_ids`` list. Returns one
        result per new (non-duplicate) trade, stamped with its parent ``market_id``.

        Args:
            source: The configured polling source (carries the ``markets`` work-list).
            is_backfill: Unused here (offset pagination bounded by max_pages).
            from_date: Unused.
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        condition_ids = self._extract_condition_ids(source)
        if not condition_ids:
            logger.info("polymarket_trades_no_condition_ids", source=source.name)
            return []

        results: list[PredictionTradeFetchResult] = []
        for condition_id in condition_ids:
            results.extend(await self._process_market(condition_id, fetched_at))

        logger.info(
            "polymarket_trades_fetch_complete",
            source=source.name,
            markets=len(condition_ids),
            new=len(results),
        )
        return results

    # ── PLAN-0056 QA — INCREMENTAL + BOUNDED per-market fetch ─────────────────
    #
    # ``fetch_market`` is the path the worker now drives (one market at a time,
    # round-robin windowed, committing a cursor per market). The legacy ``fetch``
    # above is retained for the flat-config / backfill callers and existing tests
    # but is NO LONGER on the steady-state cadence — it re-pulls full history and
    # was the source of the 900s timeout deadlock.

    async def fetch_market(
        self,
        condition_id: str,
        cursor: dict[str, Any] | None,
        *,
        is_backfill: bool = False,
    ) -> MarketTradesResult:
        """Fetch ONLY new trades for one market since ``cursor`` (bounded).

        Trades are append-only, so a per-market high-watermark (last-seen trade
        timestamp) lets each cycle fetch only what is new instead of paginating
        the full 0→~3500 history every time.

        Bounds (all config-driven, no magic numbers):
        - ``max_pages_per_cycle`` pages of ``page_size`` each,
        - ``max_trades_per_market_per_cycle`` NEW trades collected.

        First cycle for a market (no cursor): the watermark floor is
        ``now - backfill_days`` so the initial pull is a BOUNDED backfill of the
        recent window (capped by the trade cap), NEVER the full historical depth.

        Args:
            condition_id: The market ``conditionId`` (the ``market`` query param).
            cursor: The persisted ``{"last_trade_ts", "last_trade_id"}`` or None.
            is_backfill: Unused here (the window is always cursor/backfill_days
                derived); accepted for a uniform call signature.

        Returns:
            :class:`MarketTradesResult` with the new trades + the advanced cursor.
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        floor_ts = self._cursor_floor_ts(cursor, fetched_at)

        collected: list[PredictionTradeFetchResult] = []
        raw_new: list[dict[str, Any]] = []
        max_ts = floor_ts
        max_ts_trade_id: str | None = cursor.get("last_trade_id") if cursor else None
        cap = self._settings.max_trades_per_market_per_cycle

        offset = 0
        page_count = 0
        while True:
            try:
                page = await self._client.fetch_trades_page(
                    market=condition_id,
                    limit=self._settings.page_size,
                    offset=offset,
                )
            except AdapterError as exc:
                # End-of-data 400 AFTER ≥1 good page = benign end of pagination
                # (mirrors the legacy path). A 400 on the FIRST page is a real
                # error → re-raise (retryable).
                if exc.status_code == 400 and page_count >= 1:
                    logger.info(
                        "polymarket_trades_end_of_data_400",
                        condition_id=condition_id,
                        offset=offset,
                        pages=page_count,
                        collected=len(collected),
                    )
                    break
                raise
            except Exception as exc:
                raise AdapterError(f"Trades API fetch failed: {exc}") from exc

            page_count += 1
            if not page.trades:
                break

            new_in_page = 0
            cap_hit = False
            for trade in page.trades:
                ts = self._trade_epoch(trade)
                # Skip trades at/older than the watermark — already ingested (or
                # outside the first-backfill window). ``ts is None`` (unparseable
                # timestamp) is treated as new so we never silently drop a fill.
                if ts is not None and ts <= floor_ts:
                    continue
                new_in_page += 1
                result = self._parse_trade(trade, fetched_at, condition_id)
                if result is None:
                    continue
                collected.append(result)
                raw_new.append(trade)
                if ts is not None and ts > max_ts:
                    max_ts = ts
                    max_ts_trade_id = result.trade_id
                if len(collected) >= cap:
                    cap_hit = True
                    break

            offset += self._settings.page_size
            if cap_hit:
                # BOUNDED backfill / high-churn backstop: stop at the cap and let
                # the cursor advance to the newest seen ts. On a deep first
                # backfill this intentionally ingests only the most-recent ``cap``
                # trades (bounded), not the full depth.
                break
            # Newest-first feeds: a page with zero new trades means we have paged
            # past the watermark → stop. (For an oldest-first feed this never
            # trips early and we simply stop at max_pages — still bounded.)
            if new_in_page == 0:
                break
            if not page.has_more or page_count >= self._settings.max_pages_per_cycle:
                break

        await self._store_batch_bronze(condition_id, raw_new, fetched_at, collected)

        new_cursor: dict[str, Any] | None
        if collected and max_ts_trade_id is not None:
            new_cursor = {"last_trade_ts": max_ts, "last_trade_id": max_ts_trade_id}
        else:
            # Nothing new this cycle → keep the prior cursor unchanged.
            new_cursor = cursor

        logger.info(
            "polymarket_trades_market_fetch_complete",
            condition_id=condition_id,
            pages=page_count,
            new=len(collected),
            floor_ts=floor_ts,
            new_cursor_ts=new_cursor.get("last_trade_ts") if new_cursor else None,
        )
        return MarketTradesResult(results=collected, new_cursor=new_cursor)

    def _cursor_floor_ts(self, cursor: dict[str, Any] | None, fetched_at: datetime) -> int:
        """Return the watermark floor epoch-seconds for an incremental fetch.

        Uses the persisted cursor when present; otherwise the first-cycle
        BOUNDED-backfill floor of ``now - backfill_days``.
        """
        if cursor and cursor.get("last_trade_ts") is not None:
            return int(cursor["last_trade_ts"])
        window = timedelta(days=self._settings.backfill_days)
        return int((fetched_at - window).timestamp())

    @staticmethod
    def _trade_epoch(trade: dict[str, Any]) -> int | None:
        """Extract the trade's Unix epoch-seconds timestamp, or None if absent."""
        raw = trade.get("timestamp")
        if raw is None:
            return None
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_trade(
        trade: dict[str, Any],
        fetched_at: datetime,
        condition_id: str | None,
    ) -> PredictionTradeFetchResult | None:
        """Parse one trade dict into a fetch-result (no dedup, no bronze I/O).

        Cross-cycle idempotency is handled by the persisted cursor (skips already
        seen trades) plus the S3 consumer's ``ON CONFLICT (market_id, trade_id)``;
        the use case still performs the authoritative fetch_log dedup at write
        time. So the incremental path does NOT do a per-trade DB dedup round-trip.
        """
        trade_id = str(trade.get("transactionHash") or trade.get("id") or "")
        if not trade_id:
            logger.debug("polymarket_trades_skip_no_id")
            return None
        try:
            return PredictionTradeFetchResult.from_api_response(trade, fetched_at, condition_id=condition_id)
        except Exception:
            logger.warning("polymarket_trades_parse_failed", trade_id=trade_id, exc_info=True)
            return None

    async def _store_batch_bronze(
        self,
        condition_id: str,
        raw_new: list[dict[str, Any]],
        fetched_at: datetime,
        results: list[PredictionTradeFetchResult],
    ) -> None:
        """Store ONE batched bronze object for this market-cycle (non-fatal).

        Replaces the legacy per-trade MinIO put (the dominant cost driver behind
        the timeout deadlock) with a single object holding all new raw trades,
        and stamps that shared key onto every collected result. A MinIO failure
        is non-fatal — ``minio_bronze_key`` stays None and ingestion continues.
        """
        if not raw_new:
            return
        key = _build_batch_bronze_key(condition_id, fetched_at)
        try:
            payload = json.dumps(raw_new).encode("utf-8")
            await self._storage.put_bytes(
                self._bucket,
                key,
                payload,
                content_type="application/json",
            )
        except Exception:
            logger.warning("polymarket_trades_bronze_store_failed", condition_id=condition_id, exc_info=True)
            return
        # Stamp the shared batch key onto every collected result.
        for i, result in enumerate(results):
            results[i] = dataclasses.replace(result, minio_bronze_key=key)

    @staticmethod
    def _extract_condition_ids(source: Source) -> list[str]:
        """Read the list of market condition ids from the source config.

        Prefers the B4 ``markets`` work-list; falls back to a legacy flat
        ``condition_ids`` / ``market_ids`` list for backward compatibility.
        """
        markets = parse_markets(source.config)
        if markets:
            return [m.condition_id for m in markets if m.condition_id]
        raw = source.config.get("condition_ids") or source.config.get("market_ids") or []
        if not isinstance(raw, list):
            return []
        return [str(c) for c in raw if c]

    async def _process_market(
        self,
        condition_id: str,
        fetched_at: datetime,
    ) -> list[PredictionTradeFetchResult]:
        """Offset-paginate and process all new trades for one market."""
        results: list[PredictionTradeFetchResult] = []
        offset = 0
        page_count = 0

        while True:
            try:
                page = await self._client.fetch_trades_page(
                    market=condition_id,
                    limit=self._settings.page_size,
                    offset=offset,
                )
            except AdapterError as exc:
                # End-of-data fallback: the Data-API ``/trades`` endpoint returns
                # HTTP 400 once the paginated offset exceeds available history
                # (~offset 3500 for high-volume markets). This is a NORMAL
                # end-of-pagination signal, NOT a fatal error — treating it as
                # fatal previously DISCARDED every trade collected this cycle and
                # failed the whole task (prediction_market_trades stuck at 0).
                #
                # We cannot cleanly distinguish an offset-exhausted 400 from a
                # genuine bad-request 400 by body shape, so we mirror the CLOB
                # resolved-market benign-400 handling: a 400 AFTER at least one
                # successful page is end-of-data (break, keep collected trades);
                # a 400 on the FIRST page is a real error (re-raise → retryable).
                if exc.status_code == 400 and page_count >= 1:
                    logger.info(
                        "polymarket_trades_end_of_data_400",
                        condition_id=condition_id,
                        offset=offset,
                        pages=page_count,
                        collected=len(results),
                    )
                    break
                raise
            except Exception as exc:
                raise AdapterError(f"Trades API fetch failed: {exc}") from exc

            page_count += 1

            # Empty page → no more trades to paginate. ``has_more`` already
            # covers the full-page heuristic, but an explicitly empty page is an
            # unambiguous end-of-data signal; break and keep collected trades.
            if not page.trades:
                break

            for trade in page.trades:
                # B4: thread the parent conditionId so the trade carries market_id.
                result = await self._process_trade(trade, fetched_at, condition_id)
                if result is not None:
                    results.append(result)

            offset += self._settings.page_size
            if not page.has_more or page_count >= self._settings.max_pages_per_cycle:
                break

        return results

    async def _process_trade(
        self,
        trade: dict[str, Any],
        fetched_at: datetime,
        condition_id: str | None = None,
    ) -> PredictionTradeFetchResult | None:
        """Dedup, parse and store a single trade dict."""
        trade_id: str = str(trade.get("transactionHash") or trade.get("id") or "")
        if not trade_id:
            logger.debug("polymarket_trades_skip_no_id")
            return None

        # Dedup check.
        try:
            if await self._fetch_log_exists_fn(trade_id, fetched_at):
                logger.debug("polymarket_trades_dedup_skip", trade_id=trade_id)
                return None
        except Exception as exc:
            logger.warning("polymarket_trades_dedup_check_failed", trade_id=trade_id, error=str(exc))
            return None

        # Parse.
        try:
            result = PredictionTradeFetchResult.from_api_response(trade, fetched_at, condition_id=condition_id)
        except Exception:
            logger.warning("polymarket_trades_parse_failed", trade_id=trade_id, exc_info=True)
            return None

        # Store raw bytes to MinIO bronze (non-fatal on failure).
        #
        # Inode-exhaustion P0 (2026-07-16): one bronze object PER trade fill —
        # gated OFF by default (``bronze_archive_enabled``) because nothing reads
        # these objects back (the live path materialises from the
        # ``market.prediction.trade.v1`` Kafka payload). When disabled we skip the
        # put and leave ``minio_bronze_key`` None (same as the put-failure branch).
        if self._settings.bronze_archive_enabled:
            minio_key = _build_bronze_key(trade_id, fetched_at)
            try:
                raw_payload = json.dumps(trade).encode("utf-8")
                await self._storage.put_bytes(
                    self._bucket,
                    minio_key,
                    raw_payload,
                    content_type="application/json",
                )
                result = dataclasses.replace(result, minio_bronze_key=minio_key)
            except Exception:
                logger.warning("polymarket_trades_minio_store_failed", trade_id=trade_id, exc_info=True)
                # minio_bronze_key stays None — non-fatal.

        return result
