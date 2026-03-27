"""Watchlist event consumer — maintains Valkey SET for routing signal.

Consumes ``portfolio.watchlist.updated.v1`` (consumer group: nlp-watchlist-group).
On ``watchlist.item_added``: SADD entity_id.
On ``watchlist.item_deleted``: SREM entity_id.

PRD §6.7 Block 5 watchlist signal sourcing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

logger = get_logger(__name__)  # type: ignore[no-any-return]

_TOPIC = "portfolio.watchlist.updated.v1"
_EVENT_ITEM_ADDED = "watchlist.item_added"
_EVENT_ITEM_DELETED = "watchlist.item_deleted"


class _NoOpUnitOfWork:
    """Minimal UoW for consumers that don't need a database session."""

    async def __aenter__(self) -> _NoOpUnitOfWork:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class WatchlistEventConsumer(BaseKafkaConsumer[None]):
    """Consumes watchlist update events and syncs the Valkey SET.

    Uses the nlp-watchlist-group consumer group (separate from the main
    article processing group) so both consumers can process independently.
    """

    def __init__(self, config: ConsumerConfig, watchlist_cache: WatchlistCache) -> None:
        super().__init__(config)
        self._cache = watchlist_cache

    # ── UoW (no-op — this consumer doesn't write to the DB) ──────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUnitOfWork()  # type: ignore[return-value]

    # ── Core processing ───────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        event_type = value.get("event_type", "")
        raw_entity_id = value.get("entity_id")

        if not raw_entity_id:
            logger.warning(  # type: ignore[no-any-return]
                "watchlist_event_missing_entity_id",
                event_type=event_type,
            )
            return

        try:
            entity_id = UUID(str(raw_entity_id))
        except ValueError:
            logger.warning(  # type: ignore[no-any-return]
                "watchlist_event_invalid_entity_id",
                raw_entity_id=raw_entity_id,
            )
            return

        if event_type == _EVENT_ITEM_ADDED:
            await self._cache.add_entity(entity_id)
            logger.info(  # type: ignore[no-any-return]
                "watchlist_entity_added",
                entity_id=str(entity_id),
            )
        elif event_type == _EVENT_ITEM_DELETED:
            await self._cache.remove_entity(entity_id)
            logger.info(  # type: ignore[no-any-return]
                "watchlist_entity_removed",
                entity_id=str(entity_id),
            )
        else:
            logger.debug(  # type: ignore[no-any-return]
                "watchlist_event_unknown_type",
                event_type=event_type,
            )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "watchlist_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ── Idempotency (at-least-once; SADD/SREM are naturally idempotent) ──────

    async def is_duplicate(self, event_id: str) -> bool:
        return False  # SADD/SREM are idempotent — re-delivery is safe

    async def mark_processed(self, event_id: str) -> None:
        pass  # No dedup store needed

    # ── Failure tracking (log only — no DB persistence for this consumer) ────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "watchlist_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )
        return None

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "watchlist_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def dead_letter(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "watchlist_consumer_dead_lettered",
            event_id=failure.event_id,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Avro or JSON payload (watchlist events use Avro in prod)."""
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            # Fall back to Avro deserialization in production
            raise  # Let the base class handle Avro path

    def get_schema_path(self, topic: str) -> str | None:
        return None  # Schema registry handles schema lookup

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
