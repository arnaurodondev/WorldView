"""Polymarket Gamma ``/events`` adapter — emits PredictionEventFetchResult.

Responsibilities (mirrors :class:`PolymarketAdapter`):
- Cursor-paginated fetch from the Gamma ``/events`` endpoint (up to
  ``max_pages_per_cycle`` pages).
- Deduplication via ``fetch_log_exists_fn`` (event_id, snapshot_at).
- Raw bytes stored to MinIO bronze at a deterministic key (non-fatal on failure).
- Parse errors logged and skipped (non-fatal).

Key design notes:
- ``snapshot_at = fetched_at`` (rounded to the nearest minute) — all events in a
  single poll cycle share the same snapshot timestamp for stable dedup.
- Frozen ``PredictionEventFetchResult`` is updated via ``dataclasses.replace()``.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import common.time
from content_ingestion.domain.entities import PredictionEventFetchResult
from content_ingestion.domain.exceptions import AdapterError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.config import PolymarketEventsProviderSettings
    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.polymarket_gamma_events.client import PolymarketEventsClient
    from storage.interface import ObjectStorage  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BRONZE_BUCKET = "worldview-bronze"


def _build_bronze_key(event_id: str, snapshot_at: datetime) -> str:
    """Build the MinIO bronze key for a Polymarket event snapshot."""
    d = snapshot_at
    return (
        f"content-ingestion/polymarket-events/{d.year}/{d.month:02d}/{d.day:02d}/"
        f"{event_id}_{snapshot_at.isoformat()}.json"
    )


def _round_to_minute(dt: datetime) -> datetime:
    """Round a UTC-aware datetime down to the nearest minute (stable dedup key)."""
    return dt.replace(second=0, microsecond=0)


class PolymarketEventsAdapter:
    """S4 adapter that polls the Polymarket Gamma ``/events`` endpoint.

    Args:
        client: Low-level HTTP client for the Gamma events API.
        fetch_log_exists_fn: Async callable ``(event_id, snapshot_at) -> bool``
            — returns True if this (event_id, snapshot_at) pair was already processed.
        settings: Provider configuration (page_size, max_pages_per_cycle, etc.).
        storage: Object storage backend (MinIO) for bronze-tier raw bytes.
        bucket: Target bucket name.
    """

    def __init__(
        self,
        client: PolymarketEventsClient,
        fetch_log_exists_fn: Callable[[str, datetime], Awaitable[bool]],
        settings: PolymarketEventsProviderSettings,
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
    ) -> list[PredictionEventFetchResult]:
        """Fetch active Polymarket events for one poll cycle.

        Returns a list of new (non-duplicate) ``PredictionEventFetchResult``
        objects, each with ``minio_bronze_key`` populated.

        Args:
            source: The configured polling source (used for logging only).
            is_backfill: Unused for events (snapshot-based, not date-based).
            from_date: Unused for events.
        """
        fetched_at = _round_to_minute(common.time.utc_now())
        results: list[PredictionEventFetchResult] = []
        cursor: str | None = None
        page_count = 0

        while True:
            try:
                page = await self._client.fetch_events_page(
                    limit=self._settings.page_size,
                    next_cursor=cursor,
                )
            except AdapterError:
                raise
            except Exception as exc:
                raise AdapterError(f"Gamma events API fetch failed: {exc}") from exc

            page_count += 1

            for event in page.events:
                result = await self._process_event(event, fetched_at)
                if result is not None:
                    results.append(result)

            cursor = page.next_cursor
            if cursor is None or page_count >= self._settings.max_pages_per_cycle:
                break

        logger.info(
            "polymarket_events_fetch_complete",
            source=source.name,
            pages=page_count,
            new=len(results),
        )
        return results

    async def _process_event(
        self,
        event: dict[str, Any],
        fetched_at: datetime,
    ) -> PredictionEventFetchResult | None:
        """Process a single event dict from a Gamma events page.

        Returns a ``PredictionEventFetchResult`` with ``minio_bronze_key`` set,
        or ``None`` if the event should be skipped (dedup hit or parse error).
        """
        event_id: str = str(event.get("id") or event.get("slug") or "")
        if not event_id:
            logger.debug("polymarket_events_skip_no_id")
            return None

        # Dedup check — skip if already processed for this snapshot time.
        try:
            if await self._fetch_log_exists_fn(event_id, fetched_at):
                logger.debug("polymarket_events_dedup_skip", event_id=event_id)
                return None
        except Exception as exc:
            logger.warning("polymarket_events_dedup_check_failed", event_id=event_id, error=str(exc))
            return None

        # Parse
        try:
            result = PredictionEventFetchResult.from_gamma_response(event, fetched_at)
        except Exception:
            logger.warning("polymarket_events_parse_failed", event_id=event_id, exc_info=True)
            return None

        # Store raw bytes to MinIO bronze (non-fatal on failure).
        #
        # Inode-exhaustion P0 (2026-07-16): gated OFF by default
        # (``bronze_archive_enabled``) — these objects are never read back (the
        # live path materialises from the ``market.prediction.event.v1`` Kafka
        # payload, which does not carry ``minio_bronze_key``). When disabled we
        # skip the put and leave ``minio_bronze_key`` None (same as put-failure).
        if self._settings.bronze_archive_enabled:
            minio_key = _build_bronze_key(event_id, fetched_at)
            try:
                raw_payload = json.dumps(event).encode("utf-8")
                await self._storage.put_bytes(
                    self._bucket,
                    minio_key,
                    raw_payload,
                    content_type="application/json",
                )
                result = dataclasses.replace(result, minio_bronze_key=minio_key)
            except Exception:
                logger.warning("polymarket_events_minio_store_failed", event_id=event_id, exc_info=True)
                # minio_bronze_key stays None — non-fatal.

        return result
