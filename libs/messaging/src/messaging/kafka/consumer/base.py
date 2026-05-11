"""Abstract Kafka consumer base class.

:class:`BaseKafkaConsumer` provides:
- Avro deserialization via fastavro (schemaless, no Schema Registry required).
- Idempotency via :meth:`is_duplicate` (dedup table owned by the subclass).
- Retryable vs Fatal error classification via the error hierarchy in
  :mod:`messaging.kafka.consumer.errors`.
- Exponential back-off with full jitter.
- Structured metrics via :class:`~observability.metrics.ServiceMetrics`.
- Graceful shutdown via ``asyncio`` event.

Subclasses must implement all ``@abstractmethod`` methods.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import sys
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from messaging.kafka.consumer.backpressure import BackpressurePolicy, LagCalculator
from messaging.kafka.consumer.errors import ConsumerError, FatalError, RetryableError
from observability import ServiceMetrics, get_logger  # type: ignore[import-untyped]
from observability import create_metrics as _create_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from confluent_kafka import TopicPartition

logger = get_logger(__name__)

# Generic type for the failure record stored by the consuming service
TFailure = TypeVar("TFailure")


@dataclasses.dataclass
class ConsumerConfig:
    """Typed configuration for :class:`BaseKafkaConsumer`.

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        group_id: Consumer group identifier.
        topics: List of Kafka topic names to subscribe to.
        auto_offset_reset: Offset reset policy (``"earliest"`` or ``"latest"``).
        enable_auto_commit: Whether to enable automatic offset commits.
        session_timeout_ms: Session timeout in milliseconds.
        heartbeat_interval_ms: Heartbeat interval in milliseconds.
        max_poll_interval_ms: Max time between poll calls.
        max_poll_records: Maximum records returned per poll.
        poll_timeout_seconds: Timeout for each ``poll()`` call.
        max_retries: Maximum retry attempts before dead-lettering.
        initial_backoff_seconds: Initial back-off interval.
        max_backoff_seconds: Cap on exponential back-off.
        backoff_multiplier: Exponential multiplier per retry attempt.
    """

    bootstrap_servers: str = "localhost:9092"
    group_id: str = "default-group"
    topics: list[str] = dataclasses.field(default_factory=list)
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    # PLAN-0052 platform-QA round 8 (2026-05-01): the previous defaults had
    # session_timeout_ms (30s) < message_processing_timeout_s (120s), which is
    # the inverse of what's correct. Heartbeats only fire from inside
    # ``Consumer.poll()``; once ``_handle_message`` runs we cannot heartbeat,
    # so any handler exceeding session_timeout_ms triggers SESSTMOUT and a
    # rebalance. The watchdog (message_processing_timeout_s) MUST be
    # strictly less than session_timeout_ms or Kafka wins the race and kicks
    # the consumer out of the group before the watchdog can dead-letter the
    # poison message. This bit two KG dataset consumers (fundamentals,
    # insider-transactions) which call DeepInfra embed inside the message
    # handler — observable as a continuous "revoking assignment and
    # rejoining" log loop. Reorder: session_timeout 60s, max_poll 600s,
    # watchdog 45s. Heartbeat scaled at ~1/3 of session_timeout per
    # rdkafka guidance.
    session_timeout_ms: int = 60_000
    heartbeat_interval_ms: int = 20_000
    max_poll_interval_ms: int = 600_000
    max_poll_records: int = 500
    poll_timeout_seconds: float = 1.0
    max_retries: int = 5
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    # PLAN-0052 QA-R6 (BP-302): watchdog timeout per message.  Set to 0 to disable.
    # Must be strictly less than session_timeout_ms so the watchdog dead-letters
    # the message before Kafka declares the consumer dead.
    message_processing_timeout_s: int = 45
    # Maximum dead-letters allowed before the consumer crashes to force a restart.
    # Prevents a runaway poison-message storm from silently filling the DLQ.
    # PLAN-0088 Wave I (2026-05-10): bumped from 100 → 5000 after a schema
    # evolution (D-INIT-6 added source_name to nlp.article.enriched.v1) caused
    # the kg-service-group-enriched consumer to fail-stop on ~770 pre-change
    # messages on the topic, leaving the entire KG pipeline dead for 5h. The
    # cap is still load-bearing as a poison-storm guard, but 100 is too tight
    # for any non-trivial schema migration window.
    dead_letter_cap: int = 5000
    # PLAN-0087 D-P3-006 / D-P3-009 (2026-05-09): partial-assignment wedge fix.
    # Default Kafka assignor "range" performs stop-the-world rebalances —
    # every member revokes ALL partitions, then re-joins to receive a new set.
    # When a single slow consumer (e.g. one doing per-message DeepInfra calls
    # that span 30-60s) hits the rebalance window, it can fail to re-claim
    # all of its partitions in time, leaving some with CURRENT-OFFSET=`-`
    # for hours.  "cooperative-sticky" performs incremental rebalances —
    # only partitions that need to move are revoked, dramatically shrinking
    # the rebalance attack surface and preventing partial-assignment wedges.
    # Reference: KIP-429 (incremental cooperative rebalancing) and
    # librdkafka >=1.6 cooperative-sticky support.
    partition_assignment_strategy: str = "cooperative-sticky"

    def to_dict(self) -> dict[str, Any]:
        """Return Confluent-compatible consumer config dict.

        Note (PLAN-0087 D-P3-006 + 2026-05-09 follow-up): the cooperative-sticky
        assignor IS passed through so the rebalance behaviour fix lands.
        ``max.poll.records`` is NOT a librdkafka config key (that property is
        Java/Spring Kafka only); passing it crashes ``Consumer(...)`` with
        ``KafkaError{code=_INVALID_ARG, str="No such configuration property"}``.
        Keep it on the dataclass for documentation/typing but DROP it from the
        rdkafka config payload.  Equivalent throughput tuning on librdkafka
        is via ``fetch.message.max.bytes`` / ``queued.max.messages.kbytes``,
        not record count.
        """
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
            "session.timeout.ms": self.session_timeout_ms,
            "heartbeat.interval.ms": self.heartbeat_interval_ms,
            "max.poll.interval.ms": self.max_poll_interval_ms,
            "partition.assignment.strategy": self.partition_assignment_strategy,
        }


@dataclasses.dataclass
class FailureInfo(Generic[TFailure]):
    """Record of a processing failure for retry tracking.

    Args:
        event_id: ID of the failed event.
        topic: Source Kafka topic.
        partition: Source partition.
        offset: Source offset.
        attempt: Current attempt count (1-based).
        last_error: The most recent exception.
        record: Optional failure record for persistence (subclass-defined).
    """

    event_id: str
    topic: str
    partition: int
    offset: int
    attempt: int
    last_error: BaseException
    record: TFailure | None = None


class UnitOfWorkProtocol(ABC):
    """Minimal async unit-of-work interface used by the consumer."""

    @abstractmethod
    async def __aenter__(self) -> UnitOfWorkProtocol: ...

    @abstractmethod
    async def __aexit__(self, *args: Any) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...


class BaseKafkaConsumer(ABC, Generic[TFailure]):
    """Generic Kafka consumer with idempotency, retries, and metrics.

    Type parameter *TFailure* is the subclass-defined failure record type
    stored to the dead-letter / retry table.

    Args:
        config: Consumer configuration.
        metrics: Pre-created :class:`~observability.metrics.ServiceMetrics`.
            If *None*, a default registry is created for the consumer group.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        metrics: ServiceMetrics | None = None,
        backpressure_policy: BackpressurePolicy | None = None,
    ) -> None:
        self._config = config
        self._metrics = metrics or _create_metrics(config.group_id)
        self._consumer: Any = None  # confluent_kafka.Consumer, assigned in _init_kafka
        self._stop_event = asyncio.Event()
        # Running count of dead-letters sent; crashes the consumer when it
        # exceeds dead_letter_cap to trigger a container restart.
        self._dead_letter_count: int = 0
        # DEF-032 backpressure (opt-in).  When None or policy.enabled=False,
        # the integration short-circuits in _maybe_apply_backpressure with
        # zero per-poll overhead so existing consumers see no behaviour change.
        self._backpressure_policy: BackpressurePolicy | None = backpressure_policy
        self._paused_partitions: set[TopicPartition] = set()
        # Monotonic timestamp of the last backpressure evaluation; used to
        # rate-limit checks to ``policy.check_interval_seconds``.
        self._last_backpressure_check: float = 0.0
        # Lazily created only when backpressure is enabled (avoids constructing
        # the calculator when the feature is off — keeps tests + production
        # behaviour identical for non-opted-in consumers).
        self._lag_calculator: LagCalculator | None = (
            LagCalculator() if backpressure_policy is not None and backpressure_policy.enabled else None
        )

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Process a single deserialized Kafka message.

        Raise :class:`~messaging.kafka.consumer.errors.RetryableError` for
        transient failures and :class:`~messaging.kafka.consumer.errors.FatalError`
        for permanent failures.

        Args:
            key: Message key (decoded string or ``None``).
            value: Avro-deserialized message value dict.
            headers: Message headers as a string-to-string dict.
        """

    @abstractmethod
    async def is_duplicate(self, event_id: str) -> bool:
        """Return ``True`` if *event_id* has already been processed.

        Args:
            event_id: The ``event_id`` envelope field from the Kafka message.
        """

    @abstractmethod
    async def mark_processed(self, event_id: str) -> None:
        """Record *event_id* as successfully processed (dedup table insert).

        Args:
            event_id: The ``event_id`` envelope field.
        """

    @abstractmethod
    async def store_failure(self, failure: FailureInfo[TFailure]) -> TFailure:
        """Persist a failure record for retry tracking.

        Args:
            failure: Populated :class:`FailureInfo`.

        Returns:
            The persisted failure record.
        """

    @abstractmethod
    async def update_failure(self, failure: FailureInfo[TFailure]) -> None:
        """Update an existing failure record after a retry attempt.

        Args:
            failure: :class:`FailureInfo` with updated attempt count and error.
        """

    @abstractmethod
    async def _dead_letter_impl(self, failure: FailureInfo[TFailure]) -> None:
        """Move a failure record to the dead-letter store (subclass hook).

        Called by :meth:`dead_letter` after the cap check passes.
        Subclasses persist the record to their dead-letter table/topic here.

        Args:
            failure: :class:`FailureInfo` that exceeded max retries.
        """

    async def dead_letter(self, failure: FailureInfo[TFailure]) -> None:
        """Move a failure record to the dead-letter store with cap enforcement.

        Increments the internal dead-letter counter and delegates to
        :meth:`_dead_letter_impl`.  If the counter exceeds
        ``config.dead_letter_cap``, a :exc:`RuntimeError` is raised to crash
        the consumer and trigger a container restart — preventing a runaway
        poison-message storm from silently filling the DLQ.

        Args:
            failure: :class:`FailureInfo` that exceeded max retries.

        Raises:
            RuntimeError: When the dead-letter count exceeds the configured cap.
        """
        self._dead_letter_count += 1
        if self._dead_letter_count > self._config.dead_letter_cap:
            logger.critical(
                "dead_letter_cap_exceeded",
                cap=self._config.dead_letter_cap,
                count=self._dead_letter_count,
            )
            raise RuntimeError(f"Dead-letter cap {self._config.dead_letter_cap} exceeded — forcing restart")
        await self._dead_letter_impl(failure)

    @abstractmethod
    async def get_pending_retries(self) -> list[FailureInfo[TFailure]]:
        """Return all pending failure records eligible for retry.

        Returns:
            Ordered list of :class:`FailureInfo` objects.
        """

    @abstractmethod
    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        """Return a fresh unit-of-work context manager for this message.

        Returns:
            An instance implementing :class:`UnitOfWorkProtocol`.
        """

    @abstractmethod
    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Deserialize Avro-encoded *raw* bytes to a dict.

        Default implementations can call
        :func:`~messaging.kafka.serialization_utils.deserialize_avro`.

        Args:
            raw: Raw Avro bytes from the Kafka message.
            schema_path: Optional path to the ``.avsc`` schema file.

        Returns:
            Deserialized record dict.
        """

    @abstractmethod
    def get_schema_path(self, topic: str) -> str | None:
        """Return the filesystem path to the Avro schema for *topic*.

        Args:
            topic: Kafka topic name.

        Returns:
            Absolute path string, or ``None`` to skip schema-based deserialization.
        """

    @abstractmethod
    def extract_event_id(self, value: dict[str, Any]) -> str:
        """Extract the idempotency event ID from the deserialized *value*.

        Typically returns ``value["event_id"]``.

        Args:
            value: Deserialized record dict.

        Returns:
            Event ID string.
        """

    # ── Concrete implementation ───────────────────────────────────────────────

    def _on_partitions_revoked(self, _consumer: Any, _partitions: list[Any]) -> None:
        """Rebalance callback fired before partitions are revoked.

        We must resume any partitions we paused for backpressure before they
        leave our assignment — otherwise the next consumer to receive them
        could inherit a paused state we no longer track, and the pause set
        would still hold stale references that never resume.

        This callback signature matches Confluent's ``on_revoke`` contract;
        the consumer + partitions args are unused because we resume *all*
        currently-paused partitions regardless of which were revoked
        (over-resume is a no-op for un-paused partitions).
        """
        # Backpressure may not be configured — guard before doing any work.
        if self._backpressure_policy is None or not self._backpressure_policy.enabled:
            return
        self._resume_all_paused_partitions()
        # QA-fix §2.2: reset the throttle timer so the new assignment is
        # evaluated immediately on the next poll, instead of waiting up to a
        # full ``check_interval_seconds`` window during which fresh partitions
        # could grow lag without triggering a pause.
        self._last_backpressure_check = 0.0

    def _init_kafka(self) -> None:
        """Initialise the Confluent Kafka consumer."""
        from confluent_kafka import Consumer

        self._consumer = Consumer(self._config.to_dict())
        # Register the revoke callback only when backpressure is enabled — this
        # keeps the subscribe() call shape identical to the previous behaviour
        # for the default (non-opted-in) code path, so any subclass relying on
        # the old subscribe semantics is unaffected.
        if self._backpressure_policy is not None and self._backpressure_policy.enabled:
            self._consumer.subscribe(
                self._config.topics,
                on_revoke=self._on_partitions_revoked,
            )
        else:
            self._consumer.subscribe(self._config.topics)
        logger.info(
            "kafka_consumer_started",
            group_id=self._config.group_id,
            topics=self._config.topics,
        )

    def _shutdown_kafka(self) -> None:
        """Close the Confluent Kafka consumer gracefully."""
        if self._consumer is not None:
            # Resume any backpressure-paused partitions before close so the
            # rebalance hand-off does not leave them paused for the next
            # member of the group.
            self._resume_all_paused_partitions()
            self._consumer.close()
            logger.info("kafka_consumer_stopped", group_id=self._config.group_id)

    def _compute_backoff(self, attempt: int) -> float:
        """Return back-off duration in seconds for the given *attempt*.

        Uses full-jitter exponential back-off:
        ``sleep = random(0, min(cap, base * multiplier^attempt))``

        Args:
            attempt: 1-based retry attempt number.

        Returns:
            Sleep duration in seconds.
        """
        cap = self._config.max_backoff_seconds
        base = self._config.initial_backoff_seconds
        mult = self._config.backoff_multiplier
        ceiling = min(cap, base * (mult ** (attempt - 1)))
        return random.uniform(0, ceiling)  # noqa: S311

    async def _handle_message(self, msg: Any) -> None:
        """Deserialize, deduplicate, and dispatch a single Kafka message.

        Args:
            msg: Raw Confluent Kafka message object.
        """
        topic: str = msg.topic()
        schema_path = self.get_schema_path(topic)
        raw_value: bytes = msg.value()

        try:
            value = self.deserialize_value(raw_value, schema_path)
        except Exception as exc:
            raise MalformedDataError(f"deserialization failed: {exc}") from exc

        event_id = self.extract_event_id(value)

        if await self.is_duplicate(event_id):
            logger.debug(
                "kafka_message_duplicate",
                event_id=event_id,
                topic=topic,
            )
            return

        key_raw = msg.key()
        key = key_raw.decode() if isinstance(key_raw, bytes) else key_raw
        headers_raw = msg.headers() or []
        headers = {k: v.decode() if isinstance(v, bytes) else v for k, v in headers_raw}

        timeout_s = self._config.message_processing_timeout_s
        async with await self.get_unit_of_work() as uow:
            try:
                if timeout_s > 0:
                    async with asyncio.timeout(timeout_s):
                        await self.process_message(key, value, headers)
                else:
                    await self.process_message(key, value, headers)
                await uow.commit()
                await self.mark_processed(event_id)
            except TimeoutError:
                # BP-302 watchdog: poison message hung processing for timeout_s.
                # Dump a stack trace, dead-letter the message, and continue so
                # the consumer does not stall on re-delivery of the same message.
                import faulthandler

                faulthandler.dump_traceback(file=sys.stderr)
                await uow.rollback()
                _timeout_failure: FailureInfo[TFailure] = FailureInfo(
                    event_id=event_id,
                    topic=topic,
                    partition=msg.partition(),
                    offset=msg.offset(),
                    attempt=self._config.max_retries,
                    last_error=TimeoutError(f"message_processing_timeout after {timeout_s}s"),
                )
                await self.dead_letter(_timeout_failure)
                logger.error(  # type: ignore[no-any-return]
                    "message_processing_timeout_dead_lettered",
                    event_id=event_id,
                    topic=topic,
                    timeout_s=timeout_s,
                )
            except Exception:
                await uow.rollback()
                raise

        self._metrics.kafka_messages_consumed_total.labels(
            topic=topic,
            consumer_group=self._config.group_id,
        ).inc()

    async def _handle_failure(
        self,
        msg: Any,
        exc: BaseException,
    ) -> None:
        """Handle a failed message — retry or dead-letter.

        Args:
            msg: Raw Confluent Kafka message.
            exc: The exception that caused the failure.
        """
        topic: str = msg.topic()
        partition: int = msg.partition()
        offset: int = msg.offset()

        raw_value: bytes = msg.value() or b""
        try:
            value = self.deserialize_value(raw_value, self.get_schema_path(topic))
            event_id = self.extract_event_id(value)
        except Exception:
            event_id = f"{topic}/{partition}/{offset}"

        failure: FailureInfo[TFailure] = FailureInfo(
            event_id=event_id,
            topic=topic,
            partition=partition,
            offset=offset,
            attempt=1,
            last_error=exc,
        )

        if isinstance(exc, FatalError) or failure.attempt >= self._config.max_retries:
            await self.dead_letter(failure)
            logger.error(
                "kafka_message_dead_lettered",
                event_id=event_id,
                error=str(exc),
                topic=topic,
            )
        else:
            failure.record = await self.store_failure(failure)
            logger.warning(
                "kafka_message_failed_retryable",
                event_id=event_id,
                attempt=failure.attempt,
                error=str(exc),
                topic=topic,
            )

    async def _retry_failure(self, failure: FailureInfo[TFailure]) -> None:
        """Attempt to re-process a single *failure*.

        Args:
            failure: The :class:`FailureInfo` record to retry.
        """
        backoff = self._compute_backoff(failure.attempt)
        await asyncio.sleep(backoff)

        try:
            # Re-fetch the original message is not possible without seeking;
            # subclasses must store the raw payload in the failure record.
            # This method exists as the retry dispatch point.
            await self.process_message_from_failure(failure)
            await self.mark_processed(failure.event_id)
        except RetryableError as exc:
            failure.attempt += 1
            failure.last_error = exc
            if failure.attempt >= self._config.max_retries:
                await self.dead_letter(failure)
                logger.error(
                    "kafka_message_dead_lettered_after_retries",
                    event_id=failure.event_id,
                    attempts=failure.attempt,
                )
            else:
                await self.update_failure(failure)
        except FatalError as exc:
            failure.last_error = exc
            await self.dead_letter(failure)
            logger.error(
                "kafka_message_fatal_during_retry",
                event_id=failure.event_id,
                error=str(exc),
            )

    @abstractmethod
    async def process_message_from_failure(self, failure: FailureInfo[TFailure]) -> None:
        """Re-process a message from a stored failure record.

        Called by :meth:`_retry_failure`.  Subclasses must store the
        necessary payload in :attr:`FailureInfo.record` to allow re-processing.

        Args:
            failure: The :class:`FailureInfo` to re-process.
        """

    def _record_consumer_lag(self) -> None:
        """Poll Kafka watermark offsets and update the consumer lag gauge.

        Called after each successfully committed message.  Errors are swallowed
        so that a transient Kafka metadata timeout never breaks the consumer loop.
        Non-critical: a missing data point is far better than a dead consumer.

        PLAN-0087 D-P3-006: this routine is invoked from an asyncio context but
        ``get_watermark_offsets`` is a *blocking* librdkafka call with a 1-second
        timeout per partition.  Across 12 partitions that is up to 12s of
        event-loop blocking after every committed message — long enough to
        delay Confluent's poll loop and contribute to the "wedged consumer"
        symptom (assigned but no progress).  The call sites now hop this
        method onto the default executor via :func:`run_in_executor` so the
        event loop remains responsive while broker watermarks are read.
        """
        if self._metrics is None or self._consumer is None:
            # Metrics or consumer not initialised yet — nothing to record.
            return
        try:
            assignment = self._consumer.assignment()
            for tp in assignment:
                # get_watermark_offsets returns (low, high) — the high watermark
                # is the offset of the next message to be produced, so the lag
                # is high - current_position.
                _low, high = self._consumer.get_watermark_offsets(tp, timeout=1.0)
                position_list = self._consumer.position([tp])
                if position_list:
                    position = position_list[0].offset
                    if position >= 0:  # -1001 == OFFSET_BEGINNING (no committed offset yet)
                        lag = max(0, high - position)
                        self._metrics.kafka_consumer_lag.labels(
                            topic=tp.topic,
                            partition=str(tp.partition),
                            consumer_group=self._config.group_id,
                        ).set(lag)
        except Exception:  # noqa: S110
            # Non-critical — don't break the consumer loop on lag polling failure.
            pass

    def _maybe_apply_backpressure(self) -> None:
        """Pause/resume partitions based on the configured backpressure policy.

        Called once per poll cycle (before ``consumer.poll``).  Short-circuits
        immediately when no policy is set or the policy is disabled, so the
        default code path adds essentially zero overhead for consumers that
        have not opted in.

        When enabled, the function rate-limits itself to one evaluation every
        ``policy.check_interval_seconds`` (monotonic clock) — there is no
        benefit to evaluating lag on every poll, and the broker watermark
        cache may not have refreshed yet.

        Pause logic: any partition whose current lag exceeds
        ``policy.pause_lag_threshold`` and is not already paused gets paused.
        Resume logic: any currently-paused partition whose lag has fallen
        below ``policy.resume_lag_threshold`` (or is no longer assigned) gets
        resumed.  The hysteresis gap between the two thresholds prevents
        flapping when lag oscillates near the boundary.
        """
        policy = self._backpressure_policy
        # Fast path: no policy or disabled → zero work, zero broker calls.
        if policy is None or not policy.enabled:
            return
        # Rate-limit: skip until the configured interval has elapsed since
        # the last check.  Uses monotonic time so wall-clock jumps cannot
        # cause us to miss or double-up evaluations.
        now = time.monotonic()
        if now - self._last_backpressure_check < policy.check_interval_seconds:
            return
        if self._lag_calculator is None or self._consumer is None:
            return

        lag_by_tp = self._lag_calculator.get_lag_for_assignment(self._consumer)

        # ── Pause partitions that crossed the high-water threshold ──────────
        for tp, lag in lag_by_tp.items():
            if lag > policy.pause_lag_threshold and tp not in self._paused_partitions:
                try:
                    self._consumer.pause([tp])
                except Exception as exc:
                    # Pause is best-effort — failing here would just delay
                    # backpressure by one cycle; do not crash the loop.
                    logger.warning(
                        "consumer.backpressure.pause_failed",
                        topic=tp.topic,
                        partition=tp.partition,
                        error=str(exc),
                    )
                    continue
                self._paused_partitions.add(tp)
                logger.info(
                    "consumer.backpressure.paused",
                    topic=tp.topic,
                    partition=tp.partition,
                    lag=lag,
                    threshold=policy.pause_lag_threshold,
                )

        # ── Resume partitions that recovered below the low-water threshold ──
        # Iterate over a copy because we mutate the set during iteration.
        for tp in list(self._paused_partitions):
            current_lag = lag_by_tp.get(tp)
            # Two reasons to resume:
            # 1. Lag dropped below resume threshold.
            # 2. Partition is no longer in the assignment (current_lag is None
            #    because the calculator only returns assigned partitions).
            #    Without this branch, a revoked-then-reassigned partition
            #    would stay in our paused set forever.
            should_resume = current_lag is None or current_lag < policy.resume_lag_threshold
            if should_resume:
                try:
                    self._consumer.resume([tp])
                except Exception as exc:
                    logger.warning(
                        "consumer.backpressure.resume_failed",
                        topic=tp.topic,
                        partition=tp.partition,
                        error=str(exc),
                    )
                    # Remove from paused set even on resume failure — otherwise
                    # we leak the entry; the next pause cycle can re-add it.
                self._paused_partitions.discard(tp)
                logger.info(
                    "consumer.backpressure.resumed",
                    topic=tp.topic,
                    partition=tp.partition,
                    lag=current_lag if current_lag is not None else -1,
                    threshold=policy.resume_lag_threshold,
                )

        self._last_backpressure_check = now

    def _resume_all_paused_partitions(self) -> None:
        """Resume every currently-paused partition and clear the tracking set.

        Called from the rebalance revoke callback and from ``_shutdown_kafka``
        so that paused partitions are not left dangling for the next consumer
        in the group.  Errors are swallowed — we are in a teardown / rebalance
        path and cannot do anything useful with them.
        """
        if not self._paused_partitions:
            return
        partitions = list(self._paused_partitions)
        try:
            if self._consumer is not None:
                self._consumer.resume(partitions)
        except Exception as exc:
            logger.warning(
                "consumer.backpressure.bulk_resume_failed",
                count=len(partitions),
                error=str(exc),
            )
        self._paused_partitions.clear()

    async def _process_retry_batch(self) -> None:
        """Fetch and retry all pending failures once per poll cycle."""
        pending = await self.get_pending_retries()
        for failure in pending:
            await self._retry_failure(failure)

    async def _retry_loop(self) -> None:
        """Background loop that periodically retries pending failures."""
        while not self._stop_event.is_set():
            try:
                await self._process_retry_batch()
            except Exception as exc:
                logger.error("retry_loop_error", error=str(exc))
            await asyncio.sleep(self._config.poll_timeout_seconds)

    async def run(self) -> None:
        """Start consuming messages until :meth:`stop` is called.

        Runs the Kafka poll loop and the retry loop concurrently.  Blocks
        until the stop event is set.
        """
        self._init_kafka()
        retry_task = asyncio.create_task(self._retry_loop())

        # BP-268 fix: asyncio.create_task without a done_callback means a crash
        # in the retry loop is silently swallowed — the task becomes a failed
        # Future that nobody awaits.  The callback forces sys.exit(1) so the
        # container orchestrator (Docker/k3s) restarts the service immediately
        # instead of letting it limp along with a dead retry loop.
        def _on_retry_task_done(task: asyncio.Task[None]) -> None:  # type: ignore[type-arg]
            if task.cancelled():
                # Normal shutdown path — the retry loop is cancelled in `finally`.
                return
            exc = task.exception()
            if exc is not None:
                # Log and force a container restart so the crash is visible.
                logger.critical("retry_task_crashed", exc_info=exc)
                sys.exit(1)

        retry_task.add_done_callback(_on_retry_task_done)

        try:
            loop = asyncio.get_event_loop()
            while not self._stop_event.is_set():
                # DEF-032: opt-in backpressure check before each poll.
                # Short-circuits to a single attribute check when no policy
                # is configured; otherwise rate-limits to once per
                # ``check_interval_seconds`` so the cost is negligible.
                self._maybe_apply_backpressure()
                msg = await loop.run_in_executor(
                    None,
                    self._consumer.poll,
                    self._config.poll_timeout_seconds,
                )
                if msg is None:
                    continue
                if msg.error():
                    from confluent_kafka import KafkaError

                    err = msg.error()
                    if err.code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error("kafka_poll_error", error=str(err))
                    continue

                try:
                    await self._handle_message(msg)
                    # Commit after successful processing (manual offset management)
                    if not self._config.enable_auto_commit:
                        await loop.run_in_executor(None, self._consumer.commit, msg)
                    # Record consumer lag after each successful commit so Prometheus
                    # reflects the latest position.  Failures are swallowed inside
                    # _record_consumer_lag to keep this non-critical.
                    # PLAN-0087 D-P3-006: hop the blocking watermark/position
                    # broker calls onto the executor so they cannot delay the
                    # event loop (up to ~12s blocking with 12 partitions and
                    # the 1s per-call timeout).  Event-loop responsiveness is
                    # critical for Confluent poll(), heartbeat callbacks,
                    # and other pending coroutines.
                    await loop.run_in_executor(None, self._record_consumer_lag)
                except ConsumerError as exc:
                    await self._handle_failure(msg, exc)
                except Exception as exc:
                    logger.exception("kafka_unexpected_error", error=str(exc))
                    await self._handle_failure(msg, exc)
        finally:
            import contextlib

            retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry_task
            self._shutdown_kafka()

    def stop(self) -> None:
        """Signal the consumer to stop after the current message is processed."""
        self._stop_event.set()
        logger.info("kafka_consumer_stop_requested", group_id=self._config.group_id)


# Import here to avoid circular imports at module top
from messaging.kafka.consumer.errors import MalformedDataError  # noqa: E402
