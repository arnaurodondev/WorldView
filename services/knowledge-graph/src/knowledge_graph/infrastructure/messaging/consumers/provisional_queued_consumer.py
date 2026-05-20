"""ProvisionalQueuedConsumer — hot-path enrichment for provisional entities.

Consumes ``entity.provisional.queued.v1`` events emitted by S6
UnresolvedResolutionWorker when a new provisional entity is inserted into
``provisional_entity_queue``.

Processing per message:
  1. SELECT queue_id row FOR UPDATE SKIP LOCKED (idempotency — only one consumer
     instance acquires the lock).
  2. If row missing or status != 'pending': skip (already processed or stale).
  3. UPDATE status='processing', commit → release session (ARCH-003).
  4. Call core.extract_entity_profile() — LLM call, no session held.
  5. Call core.compute_embedding() — HTTP call, no session held.
  6. New session: core.persist_enrichment() + UPDATE status='resolved', commit.
  7. Emit entity.dirtied.v1 after commit (fire-and-forget).
  8. On any failure: new session, core.apply_retry_transition(), commit.

This consumer is intentionally separate from ProvisionalEnrichmentWorker
(polling sweep) — each has its own consumer-group offset and can be scaled
independently.  The worker provides the catch-up guarantee; this consumer
provides the <100ms hot path.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from knowledge_graph.infrastructure.metrics.prometheus import s7_provisional_queue_stuck_total
from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core
from messaging.kafka.consumer.base import (  # type: ignore[import-untyped]
    BaseKafkaConsumer,
    ConsumerConfig,
    FailureInfo,
    UnitOfWorkProtocol,
)
from messaging.kafka.consumer.dedup import ValkeyDedupMixin  # type: ignore[import-untyped]
from messaging.kafka.schema_paths import get_schema_path  # type: ignore[import-untyped]
from messaging.topics import (  # type: ignore[import-untyped]
    ENTITY_DIRTIED as _ENTITY_DIRTIED_TOPIC,
)
from messaging.topics import (
    ENTITY_PROVISIONAL_QUEUED as _PROVISIONAL_QUEUED_TOPIC,
)
from observability import get_logger  # type: ignore[import-untyped]

_PROVISIONAL_QUEUED_SCHEMA_PATH = get_schema_path("entity.provisional.queued.v1.avsc")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

_DEFAULT_MAX_RETRIES = 5


class DirectProducerProtocol(Protocol):
    """Structural type for direct Kafka producer (entity.dirtied.v1)."""

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None: ...


class _NoOpUoW:
    async def __aenter__(self) -> _NoOpUoW:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


class ProvisionalQueuedConsumer(ValkeyDedupMixin, BaseKafkaConsumer[None]):
    """Consumes entity.provisional.queued.v1 and triggers immediate enrichment.

    Args:
    ----
        config:           Consumer configuration (topic, group, bootstrap).
        session_factory:  async_sessionmaker for intelligence_db.
        llm_client:       FallbackChainClient for extraction + embedding.
        embed_model_id:   Embedding model ID (must match the KG scheduler's
                          embedding model to stay in the same vector space).
        max_retries:      Max LLM failures before row transitions to 'failed'.
        entity_dirtied_topic: Topic for entity.dirtied.v1 hot-path emit.
        direct_producer:  Optional Kafka producer for entity.dirtied.v1.
        dedup_client:     Optional Valkey client for event deduplication.

    """

    def __init__(
        self,
        config: ConsumerConfig,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: Any,
        *,
        embed_model_id: str = "bge-large:latest",
        max_retries: int = _DEFAULT_MAX_RETRIES,
        entity_dirtied_topic: str = _ENTITY_DIRTIED_TOPIC,
        direct_producer: DirectProducerProtocol | None = None,
        dedup_client: Any | None = None,
        # DEF-033 / BP-396 — exponential backoff parameters.  Defaults match
        # the canonical ``core.apply_retry_transition`` defaults so existing
        # call sites that did not pass these are backward-compatible.  In
        # production the factory in ``provisional_queued_consumer_main.py``
        # threads ``settings.provisional_enrichment_{base,max}_retry_minutes``
        # through so the hot-path consumer honours the same env-var-driven
        # window as the polling worker — without this fix the hot path would
        # silently use the defaults regardless of ops configuration.
        base_retry_minutes: int = 2,
        max_retry_minutes: int = 1440,
        # PRD-0089 F2 §4.3: optional S2 lookup port. The hot-path consumer
        # forwards it to ``core.persist_enrichment`` so tradable provisional
        # entities anchor on the existing instrument_id (M-017). When the
        # port is None the consumer behaves exactly as before — tradable
        # rows are minted with a fresh UUID. The scheduler wiring passes the
        # MarketDataLookupAdapter when an internal JWT signer is configured.
        market_data_lookup: Any | None = None,
    ) -> None:
        super().__init__(config)
        self._sf = session_factory
        self._llm = llm_client
        self._embed_model_id = embed_model_id
        self._max_retries = max_retries
        self._dirtied_topic = entity_dirtied_topic
        self._producer = direct_producer
        self._dedup_client = dedup_client
        self._dedup_prefix = f"kg:dedup:{config.group_id}"
        # Stored as private attrs so the ``_retry`` / ``_fail_safe_retry``
        # helpers can read them without re-plumbing every call site.  These
        # become arguments to ``core.apply_retry_transition``.
        self._base_retry_minutes = base_retry_minutes
        self._max_retry_minutes = max_retry_minutes
        # F2 §4.3 — stash the lookup port for forwarding into persist_enrichment.
        self._market_data_lookup = market_data_lookup
        if direct_producer is None:
            logger.warning(  # type: ignore[no-any-return]
                "provisional_queued_consumer_no_producer",
                message="direct_producer is None — entity.dirtied.v1 will not be emitted after enrichment",
            )

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    async def process_message(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str],
    ) -> None:
        """Enrich the provisional entity referenced in the event."""
        from sqlalchemy import text

        queue_id_raw: str | None = value.get("queue_id")
        if not queue_id_raw:
            logger.warning(  # type: ignore[no-any-return]
                "provisional_queued_missing_queue_id",
                payload=value,
            )
            return

        queue_id = UUID(queue_id_raw)

        # ── Step 1: acquire row lock, check status ──────────────────────────
        mention_text: str | None = None
        mention_class: str | None = None
        context_snippet: str = ""
        retry_count: int = 0

        # DEF-033 / Wave A-4 QA fix: filter out rows whose exponential-backoff
        # window has not yet elapsed.  Without this guard a Kafka redelivery
        # immediately after a failed attempt would pull the same row and
        # short-circuit the backoff that we just persisted.  Pre-Wave-A-4 rows
        # have ``next_retry_at IS NULL`` and remain immediately eligible for
        # backward compatibility (no backfill required).  ``:now`` is bound
        # from ``common.time.utc_now()`` so tests can drive the comparison
        # deterministically by patching ``common.time``.
        from common.time import utc_now as _utc_now  # type: ignore[import-untyped]

        async with self._sf() as session:
            result = await session.execute(
                text("""
SELECT mention_text, mention_class, context_snippet, retry_count
FROM provisional_entity_queue
WHERE queue_id = :queue_id
  AND status = 'pending'
  AND (next_retry_at IS NULL OR next_retry_at <= CAST(:now AS TIMESTAMPTZ))
FOR UPDATE SKIP LOCKED
"""),
                {"queue_id": str(queue_id), "now": _utc_now()},
            )
            row = result.fetchone()

            if row is None:
                # Either already processing/resolved or another consumer grabbed
                # the lock first — either way nothing to do.
                logger.debug(  # type: ignore[no-any-return]
                    "provisional_queued_skip_not_pending",
                    queue_id=str(queue_id),
                )
                return

            mention_text = str(row[0])
            mention_class = str(row[1])
            context_snippet = str(row[2]) if row[2] else ""
            retry_count = int(row[3]) if row[3] is not None else 0

            # ── Step 2: mark processing before releasing lock ────────────────
            await session.execute(
                text("""
UPDATE provisional_entity_queue
SET status = 'processing'
WHERE queue_id = :queue_id
"""),
                {"queue_id": str(queue_id)},
            )
            await session.commit()
        # Session released — no connection held during LLM calls (ARCH-003).

        # ── Step 3: LLM extraction + embedding (no session) ─────────────────
        profile: dict[str, Any] | None = None
        embedding: list[float] | None = None
        entity_id: UUID | None = None

        try:
            profile = await core.extract_entity_profile(self._llm, mention_text, mention_class or "", context_snippet)
            if profile is not None:
                canonical_name = profile.get("canonical_name") or mention_text
                if canonical_name:
                    embedding = await core.compute_embedding(self._llm, None, canonical_name, self._embed_model_id)
        except Exception as exc:
            logger.error(  # type: ignore[no-any-return]
                "provisional_queued_llm_error",
                queue_id=str(queue_id),
                error=str(exc),
            )

        # ── Step 4: persist results ──────────────────────────────────────────
        if profile is not None:
            try:
                async with self._sf() as session:
                    entity_id = await core.persist_enrichment(
                        session=session,
                        queue_id=queue_id,
                        mention_text=mention_text,
                        profile=profile,
                        embedding=embedding,
                        embed_model_id=self._embed_model_id,
                        # F2 §4.3 — share the same M-017 anchoring path as the
                        # polling worker; returns None when S2 has no row yet
                        # so the existing _retry helper applies the deferral.
                        market_data_lookup=self._market_data_lookup,
                    )
                    if entity_id:
                        await session.execute(
                            text("""
UPDATE provisional_entity_queue
SET status = 'resolved', assigned_entity_id = :entity_id, resolved_at = now()
WHERE queue_id = :queue_id
"""),
                            {"entity_id": str(entity_id), "queue_id": str(queue_id)},
                        )
                    else:
                        # DEF-033 / BP-396: forward the configured backoff window
                        # from the consumer instance so the SQL CASE writes a
                        # ``next_retry_at`` consistent with operator config.
                        await _retry(
                            session,
                            queue_id,
                            retry_count,
                            self._max_retries,
                            base_retry_minutes=self._base_retry_minutes,
                            max_retry_minutes=self._max_retry_minutes,
                        )
                    await session.commit()
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "provisional_queued_persist_error",
                    queue_id=str(queue_id),
                    error=str(exc),
                )
                entity_id = None
                await _fail_safe_retry(
                    self._sf,
                    queue_id,
                    retry_count,
                    self._max_retries,
                    base_retry_minutes=self._base_retry_minutes,
                    max_retry_minutes=self._max_retry_minutes,
                )
        else:
            await _fail_safe_retry(
                self._sf,
                queue_id,
                retry_count,
                self._max_retries,
                base_retry_minutes=self._base_retry_minutes,
                max_retry_minutes=self._max_retry_minutes,
            )

        # ── Step 5: emit entity.dirtied.v1 after successful commit ──────────
        if entity_id and self._producer:
            try:
                self._producer.produce_bytes(
                    topic=self._dirtied_topic,
                    key=str(entity_id).encode(),
                    value=core._build_dirtied_event(entity_id),
                )
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "provisional_queued_dirtied_emit_failed",
                    entity_id=str(entity_id),
                    exc_info=True,
                )

        logger.info(  # type: ignore[no-any-return]
            "provisional_queued_processed",
            queue_id=str(queue_id),
            entity_id=str(entity_id) if entity_id else None,
        )

    async def process_message_from_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "provisional_queued_consumer_retry_not_supported",
            event_id=failure.event_id,
        )

    # ------------------------------------------------------------------
    # Failure tracking
    # ------------------------------------------------------------------

    async def store_failure(self, failure: FailureInfo[None]) -> None:  # type: ignore[override]
        logger.error(  # type: ignore[no-any-return]
            "provisional_queued_consumer_failure",
            event_id=failure.event_id,
            error=str(failure.last_error),
        )

    async def update_failure(self, failure: FailureInfo[None]) -> None:
        logger.warning(  # type: ignore[no-any-return]
            "provisional_queued_consumer_failure_retry",
            event_id=failure.event_id,
            attempt=failure.attempt,
        )

    async def _dead_letter_impl(self, failure: FailureInfo[None]) -> None:
        logger.error(  # type: ignore[no-any-return]
            "provisional_queued_consumer_dead_lettered",
            event_id=failure.event_id,
            attempts=failure.attempt,
            error=str(failure.last_error),
        )

    async def get_pending_retries(self) -> list[FailureInfo[None]]:
        return []

    async def get_unit_of_work(self) -> UnitOfWorkProtocol:
        return _NoOpUoW()  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def deserialize_value(self, raw: bytes, schema_path: str | None = None) -> dict[str, Any]:
        """Decode entity.provisional.queued.v1 events from Confluent-Avro wire format.

        PLAN-0062: this consumer enforces the platform principle that all
        Kafka contracts use Avro (no JSON).  Producer side is
        ``UnresolvedResolutionWorker`` in nlp-pipeline which uses
        ``serialize_confluent_avro`` against the same schema file.

        Falls back to JSON parsing only when the payload lacks the Confluent
        magic byte (0x00) — useful for legacy replays during the migration
        window where some pre-PLAN-0062 messages may still be in the topic.
        """
        from messaging.kafka.serialization_utils import deserialize_confluent_avro  # type: ignore[import-untyped]

        path = schema_path or _PROVISIONAL_QUEUED_SCHEMA_PATH
        if raw and raw[:1] == b"\x00":
            return deserialize_confluent_avro(path, raw)  # type: ignore[no-any-return]
        # Legacy JSON fallback — logged so we can quantify residual JSON
        # traffic and remove this branch once the migration window closes.
        logger.warning(  # type: ignore[no-any-return]
            "provisional_queued_legacy_json_payload",
            message="entity.provisional.queued.v1 message lacks Confluent magic byte; using JSON fallback",
        )
        return json.loads(raw)  # type: ignore[no-any-return]

    def get_schema_path(self, topic: str) -> str | None:
        if topic == _PROVISIONAL_QUEUED_TOPIC:
            return _PROVISIONAL_QUEUED_SCHEMA_PATH
        return None

    def extract_event_id(self, value: dict[str, Any]) -> str:
        return str(value.get("event_id", ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _retry(
    session: AsyncSession,
    queue_id: UUID,
    retry_count: int,
    max_retries: int,
    *,
    base_retry_minutes: int = 2,
    max_retry_minutes: int = 1440,
) -> None:
    """Apply retry transition within an already-open session.

    ``retry_count`` is retained in the signature for source-compatibility with
    earlier call sites; the SQL now reads the count atomically from the DB.

    DEF-033 (Wave A-4 QA fix): forward the configured backoff window through
    to ``core.apply_retry_transition`` so the SQL CASE writes ``next_retry_at``
    consistent with the consumer's settings.  Without this, the hot path
    silently used the function defaults regardless of ops configuration.
    """
    del retry_count
    await core.apply_retry_transition(
        session,
        queue_id,
        max_retries,
        base_retry_minutes=base_retry_minutes,
        max_retry_minutes=max_retry_minutes,
    )


async def _fail_safe_retry(
    session_factory: async_sessionmaker[AsyncSession],
    queue_id: UUID,
    retry_count: int,
    max_retries: int,
    *,
    base_retry_minutes: int = 2,
    max_retry_minutes: int = 1440,
) -> None:
    """Apply retry transition in a fresh session (used on persist failure).

    ``retry_count`` is retained for source-compatibility — see ``_retry``.

    DEF-033 (Wave A-4 QA fix): forward the backoff window — see ``_retry``
    docstring for the full rationale.
    """
    del retry_count
    try:
        async with session_factory() as session:
            await core.apply_retry_transition(
                session,
                queue_id,
                max_retries,
                base_retry_minutes=base_retry_minutes,
                max_retry_minutes=max_retry_minutes,
            )
            await session.commit()
    except Exception:
        s7_provisional_queue_stuck_total.inc()
        logger.error(  # type: ignore[no-any-return]
            "provisional_queued_retry_transition_failed",
            queue_id=str(queue_id),
            exc_info=True,
        )
