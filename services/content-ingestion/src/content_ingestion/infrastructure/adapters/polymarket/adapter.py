"""Polymarket source adapter — polls Gamma API and emits PredictionMarketFetchResult.

Responsibilities:
- Cursor-paginated fetch from Gamma API (up to max_pages_per_cycle pages).
- Deduplication via fetch_log_exists_fn (market_id, snapshot_at).
- Raw bytes stored to MinIO bronze at a deterministic key.
- Parse errors logged and skipped (non-fatal); MinIO failures non-fatal.

Key design notes:
- ``snapshot_at = fetched_at`` (rounded to nearest minute) — all markets in
  a single poll cycle share the same snapshot timestamp for stable dedup.
- Frozen ``PredictionMarketFetchResult`` is updated via ``dataclasses.replace()``.
- No DB session in ``fetch()`` — only the injected ``fetch_log_exists_fn`` callable.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import common.time
from content_ingestion.domain.entities import PredictionMarketFetchResult
from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.config import PolymarketProviderSettings
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.polymarket.client import PolymarketClient
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BRONZE_BUCKET = "worldview-bronze"


def _build_bronze_key(market_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for a Polymarket market snapshot."""
    d = snapshot_at
    return f"content-ingestion/polymarket/{d.year}/{d.month:02d}/{d.day:02d}/{market_id}_{snapshot_at.isoformat()}.json"


def _round_to_minute(dt: datetime) -> datetime:
    """Round a UTC-aware datetime down to the nearest minute (stable dedup key)."""
    return dt.replace(second=0, microsecond=0)


class PolymarketAdapter:
    """S4 adapter that polls the Polymarket Gamma API.

    Args:
        client: Low-level HTTP client for the Gamma API.
        fetch_log_exists_fn: Async callable ``(market_id, snapshot_at) -> bool``
            — returns True if this (market_id, snapshot_at) pair was already processed.
        settings: Provider configuration (page_size, max_pages_per_cycle, etc.).
        storage: Object storage backend (MinIO) for bronze-tier raw bytes.
        bucket: Target bucket name.
    """

    def __init__(
        self,
        client: PolymarketClient,
        fetch_log_exists_fn: Callable[[str, datetime], Awaitable[bool]],
        settings: PolymarketProviderSettings,
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
    ) -> list[PredictionMarketFetchResult]:
        """Fetch active Polymarket markets for one poll cycle.

        Returns a list of new (non-duplicate) ``PredictionMarketFetchResult``
        objects, each with ``minio_bronze_key`` populated.

        Args:
            source: The configured polling source (used for logging only).
            is_backfill: Unused for Polymarket (snapshot-based, not date-based).
            from_date: Unused for Polymarket.
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        results: list[PredictionMarketFetchResult] = []
        cursor: str | None = None
        page_count = 0

        while True:
            try:
                page = await self._client.fetch_markets_page(
                    limit=self._settings.page_size,
                    next_cursor=cursor,
                )
            except AdapterError:
                raise
            except Exception as exc:
                raise AdapterError(f"Gamma API fetch failed: {exc}") from exc

            page_count += 1

            for market in page.markets:
                result = await self._process_market(market, fetched_at)
                if result is not None:
                    results.append(result)

            cursor = page.next_cursor
            if cursor is None or page_count >= self._settings.max_pages_per_cycle:
                break

        logger.info(
            "polymarket_fetch_complete",
            source=source.name,
            pages=page_count,
            new=len(results),
        )
        return results

    async def _process_market(
        self,
        market: dict[str, Any],
        fetched_at: datetime,
    ) -> PredictionMarketFetchResult | None:
        """Process a single market dict from a Gamma API page.

        Returns a ``PredictionMarketFetchResult`` with ``minio_bronze_key`` set,
        or ``None`` if the market should be skipped (dedup hit or parse error).
        """
        market_id: str = market.get("conditionId", "")

        # Dedup check — skip if already processed for this snapshot time
        try:
            if await self._fetch_log_exists_fn(market_id, fetched_at):
                logger.debug("polymarket_dedup_skip", market_id=market_id)
                return None
        except Exception as exc:
            logger.warning("polymarket_dedup_check_failed", market_id=market_id, error=str(exc))
            return None

        # Parse
        try:
            result = PredictionMarketFetchResult.from_gamma_response(market, fetched_at)
        except Exception:
            logger.warning("polymarket_market_parse_failed", market_id=market_id, exc_info=True)
            return None

        # Store raw bytes to MinIO bronze (non-fatal on failure)
        minio_key = _build_bronze_key(market_id, fetched_at)
        try:
            raw_payload = json.dumps(market).encode("utf-8")
            await self._storage.put_bytes(
                self._bucket,
                minio_key,
                raw_payload,
                content_type="application/json",
            )
            result = dataclasses.replace(result, minio_bronze_key=minio_key)
        except Exception:
            logger.warning("polymarket_minio_store_failed", market_id=market_id, exc_info=True)
            # minio_bronze_key stays None — non-fatal

        return result
