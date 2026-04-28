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
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from messaging.kafka.consumer.errors import ConsumerError, FatalError, RetryableError
from observability import ServiceMetrics, get_logger  # type: ignore[import-untyped]
from observability import create_metrics as _create_metrics  # type: ignore[import-untyped]

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
    session_timeout_ms: int = 30_000
    heartbeat_interval_ms: int = 10_000
    max_poll_interval_ms: int = 300_000
    max_poll_records: int = 500
    poll_timeout_seconds: float = 1.0
    max_retries: int = 5
    initial_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    backoff_multiplier: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        """Return Confluent-compatible consumer config dict."""
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
            "session.timeout.ms": self.session_timeout_ms,
            "heartbeat.interval.ms": self.heartbeat_interval_ms,
            "max.poll.interval.ms": self.max_poll_interval_ms,
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
    ) -> None:
        self._config = config
        self._metrics = metrics or _create_metrics(config.group_id)
        self._consumer: Any = None  # confluent_kafka.Consumer, assigned in _init_kafka
        self._stop_event = asyncio.Event()

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
    async def dead_letter(self, failure: FailureInfo[TFailure]) -> None:
        """Move a failure record to the dead-letter store.

        Called when ``failure.attempt >= config.max_retries``.

        Args:
            failure: :class:`FailureInfo` that exceeded max retries.
        """

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

    def _init_kafka(self) -> None:
        """Initialise the Confluent Kafka consumer."""
        from confluent_kafka import Consumer

        self._consumer = Consumer(self._config.to_dict())
        self._consumer.subscribe(self._config.topics)
        logger.info(
            "kafka_consumer_started",
            group_id=self._config.group_id,
            topics=self._config.topics,
        )

    def _shutdown_kafka(self) -> None:
        """Close the Confluent Kafka consumer gracefully."""
        if self._consumer is not None:
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

        async with await self.get_unit_of_work() as uow:
            try:
                await self.process_message(key, value, headers)
                await self.mark_processed(event_id)
                await uow.commit()
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
                low, high = self._consumer.get_watermark_offsets(tp, timeout=1.0)
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
                    self._record_consumer_lag()
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
