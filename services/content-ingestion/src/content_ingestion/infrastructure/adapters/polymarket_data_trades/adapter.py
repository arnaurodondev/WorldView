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
from datetime import datetime
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


def _build_bronze_key(trade_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for a single Polymarket trade."""
    d = snapshot_at
    return f"content-ingestion/polymarket-trades/{d.year}/{d.month:02d}/{d.day:02d}/{trade_id}.json"


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
            except AdapterError:
                raise
            except Exception as exc:
                raise AdapterError(f"Trades API fetch failed: {exc}") from exc

            page_count += 1

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
