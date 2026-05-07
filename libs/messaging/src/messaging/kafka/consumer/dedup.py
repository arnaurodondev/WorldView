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
    """

    # Subclasses inject this in __init__.  None ⟹ at-least-once fallback.
    _dedup_client: ValkeyClient | None = None

    # Namespace prefix for all dedup keys produced by this consumer.
    # No default — subclasses MUST declare this as a class- or instance-level
    # attribute so that key collisions between consumer classes are impossible.
    _dedup_prefix: str

    # TTL in seconds applied to every dedup key (default: 24 hours).
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
            logger.warning(  # type: ignore[no-any-return]
                "dedup.valkey_mark_failed",
                event_id=event_id,
                prefix=self._dedup_prefix,
                exc_info=True,
            )
