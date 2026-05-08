"""Valkey-backed idempotency mixin for BaseKafkaConsumer subclasses.

This module provides :class:`ValkeyDedupMixin`, a concrete mixin that
satisfies the ``is_duplicate`` / ``mark_processed`` abstract interface defined
by :class:`~messaging.kafka.consumer.base.BaseKafkaConsumer` using Valkey as
the dedup store.

Usage::

    from messaging.kafka.consumer.base import BaseKafkaConsumer, ConsumerConfig
    from messaging.kafka.consumer.dedup import ValkeyDedupMixin
    from messaging.valkey.client import ValkeyClient

    class ArticleRawConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
        def __init__(self, config: ConsumerConfig, valkey: ValkeyClient) -> None:
            super().__init__(config)
            self._dedup_client = valkey
            self._dedup_prefix = "content_ingestion:dedup:article_raw"
            # _dedup_ttl_seconds defaults to 86400 (24 h)

See STANDARDS.md §3.11 and R9 for the rule that mandates this mixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from messaging.valkey.client import ValkeyClient

logger = get_logger(__name__)

# D-001: Prometheus counter for Valkey-error fail-open events.
# Incremented every time is_duplicate() catches a Valkey error and returns
# False (at-least-once fallback).  Silent fallbacks are invisible without this
# counter; dashboards should alert when this value spikes.
try:
    import prometheus_client as _prom

    _dedup_valkey_fallback_total = _prom.Counter(
        "messaging_dedup_valkey_fallback_total",
        "Number of times dedup check failed open due to Valkey error",
        ["consumer_prefix"],
    )
    # F-DS011: Parallel counter for mark_processed failures (write side).
    # is_duplicate failures are already tracked; without this counter, a
    # sustained Valkey write outage is invisible on dashboards — dedup keys
    # are never written, so every re-delivery of the same event_id passes
    # the duplicate check and triggers double-processing.
    _dedup_mark_failed_total = _prom.Counter(
        "messaging_dedup_mark_failed_total",
        "Number of times mark_processed() failed to write to Valkey",
        ["consumer_prefix"],
    )
except ImportError:
    _dedup_valkey_fallback_total = None  # type: ignore[assignment]
    _dedup_mark_failed_total = None  # type: ignore[assignment]


class ValkeyDedupMixin:
    """Standard idempotency mixin for BaseKafkaConsumer subclasses.

    Implements ``is_duplicate`` and ``mark_processed`` against a Valkey set
    with a 24h TTL by default.  On Valkey failure, returns ``False`` from
    ``is_duplicate`` (at-least-once fallback) and silently swallows errors
    from ``mark_processed``.

    Fallback safety contract
    ------------------------
    The at-least-once fallback is only safe when the consumer's downstream
    writes are idempotent — i.e. they use deterministic IDs (``uuid5_from_parts``
    or equivalent) **or** ``INSERT … ON CONFLICT DO NOTHING``.  Subclasses
    MUST document which strategy they rely on.

    Class attributes
    ----------------
    _dedup_client : ValkeyClient | None
        Injected in the subclass ``__init__``.  ``None`` disables dedup
        (at-least-once mode only — safe only when downstream writes are
        idempotent; see above).

    _dedup_prefix : str
        Key namespace, e.g. ``"nlp:dedup:article_consumer"``.  Should be
        unique per consumer class so keys from different consumers do not
        collide.  No default — subclasses must set it explicitly.

    _dedup_ttl_seconds : int
        TTL applied to every dedup key.  Defaults to 86 400 (24 hours).
        Override in the subclass to tune the dedup window.

    Cross-reference
    ---------------
    R9 (RULES.md / STANDARDS.md §12): no cross-service DB access — Valkey is
    the correct shared-state store for dedup keys, NOT a PostgreSQL table.
    STANDARDS.md §3.11: all consumers MUST use this mixin.

    WARNING (multi-tenant): dedup keys are global per consumer group, not per tenant.
    For tenant-isolated deployments, subclasses should override is_duplicate() /
    mark_processed() to incorporate tenant_id into the key:
    ``f"{prefix}:{tenant_id}:{event_id}"``.
    This is NOT a current concern (single-tenant deployment) but IS a future footgun
    if the platform migrates to multi-tenant without updating these keys.  (S-002)
    """

    # Subclasses inject this in __init__.  None ⟹ at-least-once fallback.
    _dedup_client: ValkeyClient | None = None

    # Namespace prefix for all dedup keys produced by this consumer.
    # No default — subclasses MUST declare this as a class- or instance-level
    # attribute so that key collisions between consumer classes are impossible.
    _dedup_prefix: str

    # D-003: TTL in seconds applied to every dedup key (default: 24 hours).
    # Must exceed the maximum expected consumer pause duration.
    #
    # WARNING (D-003): If consumers are paused longer than this TTL (e.g. a 25h
    # maintenance window), Kafka re-delivery of the same event_id will NOT be
    # detected as a duplicate — the key will have expired.  The Kafka topic
    # retention for ``nlp.article.enriched.v1`` is 7 days (604800s).  If consumers
    # are expected to be paused for more than 24h, increase this value to match
    # the topic retention.  Increase to 604800 for parity with the 7-day retention.
    _dedup_ttl_seconds: ClassVar[int] = 86400

    async def is_duplicate(self, event_id: str) -> bool:
        """Return ``True`` if *event_id* was already processed.

        Checks the Valkey key ``{_dedup_prefix}:{event_id}``.

        Failure semantics
        -----------------
        - ``_dedup_client is None`` → ``False`` (at-least-once, safe only when
          downstream writes are idempotent — see class docstring).
        - Valkey unreachable / command error → logs
          ``dedup.valkey_check_failed`` at WARNING level and returns ``False``.

        Args:
            event_id: Opaque event identifier from the Kafka message envelope.
                      Must not contain PII — it is stored as-is in Valkey.

        Returns:
            ``True`` if the key exists (already processed), ``False`` otherwise.
        """
        if self._dedup_client is None:
            return False
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            return bool(await self._dedup_client.exists(key))
        except Exception:
            # D-001: increment fallback counter before logging so the metric is
            # always recorded even if the logger call raises (defensive ordering).
            if _dedup_valkey_fallback_total is not None:
                _dedup_valkey_fallback_total.labels(consumer_prefix=self._dedup_prefix).inc()
            logger.warning(  # type: ignore[no-any-return]
                "dedup.valkey_check_failed",
                event_id=event_id,
                prefix=self._dedup_prefix,
                exc_info=True,
            )
            return False  # at-least-once: prefer reprocessing over silent drop

    async def mark_processed(self, event_id: str) -> None:
        """Record *event_id* as successfully processed with a TTL.

        Sets the Valkey key ``{_dedup_prefix}:{event_id}`` to ``"1"`` with an
        expiry of ``_dedup_ttl_seconds`` (default 24 hours).

        Failure semantics
        -----------------
        - ``_dedup_client is None`` → no-op.
        - Valkey unreachable / command error → logs
          ``dedup.valkey_mark_failed`` at WARNING level and returns silently.
          The mark failure is non-fatal: the consumer already committed the DB
          transaction, so the downstream write is durable.  A repeated delivery
          will simply reprocess the message — idempotent writes ensure safety.

        Args:
            event_id: Opaque event identifier from the Kafka message envelope.
        """
        if self._dedup_client is None:
            return
        key = f"{self._dedup_prefix}:{event_id}"
        try:
            await self._dedup_client.set(key, "1", ex=self._dedup_ttl_seconds)
        except Exception:
            # F-DS011: increment mark-failed counter before logging so the metric is
            # always recorded even if the logger call raises (defensive ordering,
            # same convention as the is_duplicate fallback counter above).
            if _dedup_mark_failed_total is not None:
                _dedup_mark_failed_total.labels(consumer_prefix=self._dedup_prefix).inc()
            logger.warning(  # type: ignore[no-any-return]
                "dedup.valkey_mark_failed",
                event_id=event_id,
                prefix=self._dedup_prefix,
                exc_info=True,
            )
