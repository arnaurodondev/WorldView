"""Watchlist consumer — invalidates the watchlist cache on item_deleted events.

Consumer group: ``alert-service-watchlist-group``
Topic:          ``portfolio.watchlist.updated.v1``

Behaviour:
- ``watchlist.item_added``  → no-op (cache is populated on next lookup).
- ``watchlist.item_deleted`` → DEL Valkey key for each affected entity so
  that the next fan-out lookup fetches fresh data from S1.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.infrastructure.cache.watchlist_cache import WatchlistCache

logger = get_logger(__name__)  # type: ignore[no-any-return]

_EVENT_TYPE_DELETED = "watchlist.item_deleted"


# ── Minimal no-op UoW ─────────────────────────────────────────────────────────


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ── Consumer ──────────────────────────────────────────────────────────────────


class WatchlistConsumer(BaseKafkaConsumer[None]):
    """Consumes ``portfolio.watchlist.updated.v1`` and invalidates cache entries.

    Args:
        config: Consumer configuration (group_id should be
            ``alert-service-watchlist-group``).
        watchlist_cache: Cache instance whose entries to invalidate.
        dedup_client: Optional Valkey client for event deduplication.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        watchlist_cache: WatchlistCache,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._cache = watchlist_cache
        self._dedup_client = dedup_client
        self._dedup_prefix = f"s10:dedup:{config.group_id}"

    # ── Core processing ───────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        event_type: str = str(value.get("event_type", ""))
        entity_id: str = str(value.get("entity_id", ""))
        entity_ids_affected: list[str] = [str(e) for e in value.get("entity_ids_affected", [])]

        if event_type != _EVENT_TYPE_DELETED:
            # item_added → cache is populated on next lookup; nothing to do.
            logger.debug(  # type: ignore[no-any-return]
                "watchlist_consumer.skip_non_delete",
                event_type=event_type,
            )
            return

        # Invalidate the single entity and any additionally affected entities.
        targets: list[str] = []
        if entity_id:
            targets.append(entity_id)
        for eid in entity_ids_affected:
            if eid and eid not in targets:
                targets.append(eid)

        for eid in targets:
            await self._cache.invalidate(eid)
            logger.info(  # type: ignore[no-any-return]
                "watchlist_consumer.cache_invalidated",
                entity_id=eid,
                user_id=str(value.get("user_id", "")),
            )

    # ── Retry / failure (log-only) ────────────────────────────────────────────

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "watchlist_consumer.retry_not_supported",
            event_id=failure.event_id,
        )

    # ── Idempotency (Valkey-backed with no-op fallback) ───────────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        return bool(await self._dedup_client.exists(key))

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        await self._dedup_client.set(key, "1", ex=86400)

    # ── Failure tracking (log-only) ───────────────────────────────────────────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "watchlist_consumer.failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
            attempt=failure.attempt,
        )
        return None

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "watchlist_consumer.failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "watchlist_consumer.dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── UoW (no-op) ───────────────────────────────────────────────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
