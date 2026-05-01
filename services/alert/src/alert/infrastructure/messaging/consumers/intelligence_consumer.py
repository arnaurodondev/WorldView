"""Intelligence consumer — routes signal/graph/contradiction events to fan-out.

Consumer group: ``alert-service-group``
Topics:
  - ``nlp.signal.detected.v1``       → AlertType.SIGNAL
  - ``graph.state.changed.v1``       → AlertType.GRAPH_CHANGE
  - ``intelligence.contradiction.v1`` → AlertType.CONTRADICTION

At-least-once delivery with manual offset commit (``enable_auto_commit=False``).
Backfill suppression is delegated to :class:`AlertFanoutUseCase`.
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
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase

logger = get_logger(__name__)  # type: ignore[no-any-return]

_KNOWN_TOPICS: frozenset[str] = frozenset(
    {
        "nlp.signal.detected.v1",
        "graph.state.changed.v1",
        "intelligence.contradiction.v1",
    },
)


# ── Minimal no-op UoW ─────────────────────────────────────────────────────────


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


# ── Consumer ──────────────────────────────────────────────────────────────────


class IntelligenceConsumer(BaseKafkaConsumer[None]):
    """Consumes intelligence topics and routes each event to fan-out.

    Args:
    ----
        config: Consumer configuration.  ``topics`` should contain all
            three intelligence topic names; ``group_id`` should be
            ``alert-service-group``.
        fanout_use_case: :class:`AlertFanoutUseCase` instance to call for
            each received event.
        dedup_client: Optional Valkey client for event deduplication.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        fanout_use_case: AlertFanoutUseCase,
        *,
        dedup_client: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._fanout = fanout_use_case
        self._dedup_client = dedup_client
        self._dedup_prefix = f"s10:dedup:{config.group_id}"

    # ── Core processing ───────────────────────────────────────────────────────

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Route event to :meth:`AlertFanoutUseCase.execute`."""
        # The topic is not passed directly to process_message; retrieve it
        # from the value envelope or headers, or use the last known topic
        # extracted by BaseKafkaConsumer._handle_message (stored in value).
        # BaseKafkaConsumer passes the raw message to _handle_message which
        # calls deserialize_value, then calls process_message with (key, value,
        # headers).  The topic is available via the raw msg object but not
        # forwarded.  We extract it from the Kafka message headers if present,
        # otherwise fall back to checking the event_type in the payload to
        # determine the topic.
        topic = self._resolve_topic(value, headers)
        correlation_id: str | None = value.get("correlation_id")  # type: ignore[assignment]

        # Extract market_impact_score; default 0.0 for events that don't carry it.
        # Guard float() against None or non-numeric values (e.g. schema mismatch).
        raw_score = value.get("market_impact_score", 0.0)
        try:
            market_impact_score: float = max(0.0, min(1.0, float(raw_score or 0.0)))
        except (ValueError, TypeError):
            market_impact_score = 0.0

        result = await self._fanout.execute(
            event=value,
            topic=topic,
            correlation_id=correlation_id,
            market_impact_score=market_impact_score,
        )

        logger.debug(  # type: ignore[no-any-return]
            "intelligence_consumer.processed",
            topic=topic,
            event_id=value.get("event_id"),
            suppressed=result.suppressed,
            suppression_reason=result.suppression_reason,
            watchers=result.watchers_count,
        )

    @staticmethod
    def _resolve_topic(value: dict[str, Any], headers: dict[str, str]) -> str:
        """Infer the source topic from event_type or header."""
        # Try X-Source-Topic header first (set by producer if available)
        topic_header = headers.get("X-Source-Topic", "")
        if topic_header:
            if topic_header not in _KNOWN_TOPICS:
                logger.warning(  # type: ignore[no-any-return]
                    "intelligence_consumer.unknown_topic_from_header",
                    topic=topic_header,
                )
                # Fall through to event_type resolution; don't store arbitrary header values.
            else:
                return topic_header

        # Fall back to event_type field in the payload
        event_type: str = str(value.get("event_type", ""))
        if event_type.startswith("nlp.signal"):
            return "nlp.signal.detected.v1"
        if event_type.startswith("graph.state"):
            return "graph.state.changed.v1"
        if event_type.startswith("intelligence.contradiction"):
            return "intelligence.contradiction.v1"

        # Unresolvable — log warning; fanout degrades gracefully for unknown topics
        logger.warning(  # type: ignore[no-any-return]
            "intelligence_consumer.unresolvable_topic",
            event_type=event_type,
            event_id=value.get("event_id"),
        )
        return event_type

    # ── Retry / failure (log-only) ────────────────────────────────────────────

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "intelligence_consumer.retry_not_supported",
            event_id=failure.event_id,
        )

    # ── Idempotency (Valkey-backed with no-op fallback) ───────────────────────

    async def is_duplicate(self, event_id: str) -> bool:
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            return bool(await self._dedup_client.exists(key))
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "intelligence_consumer.valkey_check_failed",
                event_id=event_id,
                exc_info=True,
            )
            return False  # prefer at-least-once over skipping

    async def mark_processed(self, event_id: str) -> None:
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            await self._dedup_client.set(key, "1", ex=86400)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "intelligence_consumer.valkey_mark_failed",
                event_id=event_id,
                exc_info=True,
            )

    # ── Failure tracking (log-only) ───────────────────────────────────────────

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "intelligence_consumer.failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
            attempt=failure.attempt,
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "intelligence_consumer.failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "intelligence_consumer.dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    # ── UoW (no-op — fanout manages its own session) ──────────────────────────

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
