"""Intelligence consumer — routes signal/graph/contradiction events to fan-out.

Consumer group: ``alert-service-group``
Topics:
  - ``nlp.signal.detected.v1``        → AlertType.SIGNAL
  - ``graph.state.changed.v1``        → AlertType.GRAPH_CHANGE
  - ``intelligence.contradiction.v1`` → AlertType.CONTRADICTION
  - ``market.prediction.signal.v1``   → AlertType.PREDICTION (PLAN-0056 D3)

At-least-once delivery with manual offset commit (``enable_auto_commit=False``).
Backfill suppression is delegated to :class:`AlertFanoutUseCase`.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any

from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase
    from alert.application.use_cases.kg_connection_handler import KgConnectionEventHandler

logger = get_logger(__name__)  # type: ignore[no-any-return]

_KNOWN_TOPICS: frozenset[str] = frozenset(
    {
        "nlp.signal.detected.v1",
        "graph.state.changed.v1",
        "intelligence.contradiction.v1",
        # PLAN-0056 Wave D3: prediction-market signals from S7 (Wave D2).
        "market.prediction.signal.v1",
    },
)


_TOPIC_SCHEMA_PATHS: dict[str, str] = {
    "nlp.signal.detected.v1": get_schema_path("nlp.signal.detected.v1.avsc"),
    "graph.state.changed.v1": get_schema_path("graph.state.changed.v1.avsc"),
    "intelligence.contradiction.v1": get_schema_path("intelligence.contradiction.v1.avsc"),
    # PLAN-0056 Wave D3: Avro-first decode of the prediction signal.
    "market.prediction.signal.v1": get_schema_path("market.prediction.signal.v1.avsc"),
}

# PLAN-0062 F-018: defence-in-depth bound on the unbounded ``json.loads`` read.
# 16 MiB cap on the JSON-fallback path to prevent OOM from a poison legacy
# message.
_MAX_JSON_FALLBACK_BYTES = 16 * 1024 * 1024


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

    # How often (seconds) to run the expensive per-partition watermark sweep
    # for the lag gauge. The base class does it after every message; we cap it
    # so a 48-partition assignment does not pay ~48 blocking broker calls per
    # message. Class attr (not config) to avoid per-service drift.
    _LAG_RECORD_INTERVAL_SECONDS: float = 10.0

    def __init__(
        self,
        config: ConsumerConfig,
        fanout_use_case: AlertFanoutUseCase,
        *,
        dedup_client: Any | None = None,
        metrics_namespace: str | None = "alert",
        kg_handler: KgConnectionEventHandler | None = None,
    ) -> None:
        # Force the metrics namespace to the service name (default "alert") so
        # the emitted Prometheus series match alert-service.json which queries
        # `alert_kafka_messages_consumed_total`. Without this override the
        # BaseKafkaConsumer falls back to `config.group_id` (e.g.
        # "alert-intelligence-consumer"), silently breaking the dashboard panel.
        super().__init__(config, metrics_namespace=metrics_namespace)
        self._fanout = fanout_use_case
        self._dedup_client = dedup_client
        # PLAN-0113 W3: optional ADDITIVE branch that evaluates standing
        # KG_CONNECTION rules on each graph-state event. None (the default, and
        # what every existing test uses) makes the branch a pure no-op so the
        # existing GRAPH_CHANGE fan-out path is byte-for-byte unchanged.
        self._kg_handler = kg_handler
        self._dedup_prefix = f"s10:dedup:{config.group_id}"
        # ── Liveness / progress instrumentation (issue 4, Fix A gaps A+D) ──────
        # The 43h silent wedge (audit 2026-06-16) was invisible because nothing
        # tracked *forward progress*: the Docker healthcheck only proved PID 1
        # existed, and the lag-stall warning only *logged*. We record a
        # monotonic timestamp every time a message is actually processed so two
        # things can ACT on a stall:
        #   1. the wall-clock watchdog in intelligence_consumer_main.py
        #      (exits the process for an orchestrator restart), and
        #   2. the Docker healthcheck, which reads the heartbeat file we touch
        #      below (a wedged consumer then reports `unhealthy`).
        # `time.monotonic()` is used for the watchdog comparison because it is
        # immune to the wall-clock skew the audit observed on this host
        # (Docker StartedAt was 43h wrong). It is seeded to "now" so a
        # freshly-started consumer is never considered stalled before it has
        # had a chance to poll.
        self._last_progress_monotonic: float = time.monotonic()
        # ── F-006: idle-vs-wedged liveness signal ─────────────────────────────
        # `_last_progress_monotonic` above advances ONLY when a message is
        # processed, so on an idle low-traffic topic it never advances even
        # though the poll loop is perfectly alive — the watchdog then mistook
        # "no traffic" for "wedged" and crash-looped the container (RestartCount
        # =10, every ~5 min). We add a SEPARATE timestamp that advances on every
        # healthy poll-loop *cycle* (idle OR message): the base class calls
        # :meth:`_record_progress` after every successful ``poll()`` return
        # (base.py ~L1755, BP-700), so overriding it lets us tick a monotonic
        # "the loop is cycling" marker. The watchdog reads THIS marker — a loop
        # that keeps returning from poll (even empty) is alive; only a loop that
        # stops returning from poll (genuinely wedged) lets it go stale.
        # Seeded to "now" so a freshly-started consumer is never flagged before
        # its first poll. ``time.monotonic()`` keeps it immune to the wall-clock
        # skew the 2026-06-16 audit observed on this host.
        self._last_poll_monotonic: float = time.monotonic()
        # Throttle timestamp for the per-message lag-recording override below.
        # Seeded into the past so the first message records lag immediately.
        self._last_lag_record_monotonic: float = 0.0
        # Heartbeat file path the Docker healthcheck stats for freshness. Lives
        # under /tmp (always writable, tmpfs) so the check needs no network or
        # broker round-trip. Overridable via env for tests.
        self._heartbeat_path = os.environ.get(
            "ALERT_CONSUMER_HEARTBEAT_PATH",
            "/tmp/alert_intelligence_consumer.heartbeat",  # noqa: S108 — tmpfs liveness marker, not sensitive
        )
        # Touch once at construction so the healthcheck has a fresh marker
        # during the `start_period` before the first message arrives.
        self._touch_heartbeat()

    @property
    def last_progress_monotonic(self) -> float:
        """Monotonic timestamp of the last successfully processed message.

        Tracks message-processing throughput (used by the lag/metrics path).
        NOTE: this advances only when a message is actually handled, so it must
        NOT be used to decide "wedged" on a low-traffic topic — see
        :attr:`last_poll_monotonic` and F-006.
        """
        return self._last_progress_monotonic

    @property
    def last_poll_monotonic(self) -> float:
        """Monotonic timestamp of the last healthy poll-loop *cycle*.

        Advances on every successful ``poll()`` return — idle (empty poll) OR
        message — so it reflects "the consume loop is alive and cycling", which
        is the correct signal for the wedge watchdog. An idle topic keeps this
        fresh (the loop keeps returning empty polls); a genuinely wedged loop
        (poll stops returning / lost assignment) lets it go stale. Read by the
        wall-clock watchdog in the entry point. See F-006.
        """
        return self._last_poll_monotonic

    def _record_progress(self) -> None:
        """Tick the poll-cycle liveness marker on every healthy poll return.

        Overrides :meth:`BaseKafkaConsumer._record_progress`, which the base
        loop calls after each successful ``poll()`` (idle OR message; BP-700).
        We advance our monotonic poll marker here so the watchdog treats an
        idle-but-cycling loop as alive, then delegate to the base to keep its
        own ``_last_progress_ts`` / Prometheus heartbeat behaviour intact.
        """
        self._last_poll_monotonic = time.monotonic()
        super()._record_progress()

    def _touch_heartbeat(self) -> None:
        """Record forward progress for both the watchdog and the healthcheck.

        Best-effort: a failure to write the heartbeat file must never break
        message processing. The in-memory monotonic timestamp is the
        authoritative signal for the in-process watchdog; the file exists only
        so the *out-of-process* Docker healthcheck can observe liveness without
        importing application state.
        """
        self._last_progress_monotonic = time.monotonic()
        try:
            # `os.utime(..., None)` sets mtime to the current wall-clock time;
            # the healthcheck compares that mtime against `now` for staleness.
            with open(self._heartbeat_path, "a"):
                os.utime(self._heartbeat_path, None)
        except OSError:
            logger.debug(  # type: ignore[no-any-return]
                "intelligence_consumer.heartbeat_write_failed",
                path=self._heartbeat_path,
                exc_info=True,
            )

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

        # ── PLAN-0113 W3: KG_CONNECTION rule branch (ADDITIVE) ────────────────
        # Runs ONLY for graph-state events, ONLY when a kg_handler is wired, and
        # is fully isolated in try/except so it can NEVER perturb the existing
        # GRAPH_CHANGE fan-out above (the spec's hard constraint). The handler is
        # itself fail-soft per rule; this guard is the outer belt-and-braces.
        if self._kg_handler is not None and topic == "graph.state.changed.v1":
            try:
                await self._kg_handler.handle(value)
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "intelligence_consumer.kg_branch_error",
                    event_id=value.get("event_id"),
                    exc_info=True,
                )

        # Fix A (gaps A+D): record forward progress so the watchdog +
        # healthcheck can tell a draining consumer from a wedged one. Done
        # AFTER fan-out returns so a message that hangs in fan-out does NOT
        # count as progress — that is exactly the stall we want to detect.
        self._touch_heartbeat()

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
        # PLAN-0056 Wave D3: event_type is "market.prediction.signal".
        if event_type.startswith("market.prediction.signal"):
            return "market.prediction.signal.v1"

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

    # ── Lag-recording throttle (issue 4 / Fix B throughput) ───────────────────

    def _record_consumer_lag(self) -> None:
        """Throttled override of the base per-message lag recorder.

        ROOT CAUSE of the ~3 msg/min drain (audit 2026-06-16): the base class
        calls ``_record_consumer_lag`` after EVERY committed message, and that
        routine loops over the *entire* assignment calling the blocking
        librdkafka ``get_watermark_offsets(timeout=1.0)`` once per partition.
        This consumer is assigned ~48 partitions (24 signal + 12 graph + 12
        contradiction), so each message paid up to ~48 broker round-trips of
        watermark polling — tens of seconds of pure overhead per message that
        dwarfed the actual fan-out work.

        We cannot change the shared ``BaseKafkaConsumer`` from here, so we
        override the hook to RATE-LIMIT it: recompute lag at most once every
        ``_LAG_RECORD_INTERVAL_SECONDS`` instead of after every message. The
        gauge is for dashboards/alerting (and the base class's own lag-stall
        probe samples lag independently on its 60s cadence), so a slightly
        coarser per-message gauge is an acceptable trade for an order-of-
        magnitude throughput gain. Correctness of consumption is unaffected.
        """
        now = time.monotonic()
        if now - self._last_lag_record_monotonic < self._LAG_RECORD_INTERVAL_SECONDS:
            return  # skip — too soon since the last (expensive) watermark sweep
        self._last_lag_record_monotonic = now
        super()._record_consumer_lag()

    # ── Serialization ─────────────────────────────────────────────────────────

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode events from any of the three intelligence topics.

        PLAN-0062 Wave C: AVRO_FIRST decode driven by the Confluent magic
        byte (0x00).  When ``schema_path`` is provided (set by the base
        consumer's ``_handle_message`` via ``get_schema_path``) the Avro path
        decodes against that schema.  Falls back to JSON for legacy
        producers — this is logged so we can quantify residual JSON traffic.

        QA-iter1 (PLAN-0062): if the Confluent magic byte is present but no
        schema path is known (unknown topic), refuse to call ``json.loads``
        on Avro bytes — that would raise ``JSONDecodeError`` and dead-letter
        the message via the noisier path.  Raise ``MalformedDataError``
        directly so the dead-letter is clean and the warning is accurate.
        """
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        if raw and raw[:1] == b"\x00":
            if schema_path:
                return deserialize_confluent_avro(schema_path, raw)  # type: ignore[no-any-return]
            logger.warning(  # type: ignore[no-any-return]
                "intelligence_consumer.avro_payload_without_schema",
                message="Confluent magic byte present but no schema_path resolved; dead-lettering as malformed",
            )
            raise MalformedDataError(
                "Avro magic byte present but no schema path registered for this topic",
            )
        logger.warning(  # type: ignore[no-any-return]
            "intelligence_consumer.legacy_json_payload",
            message="message lacks Confluent magic byte; using JSON fallback",
        )
        # PLAN-0062 F-018: cap JSON-fallback to 16 MiB before ``json.loads``.
        if len(raw) > _MAX_JSON_FALLBACK_BYTES:
            raise MalformedDataError(
                f"JSON fallback payload exceeds cap ({len(raw)} > {_MAX_JSON_FALLBACK_BYTES})",
            )
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        return _TOPIC_SCHEMA_PATHS.get(topic)

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))
