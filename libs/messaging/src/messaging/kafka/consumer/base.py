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
import contextlib
import dataclasses
import json
import os
import random
import sys
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, runtime_checkable

from messaging.kafka.consumer.backpressure import BackpressurePolicy, LagCalculator
from messaging.kafka.consumer.errors import ConsumerError, FatalError, RetryableError
from messaging.kafka_config import apply_base_rdkafka_config
from observability import (  # type: ignore[import-untyped]
    KAFKA_CONSUMER_MESSAGES,
    ServiceMetrics,
    get_logger,
)
from observability import create_metrics as _create_metrics  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from confluent_kafka import TopicPartition

logger = get_logger(__name__)


# BP-NEW asyncpg pool resilience (Final-QA-3-deep):
# Tuple of exception classes that signal the underlying asyncpg connection
# was killed out from under SQLAlchemy (typical after a Postgres restart).
# Import lazily and guard with try/except — ``libs/messaging`` does not
# hard-depend on asyncpg, but every consumer in worldview happens to use it.
# When asyncpg is not installed (tests, alternate drivers) we still want the
# consumer to be importable; the empty tuple makes the ``except`` clause a
# no-op which is the correct fallback.
try:
    # Cover BOTH codes: import-not-found (asyncpg absent) AND import-untyped
    # (asyncpg installed but ships no stubs — the case in CI's mypy env).
    from asyncpg.exceptions import (  # type: ignore[import-not-found, import-untyped]
        ConnectionDoesNotExistError as _AsyncpgConnDoesNotExist,
    )
    from asyncpg.exceptions import (  # type: ignore[import-not-found, import-untyped]
        InterfaceError as _AsyncpgInterfaceError,
    )

    _ASYNCPG_CONN_ERRORS: tuple[type[BaseException], ...] = (
        _AsyncpgConnDoesNotExist,
        _AsyncpgInterfaceError,
    )
except ImportError:  # pragma: no cover - defensive
    _ASYNCPG_CONN_ERRORS = ()


# ── LIB-002 / TASK-W2-06: dead-letter topic emission ──────────────────────────
#
# Suffix appended to the original topic name to derive the canonical DLQ
# topic.  Centralised here so subclasses and operators have a single source
# of truth.  Following the worldview ``<domain>.<entity>.<verb>.v<version>``
# convention, ``.dead-letter.v1`` is appended verbatim.
DLQ_TOPIC_SUFFIX: str = ".dead-letter.v1"


# ── F-2 / Fix-3 (2026-06-11): cross-service dead-letter metric ────────────────
#
# A single global Prometheus counter so operators can alert on dead-letter
# bursts across every consumer in one expression:
#
#   rate(kafka_messages_dead_lettered_total[5m]) > 0
#
# Registered on the default global REGISTRY at import time with the same
# duplicate-registration guard used for ``KAFKA_CONSUMER_MESSAGES`` in
# ``observability.metrics`` (a test may re-import this module under a reloaded
# registry).  ``prometheus_client`` is imported guardedly: ``libs/messaging``
# pulls it in transitively via ``observability``, but the guard keeps the
# module importable (metric becomes a no-op) in any stripped-down environment
# so the dead-letter counting never crashes a consumer.
try:
    from prometheus_client import REGISTRY as _PROM_REGISTRY
    from prometheus_client import Counter as _PromCounter

    try:
        KAFKA_MESSAGES_DEAD_LETTERED = _PromCounter(
            "kafka_messages_dead_lettered_total",
            "Total Kafka messages dead-lettered by this client (cross-service rollup).",
            labelnames=("service", "topic", "reason"),
        )
    except ValueError:
        # Already registered (re-import / test reload) — fetch the existing one.
        _existing_dl = _PROM_REGISTRY._names_to_collectors.get("kafka_messages_dead_lettered_total")
        if _existing_dl is None:
            raise
        KAFKA_MESSAGES_DEAD_LETTERED = _existing_dl  # type: ignore[assignment]
except Exception:  # pragma: no cover - defensive (prometheus_client absent)

    class _NoOpDeadLetterMetric:
        """Fallback so dead-letter counting never raises when prometheus is absent."""

        def labels(self, **_kwargs: str) -> _NoOpDeadLetterMetric:
            return self

        def inc(self, _amount: float = 1.0) -> None:
            pass

    KAFKA_MESSAGES_DEAD_LETTERED = _NoOpDeadLetterMetric()  # type: ignore[assignment]


# ── Consumer liveness heartbeat (2026-06-16, BP-700) ──────────────────────────
#
# Mirror of the dispatcher-side ``{ns}_outbox_last_delivery_timestamp`` staleness
# gauge (commit f3b5eb14c).  Every consumer publishes a single global gauge
# ``kafka_consumer_last_progress_timestamp`` (unix seconds) that is refreshed on
# EVERY poll cycle — whether or not a message was returned — so a HEALTHY but
# idle consumer still heartbeats, while a DEAD poll loop (the silent-consumer-
# death incident) goes stale.  A container healthcheck / Prometheus alert can
# then fire on staleness:
#
#   time() - kafka_consumer_last_progress_timestamp{...} > 300
#
# The ``group_id`` label lets operators pinpoint the wedged consumer.  Same
# duplicate-registration guard + no-op fallback as the dead-letter counter above
# so the heartbeat never crashes a consumer in a stripped-down environment.
try:
    from prometheus_client import REGISTRY as _PROM_REGISTRY_HB
    from prometheus_client import Gauge as _PromGauge

    try:
        KAFKA_CONSUMER_LAST_PROGRESS = _PromGauge(
            "kafka_consumer_last_progress_timestamp",
            "Unix timestamp of this consumer's last poll-loop progress (liveness heartbeat).",
            labelnames=("service", "group_id"),
        )
    except ValueError:
        _existing_hb = _PROM_REGISTRY_HB._names_to_collectors.get("kafka_consumer_last_progress_timestamp")
        if _existing_hb is None:
            raise
        KAFKA_CONSUMER_LAST_PROGRESS = _existing_hb  # type: ignore[assignment]
except Exception:  # pragma: no cover - defensive (prometheus_client absent)

    class _NoOpHeartbeatGauge:
        """Fallback so heartbeat updates never raise when prometheus is absent."""

        def labels(self, **_kwargs: str) -> _NoOpHeartbeatGauge:
            return self

        def set(self, _value: float) -> None:
            pass

    KAFKA_CONSUMER_LAST_PROGRESS = _NoOpHeartbeatGauge()  # type: ignore[assignment]


# Tuple of exception type NAMES (matched on the class name, since librdkafka
# wraps everything in ``confluent_kafka.KafkaException``/``KafkaError`` and we
# do not want a hard import dependency on confluent_kafka at module import time)
# plus the stdlib transient types that signal a *transient broker/transport*
# problem the consumer should RECONNECT through rather than die on.  Used by
# :meth:`BaseKafkaConsumer._is_transient_broker_error`.
_TRANSIENT_BROKER_ERROR_NAMES: frozenset[str] = frozenset(
    {
        "KafkaException",
        "KafkaError",
        "TimeoutError",
        "ConnectionError",
        "ConnectionResetError",
        "ConnectionRefusedError",
        "BrokerNotAvailableError",
        "NodeNotReadyError",
        "CoordinatorNotAvailableError",
    }
)


@runtime_checkable
class DLQEmitterProtocol(Protocol):
    """Port for publishing a single dead-letter envelope to a Kafka topic.

    The base consumer uses this protocol so subclasses can wire either an
    outbox repository (transactional, exactly-once-ish) or a direct Kafka
    producer (best-effort) without the base class caring which.

    Implementations must be safe to call from an asyncio context.  Failures
    inside ``emit`` should raise — the base consumer logs and swallows so
    a DLQ emission failure never blocks the consumer loop.
    """

    async def emit(
        self,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        key: str | None = None,
    ) -> None:
        """Publish a single DLQ envelope.

        Args:
            topic: Target Kafka topic (already suffixed with ``.dead-letter.v1``).
            payload: JSON-serialisable envelope describing the failure.
            headers: Optional Kafka headers (string-string).
            key: Optional Kafka partition key (typically the original event_id).
        """
        ...


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
    # F-2 / Fix-3 (2026-06-11): opt-in persistent retry counter.
    #
    # When False (the DEFAULT) the consumer behaves EXACTLY as it did before
    # this flag existed — ``_handle_failure`` uses a hardcoded attempt=1, never
    # seeks back, and only ``FatalError`` ever dead-letters (the historical,
    # known-broken-but-stable behaviour).  This guarantees byte-for-byte
    # behaviour-equivalence for the 30 consumers that do NOT opt in.
    #
    # When True the consumer:
    #   * reads a PERSISTED attempt count keyed by (group_id, event_id) via
    #     :meth:`_get_attempt_count` (subclass-provided; default returns 0),
    #   * dead-letters AND commits the offset once attempts are exhausted (so
    #     the offset advances past the now-dead-lettered poison message),
    #   * otherwise records the attempt, does NOT commit, and SEEKS BACK to the
    #     failed offset so librdkafka redelivers it (with exponential backoff)
    #     instead of silently skipping it on the next successful message.
    #
    # Rollout is per-consumer and deliberately separate from this commit — a
    # consumer must also provide a durable ``failed_events`` table + override
    # :meth:`_get_attempt_count` / :meth:`_record_attempt` before flipping this
    # to True, otherwise attempt counts reset to 0 every redelivery and the
    # message loops until ``dead_letter_cap`` trips.  See docs/libs/messaging.md.
    enable_persistent_retry: bool = False
    # Kafka static group membership (KIP-345). When set, this value is passed
    # to librdkafka as ``group.instance.id``. Static membership prevents
    # unnecessary rebalances on consumer restarts — useful for consumers with
    # long processing times. None (the default) uses the original dynamic
    # membership behaviour.
    group_instance_id: str | None = None
    # ── FAILURE MODE 2: consumer connection-setup resilience ──────────────────
    # The wedge incident surfaced as
    #   ``GroupCoordinator: kafka:29092: Connection setup timed out in state
    #     CONNECT (after ~31000ms)``
    # — i.e. the librdkafka shared base ``socket.connection.setup.timeout.ms``
    # of 30_000 (30s, +jitter ≈ 31s) is the exact knob that fired. A coordinator
    # blip should self-heal in *seconds*, not block a full 31s per attempt before
    # the BP-700 reconnect loop even gets a turn. We lower it to 10s **for
    # consumers only** (this value is spread on top of the shared base in
    # ``to_dict``, so it overrides the base without touching producer config,
    # which other owners control). Settings-driven so an operator can retune.
    socket_connection_setup_timeout_ms: int = 10_000
    # Close idle broker sockets after this long so a half-dead connection that
    # survived a host-sleep / NAT-timeout is torn down and re-established on the
    # next use instead of hanging until a poll fails. 9 minutes < the common
    # 10-minute cloud LB idle cutoff, so we drop the socket before the LB does.
    connections_max_idle_ms: int = 540_000
    # CPU-bottleneck fix (2026-06-21 cpu-profile): when a consumer is wedged off
    # the broker (network-path break / CPU-starved handshake), librdkafka's
    # background thread retries the connection. Without an explicit, generous
    # backoff CAP it reconnects aggressively and can busy-spin at ~90% CPU at ZERO
    # throughput (observed live: 4 market-data consumers + the temporal-event
    # consumer pegged a core EACH while processing 0 messages — see
    # docs/audits/2026-06-21-*-cpu-profile.md). Pinning a 1s floor and a 20s cap
    # makes a disconnected client back off (one attempt per ≤20s) instead of
    # hot-spinning, bounding the wasted CPU AND easing the reconnect load on an
    # already-stressed broker. Healthy connections are unaffected (these only
    # apply while disconnected). Settings-driven so an operator can retune.
    reconnect_backoff_ms: int = 1_000
    reconnect_backoff_max_ms: int = 20_000

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
        # PLAN-0093 Wave A-2 (F-LOG-003): prepend the rdkafka base config so
        # every consumer carries broker.address.ttl=30s + family=v4.  User
        # keys are spread on top → per-consumer overrides still win.
        cfg: dict[str, object] = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": self.group_id,
            "auto.offset.reset": self.auto_offset_reset,
            "enable.auto.commit": self.enable_auto_commit,
            "session.timeout.ms": self.session_timeout_ms,
            "heartbeat.interval.ms": self.heartbeat_interval_ms,
            "max.poll.interval.ms": self.max_poll_interval_ms,
            "partition.assignment.strategy": self.partition_assignment_strategy,
            # FAILURE MODE 2: consumer-local connection-setup resilience. These
            # are spread on top of the shared base in ``apply_base_rdkafka_config``
            # (caller keys win), so they override the base 30s setup-timeout for
            # consumers ONLY — producers keep the shared base value. A coordinator
            # connect that hangs is failed fast (10s) so the BP-700 reconnect loop
            # retries promptly instead of burning ~31s per attempt.
            "socket.connection.setup.timeout.ms": self.socket_connection_setup_timeout_ms,
            "connections.max.idle.ms": self.connections_max_idle_ms,
            # Reconnect backoff (see field docs): bound the disconnected-client
            # reconnect spin so a wedged consumer backs off instead of pegging a
            # core at zero throughput.
            "reconnect.backoff.ms": self.reconnect_backoff_ms,
            "reconnect.backoff.max.ms": self.reconnect_backoff_max_ms,
        }
        # KIP-345 static group membership: only set if configured so consumers
        # that omit it retain the original dynamic membership behaviour. The
        # settings-driven scopes default to an empty string ("") rather than
        # None (pydantic ``str = ""`` fields), so a falsy guard — not ``is not
        # None`` — is required for empty to stay a true no-op (PLAN-0113 NFR-3:
        # the key must be ABSENT from the rdkafka payload for dynamic members).
        if self.group_instance_id:
            cfg["group.instance.id"] = self.group_instance_id
        return apply_base_rdkafka_config(cfg)


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
        raw_payload: Original Kafka message bytes (``msg.value()``).  P0-①
            (2026-06-18): carried through to :meth:`_dead_letter_impl` so a
            subclass can persist a REQUEUE-ABLE payload (the original doc_id /
            minio_silver_key) into its DLQ table instead of a metadata-only
            stub.  ``None`` when the raw bytes were unavailable at failure time.
    """

    event_id: str
    topic: str
    partition: int
    offset: int
    attempt: int
    last_error: BaseException
    record: TFailure | None = None
    raw_payload: bytes | None = None


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
            If *None*, metrics are created using *metrics_namespace* (or, if not
            provided, falling back to ``config.group_id``).
        metrics_namespace: Optional override for the Prometheus namespace prefix
            used when *metrics* is None. Service-level wirings should pass the
            service name (e.g. ``"alert"``) so emitted series match per-service
            Grafana dashboards (e.g. ``alert_kafka_messages_consumed_total``).
            When None (default), the legacy ``config.group_id`` is used as the
            namespace — backwards compatible with consumers that have not yet
            opted into the override.
    """

    def __init__(
        self,
        config: ConsumerConfig,
        metrics: ServiceMetrics | None = None,
        backpressure_policy: BackpressurePolicy | None = None,
        dlq_emitter: DLQEmitterProtocol | None = None,
        *,
        metrics_namespace: str | None = None,
    ) -> None:
        self._config = config
        # Default to group_id for backwards compatibility; allow service wirings
        # to override so dashboards keyed on `<service>_kafka_messages_consumed_total`
        # actually match the emitted series (see alert-service.json).
        self._metrics = metrics or _create_metrics(metrics_namespace or config.group_id)
        self._consumer: Any = None  # confluent_kafka.Consumer, assigned in _init_kafka
        self._stop_event = asyncio.Event()
        # Running count of dead-letters sent; crashes the consumer when it
        # exceeds dead_letter_cap to trigger a container restart.
        self._dead_letter_count: int = 0
        # LIB-002 (TASK-W2-06): optional dead-letter topic emitter.  When set,
        # the default :meth:`_dead_letter_impl` publishes failure envelopes to
        # ``<original_topic>.dead-letter.v1`` so DLQ messages are observable
        # from kafka-ui and external DLQ consumers.  When ``None``, the
        # default impl logs a warning and short-circuits — subclasses that
        # only persist failures to a DB table continue to work unchanged.
        self._dlq_emitter: DLQEmitterProtocol | None = dlq_emitter
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
        # BP-700 liveness heartbeat: monotonic-ish wall-clock timestamp (unix
        # seconds) of the last poll-loop progress.  Refreshed every poll cycle
        # (idle OR message) so an alive-but-idle consumer still heartbeats while
        # a dead loop goes stale.  ``-1.0`` means "not yet started".  Exposed via
        # :meth:`seconds_since_progress` for an in-process liveness healthcheck.
        self._last_progress_ts: float = -1.0
        # BP-700 reconnect bookkeeping: number of consecutive transient-error
        # reconnect cycles.  Drives exponential backoff and the terminal-stop
        # ceiling so a permanently-down broker still eventually force-exits for a
        # fresh container (instead of spinning a reconnect loop forever).
        self._reconnect_attempts: int = 0

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

    async def _dead_letter_impl(self, failure: FailureInfo[TFailure]) -> None:
        """Default dead-letter handler — publish to ``<topic>.dead-letter.v1``.

        Called by :meth:`dead_letter` after the cap check passes.  The
        default implementation emits a JSON failure envelope to
        ``<failure.topic>.dead-letter.v1`` via the configured
        :attr:`_dlq_emitter` so the message is observable from kafka-ui and
        any external DLQ consumer.

        Back-compat: this method used to be abstract.  Concrete subclasses
        across worldview's services already override it (typically to write
        a DLQ row to a Postgres table) — those overrides continue to work
        unchanged.  Subclasses that want to keep DB persistence AND gain
        topic emission should override and call ``await super().
        _dead_letter_impl(failure)`` after their DB write so both happen.

        To OPT OUT of topic emission entirely (e.g. consumers whose DLQ
        contract is DB-only by design) simply do NOT pass a ``dlq_emitter``
        when constructing the consumer; the default impl will then log a
        warning and short-circuit.  Document the rationale at the override
        site.

        Args:
            failure: :class:`FailureInfo` that exceeded max retries.
        """
        # No emitter wired → preserve historical behaviour (no topic emit)
        # but log a warning so operators can spot consumers that should be
        # upgraded.  We intentionally do NOT raise: persistence to a DB
        # dead-letter table (the typical subclass override) has already
        # happened by this point, so failing here would just double-count
        # the failure.
        if self._dlq_emitter is None:
            logger.warning(
                "dead_letter_no_emitter_configured",
                topic=failure.topic,
                event_id=failure.event_id,
                attempt=failure.attempt,
                hint="pass dlq_emitter to BaseKafkaConsumer to enable DLQ topic publishing",
            )
            return

        dlq_topic = f"{failure.topic}{DLQ_TOPIC_SUFFIX}"
        # Failure envelope — JSON-serialisable summary of the failure.  This
        # is deliberately metadata-only (no original payload bytes) because
        # the abstract failure record does not carry the raw message body;
        # subclasses that want to include the raw payload can override.
        envelope: dict[str, Any] = {
            "event_id": failure.event_id,
            "original_topic": failure.topic,
            "partition": failure.partition,
            "offset": failure.offset,
            "attempt": failure.attempt,
            "error": str(failure.last_error)[:1024],
            "error_type": type(failure.last_error).__name__,
            "dead_lettered_at": datetime.now(UTC).isoformat(),
            "consumer_group": self._config.group_id,
        }
        # Standard headers — operators rely on these for routing and
        # debugging in kafka-ui.  Truncated where unbounded to keep header
        # size within Kafka's per-message limit (1 MiB by default but each
        # header is best kept well under 1 KiB).
        headers: dict[str, str] = {
            "X-Dead-Letter-Error": str(failure.last_error)[:1024],
            "X-Dead-Letter-Original-Topic": failure.topic,
            "X-Dead-Letter-Timestamp": envelope["dead_lettered_at"],
            "X-Dead-Letter-Event-Id": failure.event_id,
        }
        try:
            await self._dlq_emitter.emit(
                topic=dlq_topic,
                payload=envelope,
                headers=headers,
                key=failure.event_id,
            )
        except Exception as exc:
            # DLQ emission failure must never crash the consumer loop —
            # the message has already been logged + retried + counted
            # against the cap.  Log loud so operators can spot the gap.
            logger.error(
                "dead_letter_emit_failed",
                topic=dlq_topic,
                event_id=failure.event_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return

        logger.warning(
            "message_dead_lettered",
            topic=dlq_topic,
            original_topic=failure.topic,
            event_id=failure.event_id,
            attempt=failure.attempt,
            error=str(failure.last_error)[:512],
        )

    @staticmethod
    def _serialize_dlq_envelope(envelope: dict[str, Any]) -> bytes:
        """JSON-encode a DLQ envelope to UTF-8 bytes.

        Exposed as a helper so subclasses or emitter implementations that
        need raw bytes (e.g. a direct ``confluent_kafka.Producer.produce``)
        can use the same encoding the rest of the platform expects.
        """
        return json.dumps(envelope, separators=(",", ":"), default=str).encode("utf-8")

    async def dead_letter(self, failure: FailureInfo[TFailure], reason: str | None = None) -> None:
        """Move a failure record to the dead-letter store with cap enforcement.

        Increments the internal dead-letter counter, emits the cross-service
        ``kafka_messages_dead_lettered_total`` metric, and delegates to
        :meth:`_dead_letter_impl`.  If the counter exceeds
        ``config.dead_letter_cap``, a :exc:`RuntimeError` is raised to crash
        the consumer and trigger a container restart — preventing a runaway
        poison-message storm from silently filling the DLQ.

        Args:
            failure: :class:`FailureInfo` that exceeded max retries.
            reason: Optional dead-letter reason for the metric ``reason`` label
                (e.g. ``"fatal"``, ``"max_retries"``, ``"timeout"``).  When
                ``None`` it is derived from the failure's error type so every
                call site — including the historical FatalError path that never
                opted into persistent retry — produces a sensible label.

        Raises:
            RuntimeError: When the dead-letter count exceeds the configured cap.
        """
        self._dead_letter_count += 1
        # Emit the metric BEFORE the cap check so the message that trips the cap
        # is still counted as dead-lettered (it WAS routed here as a DLQ event).
        # This path fires for EVERY dead-letter — including the FatalError path
        # that already dead-letters today — so non-opted consumers also gain the
        # metric without any behaviour change.
        metric_reason = reason or (
            "fatal" if isinstance(failure.last_error, FatalError) else type(failure.last_error).__name__
        )
        KAFKA_MESSAGES_DEAD_LETTERED.labels(
            service=(self._metrics.service_name if self._metrics is not None else self._config.group_id),
            topic=failure.topic,
            reason=metric_reason,
        ).inc()
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

    # ── BP-700: liveness heartbeat + transient-error reconnect ────────────────

    def _record_progress(self) -> None:
        """Refresh the liveness heartbeat (gauge + instance timestamp).

        Called every poll cycle — on an idle poll (no message) AND after a
        successful consume — so a HEALTHY but idle consumer still heartbeats
        while a DEAD poll loop (the silent-consumer-death incident) goes stale.
        A staleness alert / healthcheck then catches the dead loop that the
        HTTP-only healthcheck never could.
        """
        now = time.time()
        self._last_progress_ts = now
        KAFKA_CONSUMER_LAST_PROGRESS.labels(
            service=(self._metrics.service_name if self._metrics is not None else self._config.group_id),
            group_id=self._config.group_id,
        ).set(now)

    def seconds_since_progress(self) -> float | None:
        """Return seconds since the last poll-loop progress, or ``None``.

        ``None`` before the loop has made its first progress tick (so a probe
        does not flag a just-started consumer).  Exposed so an in-process
        liveness endpoint / CLI healthcheck can fail when the loop is stale —
        the load-bearing signal that prevents a dead loop from ever again
        looking "healthy".
        """
        if self._last_progress_ts < 0:
            return None
        return time.time() - self._last_progress_ts

    @staticmethod
    def _is_transient_broker_error(exc: BaseException) -> bool:
        """Classify *exc* as a transient broker/transport error worth reconnecting.

        We match on the exception class name (and its MRO) rather than importing
        ``confluent_kafka`` at module scope — librdkafka wraps connectivity
        problems in ``KafkaException``/``KafkaError``, and a connection setup
        timeout surfaces as a stdlib ``TimeoutError`` / ``ConnectionError``.
        A transient classification triggers a bounded-backoff RECONNECT instead
        of a terminal stop; anything unrecognised falls through to the normal
        failure/DLQ path (so a genuine application bug is never masked as a
        broker blip).
        """
        return any(klass.__name__ in _TRANSIENT_BROKER_ERROR_NAMES for klass in type(exc).__mro__)

    def _reset_consumer(self) -> None:
        """Tear down the cached consumer so the next cycle rebuilds a fresh one.

        Mirror of the dispatcher's ``_reset_producer()`` (commit f3b5eb14c): on
        a transient broker error the cached ``confluent_kafka.Consumer`` may hold
        a half-open connection that never recovers.  We best-effort ``close()``
        it (swallowing errors — it is already broken) and null the reference so
        :meth:`_reconnect_with_backoff` builds a brand-new consumer with a fresh
        DNS lookup + group rejoin.  Paused-partition tracking is cleared because
        the new consumer starts with an empty assignment.
        """
        old = self._consumer
        self._consumer = None
        self._paused_partitions.clear()
        if old is not None:
            try:
                old.close()
            except Exception as exc:  # pragma: no cover - best-effort teardown
                logger.warning(
                    "kafka_consumer_reset_close_failed",
                    group_id=self._config.group_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect the consumer after a transient broker error, with backoff.

        Returns ``True`` once a fresh consumer is subscribed, or ``False`` if the
        stop event fired during the backoff (graceful shutdown).  Increments
        :attr:`_reconnect_attempts` and sleeps an exponential, jittered backoff
        before rebuilding so a flapping broker is not hammered.  When the attempt
        count crosses :attr:`_reconnect_max_attempts` the consumer FORCE-EXITS
        (``sys.exit(2)``) so the orchestrator restarts the container with a fresh
        process — a truly unrecoverable broker outage degrades to a loud restart,
        never a silent zombie.
        """
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._reconnect_max_attempts:
            logger.critical(
                "kafka_consumer_reconnect_exhausted",
                group_id=self._config.group_id,
                attempts=self._reconnect_attempts,
                action="exiting_with_code_2_for_fresh_container",
            )
            # Hard process exit (NOT ``sys.exit`` — a bare SystemExit raised in
            # this Task-driven coroutine gets captured/swallowed as the Task
            # result and leaves a zombie; see :meth:`_force_process_exit`).
            self._force_process_exit(2)
        backoff = self._compute_backoff(self._reconnect_attempts)
        logger.warning(
            "kafka_consumer_reconnecting",
            group_id=self._config.group_id,
            attempt=self._reconnect_attempts,
            backoff_seconds=round(backoff, 2),
        )
        # Interruptible backoff — a stop signal during the wait ends cleanly.
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
            return False  # stop fired during backoff → graceful shutdown
        except TimeoutError:
            pass
        self._reset_consumer()
        try:
            self._init_kafka()
        except Exception as exc:
            # Rebuild itself failed (e.g. broker still down) — log and let the
            # NEXT loop iteration retry via this same path; do not crash.
            logger.warning(
                "kafka_consumer_reconnect_init_failed",
                group_id=self._config.group_id,
                attempt=self._reconnect_attempts,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        logger.info(
            "kafka_consumer_reconnected",
            group_id=self._config.group_id,
            attempt=self._reconnect_attempts,
        )
        return True

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
            except TimeoutError as timeout_exc:
                # BP-302 watchdog: poison message hung processing for timeout_s.
                # Dump a stack trace so the hung frame is captured, then roll back
                # the whole-article unit of work (no partial-progress checkpoint).
                import faulthandler

                faulthandler.dump_traceback(file=sys.stderr)
                await uow.rollback()

                # P0-② (2026-06-18): the watchdog used to FORCE attempt=max_retries
                # and dead-letter the message INLINE, turning a transient host /
                # GLiNER saturation into permanent data loss (2,236 of 2,316
                # historical dead-letters).  For consumers that opt into the
                # durable attempt-count retry path (enable_persistent_retry=True),
                # RE-RAISE the timeout as a NetworkTimeoutError so it flows through
                # ``_handle_failure`` exactly like any other transient failure —
                # counting as ONE attempt, seeking back with backoff, and dead-
                # lettering ONLY after genuinely exhausting max_retries.  Poison
                # protection is preserved: a message that ALWAYS times out reaches
                # max_retries via the durable counter and is then dead-lettered.
                #
                # NetworkTimeoutError is a RetryableError, so the OFF path (legacy
                # consumers with attempt hardcoded to 1) would loop forever on it —
                # there the historical terminal-inline-dead-letter is preserved
                # byte-for-byte below.
                from messaging.kafka.consumer.errors import NetworkTimeoutError

                if self._config.enable_persistent_retry:
                    raise NetworkTimeoutError(
                        f"message_processing_timeout after {timeout_s}s",
                    ) from timeout_exc

                # ── Legacy OFF path: terminal inline dead-letter (unchanged) ──
                _timeout_failure: FailureInfo[TFailure] = FailureInfo(
                    event_id=event_id,
                    topic=topic,
                    partition=msg.partition(),
                    offset=msg.offset(),
                    attempt=self._config.max_retries,
                    last_error=TimeoutError(f"message_processing_timeout after {timeout_s}s"),
                    raw_payload=raw_value,
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
        # PLAN-0093 Wave A-2 (F-LOG-003): cross-service counter so the
        # ``KafkaConsumerStalled`` alert can pivot across every consumer in
        # a single Prometheus expression.  ``service`` label uses the
        # ServiceMetrics service_name when available, falling back to the
        # consumer group_id (always present).
        KAFKA_CONSUMER_MESSAGES.labels(
            service=self._metrics.service_name if self._metrics is not None else self._config.group_id,
            topic=topic,
            consumer_group=self._config.group_id,
        ).inc()

    # ── F-2 / Fix-3: persistent attempt-count hooks (opt-in) ──────────────────
    #
    # These default to no-ops so the 30 existing consumers are completely
    # unaffected.  A consumer opts in by (a) setting
    # ``ConsumerConfig.enable_persistent_retry=True`` AND (b) overriding both
    # methods to read/write a durable ``failed_events`` table keyed by
    # ``(group_id, event_id)``.  Without a durable store the attempt count
    # resets to 0 on every redelivery and the message loops until the
    # ``dead_letter_cap`` trips — hence rollout requires the table first.

    async def _get_attempt_count(self, event_id: str) -> int:
        """Return the number of FAILED attempts already recorded for *event_id*.

        Default implementation returns 0 (no persistence).  Override in a
        consumer that opts into ``enable_persistent_retry`` to read the count
        from a durable ``failed_events(consumer_group, event_id, attempt, ...)``
        table.  The returned value is the count of PRIOR failures; the current
        attempt is therefore ``returned_count + 1``.

        Args:
            event_id: The idempotency event id of the failing message.
        """
        return 0

    async def _record_attempt(self, event_id: str, attempt: int, error: BaseException) -> None:
        """Persist (upsert) the latest *attempt* count + *error* for *event_id*.

        Default implementation is a no-op.  Override alongside
        :meth:`_get_attempt_count` to upsert a row into the durable
        ``failed_events`` table so the count survives redelivery.

        Args:
            event_id: The idempotency event id of the failing message.
            attempt: The 1-based attempt number that just failed.
            error: The exception raised on this attempt.
        """
        return None

    def _seek_back(self, msg: Any, attempt: int) -> None:
        """Seek the consumer back to *msg*'s offset so it is redelivered.

        Used only on the opted-in retryable path.  Without this seek, the
        failed message's offset is NOT committed but librdkafka's in-memory
        position has already advanced past it — the next successful message
        would then commit PAST the failed offset, silently skipping it.
        Seeking back to ``msg.offset()`` resets the in-memory position so the
        very next ``poll()`` redelivers the SAME message.

        A bounded blocking ``sleep`` provides exponential backoff between
        redeliveries to avoid a hot loop.  The backoff is capped by
        ``max_backoff_seconds`` via :meth:`_compute_backoff`.

        Args:
            msg: The raw Confluent Kafka message that failed.
            attempt: The 1-based attempt number that just failed (drives backoff).
        """
        from confluent_kafka import TopicPartition

        tp = TopicPartition(msg.topic(), msg.partition(), msg.offset())
        try:
            self._consumer.seek(tp)
        except Exception as exc:
            # Seek can fail if the partition was just revoked in a rebalance.
            # That is acceptable: on reassignment the uncommitted offset is
            # redelivered anyway.  Log and continue — never crash the loop.
            logger.warning(
                "consumer.retry.seek_back_failed",
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
                error=str(exc),
            )
            return
        # Exponential backoff with full jitter before the next redelivery so a
        # persistently-failing message does not spin the CPU.  Bounded by
        # max_backoff_seconds (full-jitter handled by _compute_backoff).
        backoff = self._compute_backoff(attempt)
        time.sleep(backoff)

    async def _handle_failure(
        self,
        msg: Any,
        exc: BaseException,
    ) -> bool:
        """Handle a failed message — retry or dead-letter.

        Two code paths, selected by ``ConsumerConfig.enable_persistent_retry``:

        * **OFF (default)** — historical behaviour, byte-for-byte: attempt is
          hardcoded to 1, the offset is never committed and never seeked, and
          only ``FatalError`` ever dead-letters (the ``attempt >= max_retries``
          clause is unreachable with a constant attempt of 1).

        * **ON (opt-in)** — the real attempt count is read from the durable
          store (``_get_attempt_count`` + 1).  On exhaustion or a FatalError the
          message is dead-lettered AND its offset committed so it advances past
          the poison message.  Otherwise the attempt is recorded and the
          consumer SEEKS BACK to the failed offset (with backoff) so the message
          is redelivered instead of silently skipped.

        Returns:
            ``True`` when the offset is SETTLED and may advance — i.e. the OFF
            path (historical: failure was logged and treated as handled), or the
            ON path dead-lettered the message (it was committed past).  ``False``
            when the ON path SEEKED BACK for redelivery — the offset must NOT
            advance (a batch consumer must treat it as a commit barrier so it
            does not skip the still-retrying message).  The serial base ``run``
            loop ignores the return value (it never commits after a failure); the
            value exists for batch-dispatching subclasses (e.g. the nlp-pipeline
            article consumer) that DO own the contiguous-offset commit decision.

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

        # ── OFF path: exactly the historical behaviour (no seek, no commit) ───
        if not self._config.enable_persistent_retry:
            failure: FailureInfo[TFailure] = FailureInfo(
                event_id=event_id,
                topic=topic,
                partition=partition,
                offset=offset,
                attempt=1,
                last_error=exc,
                # P0-①: carry the ORIGINAL message bytes so a subclass
                # ``_dead_letter_impl`` can persist a requeue-able payload.
                raw_payload=raw_value,
            )
            # BP-700: the dead-letter / store_failure persistence below writes to
            # the consuming service's DB.  During the incident a concurrent
            # asyncpg ``TimeoutError`` raised HERE (while dead-lettering a timed-
            # out message) escaped ``_handle_failure`` entirely, propagated out of
            # ``run()``, and silently killed the consumer.  A downstream DLQ/retry
            # WRITE failure must NEVER terminate the consume loop — wrap it,
            # log loud, and treat the message as handled (the offset advances,
            # exactly as the historical commit-as-handled OFF path did).  The
            # message is re-deliverable via the dedup table if needed.
            try:
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
            except RuntimeError:
                # The dead_letter cap-exceeded RuntimeError is an INTENTIONAL
                # poison-storm crash signal — re-raise so the loop force-restarts.
                raise
            except Exception as persist_exc:
                logger.error(
                    "kafka_failure_persist_failed",
                    event_id=event_id,
                    topic=topic,
                    original_error=str(exc),
                    persist_error=str(persist_exc),
                    persist_error_type=type(persist_exc).__name__,
                )
            # OFF path is historically commit-as-handled: the offset advances.
            return True

        # ── ON path: persisted attempt count + seek-back / commit-on-DLQ ──────
        attempt = await self._get_attempt_count(event_id) + 1
        failure = FailureInfo(
            event_id=event_id,
            topic=topic,
            partition=partition,
            offset=offset,
            attempt=attempt,
            last_error=exc,
            # P0-①: carry the ORIGINAL message bytes so a subclass
            # ``_dead_letter_impl`` can persist a requeue-able payload.
            raw_payload=raw_value,
        )

        if isinstance(exc, FatalError) or attempt >= self._config.max_retries:
            reason = "fatal" if isinstance(exc, FatalError) else "max_retries"
            await self.dead_letter(failure, reason=reason)
            # Commit the offset so the consumer advances PAST the now-dead-
            # lettered poison message instead of redelivering it forever.
            if not self._config.enable_auto_commit and self._consumer is not None:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._consumer.commit, msg)
                except Exception as commit_exc:
                    # If the commit fails the message will be redelivered and
                    # dead-lettered again (idempotent via the dedup table) —
                    # never crash the loop on a commit error.
                    logger.warning(
                        "consumer.retry.dead_letter_commit_failed",
                        event_id=event_id,
                        topic=topic,
                        error=str(commit_exc),
                    )
            logger.error(
                "kafka_message_dead_lettered",
                event_id=event_id,
                error=str(exc),
                topic=topic,
                attempt=attempt,
            )
            # Dead-lettered + committed: the offset is settled and may advance.
            return True

        # Record the attempt durably so the NEXT redelivery sees attempt+1.
        await self._record_attempt(event_id, attempt, exc)
        logger.warning(
            "kafka_message_failed_retryable",
            event_id=event_id,
            attempt=attempt,
            error=str(exc),
            topic=topic,
        )
        # Seek back so the message is redelivered (with backoff) instead of
        # being silently skipped by the next successful commit.  Do NOT
        # commit here — the offset must stay uncommitted.
        self._seek_back(msg, attempt)
        # SEEKED BACK for redelivery: the offset must NOT advance.  A batch
        # consumer must treat this offset as a commit barrier so the still-
        # retrying message is not skipped by a later contiguous commit.
        return False

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

    def _compute_total_lag(self) -> int | None:
        """Sum lag across the current assignment (blocking librdkafka calls).

        Returns ``None`` when the consumer/assignment is not ready or on any
        broker error, so the caller can SKIP the sample rather than mistake an
        unreadable broker for a healthy zero-lag consumer.  Mirrors the
        watermark arithmetic in :meth:`_record_consumer_lag` but aggregates to a
        single number for the stall detector.
        """
        consumer = self._consumer
        if consumer is None:
            return None
        try:
            assignment = consumer.assignment()
            if not assignment:
                return None
            total = 0
            for tp in assignment:
                _low, high = consumer.get_watermark_offsets(tp, timeout=1.0)
                position_list = consumer.position([tp])
                if position_list and position_list[0].offset >= 0:
                    total += max(0, high - position_list[0].offset)
            return total
        except Exception:
            return None

    def _evaluate_lag_stall(self, total_lag: int) -> bool:
        """Update stall state from ``total_lag``; return ``True`` to fire an alert.

        A *stall* is lag at/above :attr:`_lag_stall_threshold` that has not
        decreased for :attr:`_lag_stall_probes` consecutive samples — i.e. the
        consumer is connected but frozen or falling behind.  Decreasing lag
        (even if still large) is healthy drain and never alerts.  After firing
        we reset the counter so the NEXT sustained window re-alerts instead of
        spamming a line every probe.
        """
        prev = self._prev_total_lag
        self._prev_total_lag = total_lag
        if total_lag < self._lag_stall_threshold:
            self._lag_stall_count = 0
            return False
        # Above threshold.  Only treat it as a stall if lag is NOT draining.
        if prev >= 0 and total_lag < prev:
            self._lag_stall_count = 0  # shrinking → healthy backlog drain
            return False
        self._lag_stall_count += 1
        if self._lag_stall_count >= self._lag_stall_probes:
            self._lag_stall_count = 0
            return True
        return False

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

    # PLAN-0093 Wave A-2 (F-LOG-003): connectivity probe configuration.
    # Tuned so a TRANSIENT broker blip under host load does not escalate to a
    # force-exit: 60 s between probes x 5 misses = a 5-minute detection window,
    # and each ``list_topics`` metadata call gets a generous 10 s to complete
    # (the host is CPU-oversubscribed; a 5 s timeout was tripping on ordinary
    # metadata latency and mislabelling a reachable broker as down).  A genuine
    # sustained outage still ends in a loud restart — the window is widened, not
    # removed.  These remain single PLATFORM-WIDE values (not ConsumerConfig
    # fields) so every consumer behaves identically — the env overrides below
    # are one global knob each, never a per-service ConsumerConfig field, which
    # preserves the no-per-service-drift property the probe depends on.
    _probe_interval_seconds: float = float(os.environ.get("KAFKA_PROBE_INTERVAL_S", "60"))
    _probe_failure_threshold: int = int(os.environ.get("KAFKA_PROBE_FAILURE_THRESHOLD", "5"))
    _probe_list_topics_timeout: float = float(os.environ.get("KAFKA_PROBE_LIST_TOPICS_TIMEOUT_S", "10"))

    # BP-700: maximum consecutive transient-error RECONNECT cycles before the
    # consumer force-exits for a fresh container.  Reserves terminal stop for a
    # truly unrecoverable broker outage while letting an ordinary blip recover
    # in-place.  At the jittered exponential backoff (capped by
    # ``max_backoff_seconds``, default 60 s) 10 attempts spans several minutes —
    # comfortably longer than a typical broker restart / leader election, yet
    # bounded so a permanently-dead broker still ends in a loud restart rather
    # than an infinite reconnect loop.  Class attr for the no-per-service-drift
    # reason as the probe knobs above.
    _reconnect_max_attempts: int = 10

    # ── Lag-stall early warning (2026-06-15, BP-699) ────────────────────────
    # The connectivity probe above only catches a DISCONNECTED broker.  It does
    # NOT catch a consumer that is connected and assigned but no longer making
    # progress — a wedged poll loop, a slow handler, a partition stuck behind a
    # poison message, or (the case that motivated this) a broker the container
    # could reach for ``list_topics`` metadata yet not actually consume from.
    # That let an OHLCV consumer fall ~19k messages behind for three days
    # unnoticed: the ``kafka_consumer_lag`` gauge existed but nothing ALERTED
    # on it.  We sample total lag on each successful probe and emit a single
    # CRITICAL ``kafka_consumer_lag_stalled`` once lag has stayed at/above the
    # threshold WITHOUT decreasing for ``_lag_stall_probes`` consecutive samples
    # (~5 min at the 60 s cadence).  Class attrs for the same no-per-service-
    # drift reason as the probe knobs above; the two ints become instance attrs
    # on first assignment (safe — immutable, never shared/mutated in place).
    _lag_stall_threshold: int = 5_000  # messages behind before we care
    _lag_stall_probes: int = 5  # consecutive non-draining samples → alert
    _prev_total_lag: int = -1
    _lag_stall_count: int = 0

    def _force_process_exit(self, code: int) -> None:
        """Terminate the WHOLE process immediately, from any asyncio/task context.

        Why not ``sys.exit()``?  ``sys.exit(code)`` merely raises ``SystemExit``
        in the *current* coroutine.  When that coroutine is driven by an
        ``asyncio.Task`` (as both force-exit call sites are — the connectivity
        probe and the run() poll loop), the ``SystemExit`` is captured as the
        Task's result rather than tearing the interpreter down.  If a
        ``done_callback`` on that Task then calls ``task.exception()`` the
        ``SystemExit`` is *retrieved and swallowed*, so the process keeps
        running.  That is the exact ZOMBIE we observed in production
        (BP: connectivity-probe zombie):

          * the probe hit 3 consecutive ``_TRANSPORT`` broker failures under
            host load and called ``sys.exit(2)``;
          * the ``SystemExit`` never reached ``asyncio.run``'s frame, the event
            loop died mid-teardown, and the ``/metrics`` + ``/healthz`` socket
            was closed;
          * Docker's healthcheck then got ``Connection refused`` → the
            container was flagged ``unhealthy`` for 16-41h, yet
            ``restart: unless-stopped`` NEVER fired because the process never
            actually exited.

        ``os._exit`` is the only primitive that guarantees the process dies now
        regardless of the asyncio/executor/greenlet state, so the orchestrator
        restarts the container with a fresh DNS lookup (the whole point of the
        force-exit).  We flush stdout/stderr and shut down the logging handlers
        first so the preceding CRITICAL diagnostic is not lost to the buffers
        ``os._exit`` would otherwise drop.

        Extracted as a method (rather than an inline ``os._exit``) so unit tests
        can patch it and assert the escalation fires without terminating the
        test interpreter.
        """
        import logging as _logging

        with contextlib.suppress(Exception):
            sys.stdout.flush()
        with contextlib.suppress(Exception):
            sys.stderr.flush()
        with contextlib.suppress(Exception):
            _logging.shutdown()
        os._exit(code)

    async def _connectivity_probe_loop(self) -> None:
        """Periodically probe the broker; force-exit on sustained failure.

        Runs alongside the poll loop.  Every ``_probe_interval_seconds`` we
        call ``consumer.list_topics(timeout=5)``; if 3 consecutive probes
        fail we log ``kafka_unreachable_for_5min`` at CRITICAL and exit
        the process with code 2 so the container orchestrator can give us
        a fresh DNS lookup on restart.

        Important properties:

        * Probe failures NEVER bubble up — only the consecutive-failure
          count matters.  The consume loop must not be affected by transient
          metadata errors.
        * ``list_topics`` is a blocking librdkafka call → hopped onto the
          default executor so it cannot delay the event loop.
        * The loop honours :attr:`_stop_event` so a graceful shutdown does
          not log misleading failure events.
        """
        loop = asyncio.get_running_loop()
        consecutive_failures = 0
        while not self._stop_event.is_set():
            # Sleep first so we do not probe immediately on startup, where the
            # consumer may not yet have completed its initial metadata fetch.
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._probe_interval_seconds,
                )
                # Stop event fired during the wait → graceful shutdown.
                return
            except TimeoutError:
                pass  # interval elapsed, run a probe

            if self._consumer is None:
                # Consumer not yet initialised; do not count as a failure.
                continue

            try:
                consumer = self._consumer  # snapshot to avoid TOCTOU if shutdown races
                timeout = self._probe_list_topics_timeout

                def _probe(c: Any = consumer, t: float = timeout) -> Any:
                    return c.list_topics(timeout=t)

                await loop.run_in_executor(None, _probe)
                # Success → reset the counter.  This is the only place a
                # success resets the counter, so a single good probe wipes
                # out two prior misses (matches the spec).
                consecutive_failures = 0
                # BP-699: the broker is reachable for metadata — now sample lag
                # for the stall early-warning.  ``get_watermark_offsets`` is a
                # blocking librdkafka call, so hop it onto the executor exactly
                # like the connectivity probe.  A ``None`` sample (assignment not
                # ready / broker hiccup) is skipped, not counted as healthy.
                total_lag = await loop.run_in_executor(None, self._compute_total_lag)
                if total_lag is not None and self._evaluate_lag_stall(total_lag):
                    logger.critical(
                        "kafka_consumer_lag_stalled",
                        group_id=self._config.group_id,
                        total_lag=total_lag,
                        threshold=self._lag_stall_threshold,
                        sustained_probes=self._lag_stall_probes,
                        probe_interval_seconds=self._probe_interval_seconds,
                        action="consumer_connected_but_not_draining_check_handler_or_force_recreate",
                    )
            except Exception as exc:
                consecutive_failures += 1
                logger.warning(
                    "kafka_connectivity_probe_failed",
                    group_id=self._config.group_id,
                    consecutive_failures=consecutive_failures,
                    threshold=self._probe_failure_threshold,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                if consecutive_failures >= self._probe_failure_threshold:
                    logger.critical(
                        "kafka_unreachable_for_5min",
                        group_id=self._config.group_id,
                        consecutive_failures=consecutive_failures,
                        action="exiting_with_code_2_for_dns_refresh",
                    )
                    # Hard process exit so the container actually restarts.
                    # ``sys.exit(2)`` here previously left a ZOMBIE: the
                    # SystemExit was captured as this probe Task's result and
                    # retrieved (swallowed) by the run() done-callback, the event
                    # loop died, the /healthz socket closed → Docker reported
                    # ``unhealthy`` forever while ``restart: unless-stopped``
                    # never fired.  See :meth:`_force_process_exit`.
                    self._force_process_exit(2)
                    return  # unreachable after os._exit; keeps type-checkers happy

    async def run(self) -> None:
        """Start consuming messages until :meth:`stop` is called.

        Runs the Kafka poll loop and the retry loop concurrently.  Blocks
        until the stop event is set.
        """
        self._init_kafka()
        retry_task = asyncio.create_task(self._retry_loop())
        # PLAN-0093 Wave A-2 (F-LOG-003): launch the broker connectivity probe
        # in parallel with the poll loop.  Cancelled in ``finally`` so the
        # task does not leak on shutdown.
        probe_task = asyncio.create_task(self._connectivity_probe_loop())

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

        def _on_probe_task_done(task: asyncio.Task[None]) -> None:  # type: ignore[type-arg]
            # The probe deliberately calls sys.exit(2) on sustained failure
            # (handled by SystemExit propagating up to the event loop).  An
            # un-cancelled task with an unhandled non-SystemExit exception
            # would otherwise be silently swallowed — log it loud so the
            # operator sees that connectivity monitoring is gone.
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.critical("connectivity_probe_crashed", exc_info=exc)

        probe_task.add_done_callback(_on_probe_task_done)

        try:
            loop = asyncio.get_event_loop()
            while not self._stop_event.is_set():
                # DEF-032: opt-in backpressure check before each poll.
                # Short-circuits to a single attribute check when no policy
                # is configured; otherwise rate-limits to once per
                # ``check_interval_seconds`` so the cost is negligible.
                self._maybe_apply_backpressure()
                # BP-700: a transient broker blip (connection setup timeout,
                # transport failure, coordinator unavailable) must trigger a
                # bounded-backoff RECONNECT and resume — NOT a silent terminal
                # stop.  ``poll`` itself rarely raises (it returns an error
                # message), but ``_init_kafka`` after a reset, the executor hop,
                # or a wedged client CAN raise; classify and reconnect here so a
                # broker hiccup can never again kill the loop.  The connectivity
                # probe remains the independent last-resort force-exit.
                # A prior reconnect could not rebuild the consumer — retry the
                # bounded-backoff reconnect before polling again.
                if self._consumer is None and not await self._reconnect_with_backoff():
                    continue
                try:
                    msg = await loop.run_in_executor(
                        None,
                        self._consumer.poll,
                        self._config.poll_timeout_seconds,
                    )
                except Exception as poll_exc:
                    if self._is_transient_broker_error(poll_exc):
                        logger.warning(
                            "kafka_poll_transient_error_reconnecting",
                            group_id=self._config.group_id,
                            error=str(poll_exc),
                            error_type=type(poll_exc).__name__,
                        )
                        await self._reconnect_with_backoff()
                    else:
                        logger.exception("kafka_poll_unexpected_error", error=str(poll_exc))
                    continue
                # Healthy poll cycle (idle OR message) → refresh the liveness
                # heartbeat and reset the reconnect counter so an isolated blip
                # does not erode the terminal-stop budget over the consumer's
                # lifetime.
                self._record_progress()
                self._reconnect_attempts = 0
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
                    # BP-NEW asyncpg pool resilience (Final-QA-3-deep):
                    # When Postgres restarts (operator-initiated or otherwise),
                    # every connection in SQLAlchemy's pool becomes stale.
                    # ``pool_pre_ping=True`` covers most cases by re-validating
                    # checked-out connections, but the pre-ping itself can
                    # raise ``asyncpg.ConnectionDoesNotExistError`` /
                    # ``InterfaceError`` on the very first attempt after the
                    # restart (the underlying socket is half-closed; the next
                    # ROUND-TRIP is what surfaces the failure).  Without this
                    # wrapper the message handler exception path dead-letters
                    # the message and the consumer can crash before the pool
                    # has a chance to recycle.  One retry with a brief sleep
                    # gives the pool a chance to discard the stale connection
                    # and hand out a fresh one — the second attempt either
                    # succeeds or falls through to the normal error path.
                    try:
                        await self._handle_message(msg)
                    except _ASYNCPG_CONN_ERRORS as conn_exc:
                        logger.warning(
                            "consumer_db_connection_lost_retrying",
                            error=str(conn_exc),
                            error_type=type(conn_exc).__name__,
                            topic=msg.topic(),
                            partition=msg.partition(),
                            offset=msg.offset(),
                        )
                        # Give the pool a moment to evict the dead connection
                        # before the second attempt — `pool_pre_ping` will
                        # validate the next checkout and the pool will refill
                        # with a live socket on demand.
                        await asyncio.sleep(1.0)
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
            # PLAN-0093 Wave A-2: cancel the probe last so a graceful shutdown
            # never produces a spurious connectivity-failure log.
            probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await probe_task
            self._shutdown_kafka()

    def stop(self) -> None:
        """Signal the consumer to stop after the current message is processed."""
        self._stop_event.set()
        logger.info("kafka_consumer_stop_requested", group_id=self._config.group_id)


# Import here to avoid circular imports at module top
from messaging.kafka.consumer.errors import MalformedDataError  # noqa: E402
