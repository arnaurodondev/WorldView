"""Polymarket Data-API open-interest adapter — emits PredictionOIFetchResult.

Responsibilities:
- Per market ``condition_id`` (read from ``source.config["condition_ids"]``),
  fetch one open-interest snapshot (daily cadence).
- Deduplication via ``fetch_log_exists_fn`` (market_id, snapshot_at).
- Raw bytes stored to MinIO bronze (non-fatal on failure).
- Parse errors logged and skipped (non-fatal).

Design notes:
- One ``PredictionOIFetchResult`` per market per snapshot day.
- ``snapshot_at = fetched_at`` (rounded to the minute) for stable dedup.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import TYPE_CHECKING

import common.time
from content_ingestion.domain.entities import PredictionOIFetchResult
from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.config import PolymarketOIProviderSettings
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.polymarket_data_oi.client import PolymarketOIClient
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BRONZE_BUCKET = "worldview-bronze"


def _build_bronze_key(market_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for an open-interest snapshot."""
    d = snapshot_at
    return (
        f"content-ingestion/polymarket-oi/{d.year}/{d.month:02d}/{d.day:02d}/{market_id}_{snapshot_at.isoformat()}.json"
    )


def _round_to_minute(dt: datetime) -> datetime:
    """Round a UTC-aware datetime down to the nearest minute (stable dedup key)."""
    return dt.replace(second=0, microsecond=0)


class PolymarketOIAdapter:
    """S4 adapter that snapshots open interest for a set of markets.

    Args:
        client: Low-level HTTP client for the Data-API open-interest endpoint.
        fetch_log_exists_fn: Async callable ``(market_id, snapshot_at) -> bool``.
        settings: Provider configuration.
        storage: Object storage backend (MinIO) for bronze-tier raw bytes.
        bucket: Target bucket name.
    """

    def __init__(
        self,
        client: PolymarketOIClient,
        fetch_log_exists_fn: Callable[[str, datetime], Awaitable[bool]],
        settings: PolymarketOIProviderSettings,
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
    ) -> list[PredictionOIFetchResult]:
        """Fetch one open-interest snapshot per configured market condition id.

        Condition ids are read from ``source.config["condition_ids"]`` (seeded in
        a later wave).

        Args:
            source: The configured polling source (carries ``condition_ids``).
            is_backfill: Unused (snapshot-based, daily).
            from_date: Unused.
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        condition_ids = self._extract_condition_ids(source)
        if not condition_ids:
            logger.info("polymarket_oi_no_condition_ids", source=source.name)
            return []

        results: list[PredictionOIFetchResult] = []
        for condition_id in condition_ids:
            result = await self._process_market(condition_id, fetched_at)
            if result is not None:
                results.append(result)

        logger.info(
            "polymarket_oi_fetch_complete",
            source=source.name,
            markets=len(condition_ids),
            new=len(results),
        )
        return results

    @staticmethod
    def _extract_condition_ids(source: Source) -> list[str]:
        """Read the list of market condition ids from the source config."""
        raw = source.config.get("condition_ids") or source.config.get("market_ids") or []
        if not isinstance(raw, list):
            return []
        return [str(c) for c in raw if c]

    async def _process_market(
        self,
        condition_id: str,
        fetched_at: datetime,
    ) -> PredictionOIFetchResult | None:
        """Dedup, fetch, parse and store one market's OI snapshot."""
        # Dedup check.
        try:
            if await self._fetch_log_exists_fn(condition_id, fetched_at):
                logger.debug("polymarket_oi_dedup_skip", market_id=condition_id)
                return None
        except Exception as exc:
            logger.warning("polymarket_oi_dedup_check_failed", market_id=condition_id, error=str(exc))
            return None

        try:
            raw = await self._client.fetch_open_interest(market=condition_id)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterError(f"OI API fetch failed: {exc}") from exc

        # Parse.
        try:
            result = PredictionOIFetchResult.from_api_response(condition_id, raw, fetched_at)
        except Exception:
            logger.warning("polymarket_oi_parse_failed", market_id=condition_id, exc_info=True)
            return None

        # Store raw bytes to MinIO bronze (non-fatal on failure).
        #
        # Inode-exhaustion P0 (2026-07-16): gated OFF by default
        # (``bronze_archive_enabled``) — these objects are never read back (the
        # live path materialises from the ``market.prediction.oi.v1`` Kafka
        # payload). When disabled we skip the put and leave ``minio_bronze_key``
        # None (same as the put-failure branch).
        if self._settings.bronze_archive_enabled:
            minio_key = _build_bronze_key(condition_id, fetched_at)
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
                logger.warning("polymarket_oi_minio_store_failed", market_id=condition_id, exc_info=True)
                # minio_bronze_key stays None — non-fatal.

        return result
