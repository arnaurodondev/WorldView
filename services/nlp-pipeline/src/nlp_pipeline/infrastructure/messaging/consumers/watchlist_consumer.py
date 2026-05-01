"""Watchlist event consumer — maintains Valkey SET for routing signal.

Consumes ``portfolio.watchlist.updated.v1`` (consumer group: nlp-watchlist-group).
On ``watchlist.item_added``: SADD entity_id.
On ``watchlist.item_deleted``: SREM entity_id.

PRD §6.7 Block 5 watchlist signal sourcing.
"""

from __future__ import annotations

import json
from pathlib import Path
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


# F-102 fix (2026-04-30 / BP-122 lineage): producer (S1 portfolio) emits
# Confluent-Avro framed bytes (5-byte header: 0x00 magic + 4-byte schema id).
# A bare ``json.loads(raw)`` triggers Python's RFC-4627 encoding sniff and
# explodes on the leading nulls. Locate the schema file the same way the
# article_consumer does so we can decode the wire format properly.
def _find_schema_dir() -> Path:
    relative = Path("infra") / "kafka" / "schemas"
    for base in Path(__file__).resolve().parents:
        candidate = base / relative
        if candidate.is_dir():
            return candidate
    return Path(__file__).parents[7] / "infra" / "kafka" / "schemas"


_SCHEMA_DIR = _find_schema_dir()
_WATCHLIST_SCHEMA_PATH = str(_SCHEMA_DIR / "portfolio.watchlist.updated.v1.avsc")


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

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "watchlist_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "watchlist_consumer_dead_lettered",
            event_id=failure.event_id,
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Confluent-Avro or JSON payload.

        F-102 fix (BP-122 + 2026-04-30 follow-up):
        - 0x00 magic byte → Confluent wire format (5-byte header + Avro body).
        - Producer uses **per-event-type schemas** (``WatchlistItemAdded`` vs
          ``WatchlistItemDeleted``); a single hardcoded ``.avsc`` only works
          for one of them. We resolve the schema dynamically via Schema
          Registry by the schema_id encoded in the header, then cache it.
        - Without this branch ``json.loads(raw)`` saw 4 leading null bytes,
          auto-detected UTF-32-BE, and crashed with `code point not in range`.
        """
        if raw and raw[0:1] == b"\x00":
            return self._deserialize_confluent(raw)
        return json.loads(raw)  # type: ignore[no-any-return]

    def _deserialize_confluent(self, raw: bytes) -> dict[str, Any]:
        """Decode Confluent-framed Avro bytes by Schema Registry id lookup."""
        import struct

        from messaging.kafka.serialization_utils import deserialize_avro  # type: ignore[import-untyped]

        if len(raw) < 5:
            msg = f"Confluent payload too short: {len(raw)} bytes"
            raise ValueError(msg)
        schema_id = struct.unpack(">I", raw[1:5])[0]
        schema = self._schema_for_id(schema_id)
        return deserialize_avro(schema, raw[5:])  # type: ignore[no-any-return]

    def _schema_for_id(self, schema_id: int) -> dict[str, Any]:
        """Resolve and cache an Avro schema by Schema Registry id.

        ``deserialize_value`` is invoked synchronously by ``BaseKafkaConsumer``
        (the consumer base interface predates async deserialisers). On cache
        miss this issues a sync ``httpx.get`` to Schema Registry. The first
        two messages of each event-type fill the cache (one schema_id per
        per-event-type subject); every subsequent message is in-memory.
        Cumulative blocking time is bounded at ~500 ms over the whole consumer
        lifetime — acceptable for a low-volume metadata topic.

        For higher-volume topics the right answer is to lift the lookup into
        an async startup hook (``BaseKafkaConsumer.start``) so the event loop
        never sees a sync HTTP call.
        """
        cached = self.__dict__.setdefault("_schema_cache", {})
        if schema_id in cached:
            return cached[schema_id]  # type: ignore[no-any-return]
        import os

        import httpx

        sr_url = os.environ.get("NLP_PIPELINE_SCHEMA_REGISTRY_URL", "http://schema-registry:8081")
        # blocking-io-justification (HR-019): the synchronous httpx call here is a
        # bounded one-time cost per schema_id (≤3 per topic) and never blocks
        # the event loop after the first two messages.
        resp = httpx.get(f"{sr_url}/schemas/ids/{schema_id}", timeout=5.0)  # - timeout set
        resp.raise_for_status()
        schema = json.loads(resp.json()["schema"])
        cached[schema_id] = schema
        return schema  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        # Schema is resolved by schema_id from the wire format header in
        # ``_deserialize_confluent`` — no static path lookup needed.
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
