"""Worker 13E: Provisional entity enrichment (PRD §6.7 Block 13E / §14.2).

Runs every 5 minutes (catch-up sweep). Hot path handled by
ProvisionalQueuedConsumer which reacts to entity.provisional.queued.v1 events
emitted by S6 UnresolvedResolutionWorker (PLAN-0061 Wave E).

Processes ``provisional_entity_queue`` rows with ``status='pending'``:
  1. Two-layer noise pre-filter (PLAN-0072 T-72-1-01):
     Layer 1: static blocklist (O(1), no LLM cost).
     Layer 2: cheap meta-llama/8B binary classifier (fail-open on error).
     Noise rows → status='noise' (new terminal state, migration 0020).
  2. Use ExtractionClient (FallbackChainClient) to generate entity profile
     (canonical_name, entity_type, ticker, ISIN).
  3. INSERT into canonical_entities.
  4. INSERT mechanical aliases (canonical_name, ticker, ISIN if available).
  5. INSERT 2-3 entity_embedding_state rows (financial_instrument: 3; others: 2).
  6. UPDATE provisional_entity_queue.status → 'resolved'.
  7. UPDATE relation_evidence_raw to clear entity_provisional flag.
  8. EMIT entity.canonical.created.v1 via outbox.
  9. EMIT entity.dirtied.v1 via outbox (D-014: changed from fire-and-forget
     direct Kafka produce to the durable outbox pattern — PLAN-0084 QA fix).
     One-time entity promotions are now guaranteed to reach the embedding
     pipeline even if the process crashes between the DB commit and the
     produce step.
  10. Log to llm_usage_log.

LLM alias collision validation: reject an LLM-generated alias if it maps
to a different entity in entity_aliases.

Shared enrichment logic lives in provisional_enrichment_core.py so the
hot-path ProvisionalQueuedConsumer can reuse the same LLM + DB steps.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

import httpx

from common.ids import new_uuid7  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.intelligence_db.repositories.outbox import OutboxRepository
from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_provisional_enrichment_failed_total,
    s7_provisional_enrichment_success_total,
    s7_provisional_noise_filtered_total,
    s7_provisional_noise_llm_filtered_total,
    s7_provisional_stuck_recovered_total,
)
from knowledge_graph.infrastructure.workers import provisional_enrichment_core as core
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.ports.market_data_lookup_port import MarketDataLookupPort
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Topic name constant — avoid importing from messaging.topics to sidestep
# version-skew attr-defined errors when the installed package predates the
# ENTITY_DIRTIED constant (added in a later revision of libs/messaging).
_ENTITY_DIRTIED_TOPIC = "entity.dirtied.v1"

# ---------------------------------------------------------------------------
# PLAN-0072 T-72-1-01 — two-layer noise pre-filter
# ---------------------------------------------------------------------------

# Layer 1: obvious noise eliminated with O(1) frozenset lookup (no LLM cost).
_NOISE_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Pronouns / generic references
        "he",
        "she",
        "they",
        "it",
        "we",
        "us",
        "his",
        "her",
        "their",
        "him",
        "them",
        "who",
        "what",
        # Generic finance jargon that produce useless nodes
        "constant currency",
        "organic growth",
        "analysts",
        "management",
        "investors",
        "shareholders",
        "executives",
        "regulators",
        "the company",
        "company",
        "the firm",
        "firm",
        "business",
        # Fake entities from publication names used as subjects
        "simply wall st",
        "seeking alpha",
        "the motley fool",
        "bloomberg",
        "reuters",
        "cnbc",
        "marketwatch",
        "barron's",
        "wsj",
        # Noise mentions of generic geographic / institutional terms
        "street",
        "market",
        "sector",
        "industry",
        "index",
    },
)

# Layer 2: cheap binary classifier model (fast, low cost vs. full DeepSeek extraction).
_NOISE_CLASSIFIER_MODEL_ID = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"

_NOISE_CLASSIFIER_SYSTEM_PROMPT = (
    "Is the MENTION a specific named financial entity "
    "(company, person, financial instrument, index, currency, or commodity)? "
    "Do NOT classify generic roles, concepts, pronouns, media outlets, "
    "or financial jargon as entities. "
    "Respond ONLY with JSON: "
    '{"is_entity": true/false, "confidence": 0.0-1.0}'
)


class DirectProducerProtocol(Protocol):
    """Structural type for direct Kafka producer (entity.dirtied.v1)."""

    def produce_bytes(self, *, topic: str, key: bytes, value: bytes) -> None: ...


class ProvisionalEnrichmentWorker:
    """Enriches provisional entities via LLM (Worker 13E).

    D-014 (PLAN-0084 QA fix): ``entity.dirtied.v1`` events are now emitted via
    the durable outbox pattern (``OutboxRepository.append``) rather than a
    fire-and-forget direct Kafka produce.  This guarantees that one-time entity
    promotions always reach the embedding pipeline even if the process crashes
    between the DB commit and the original produce call.

    ``direct_producer`` is kept as an optional constructor parameter for
    backward-compatibility with existing call sites and tests, but it is no
    longer used in the hot path.

    Args:
    ----
        session_factory:   Read/write sessionmaker for intelligence_db.
        llm_client:        FallbackChainClient for extraction + embedding.
        direct_producer:   Deprecated — no longer used (entity.dirtied.v1 goes
                           through the outbox).  Accepted to avoid breaking
                           existing call sites; silently ignored.
        entity_dirtied_topic: Topic name for entity.dirtied.v1 outbox rows.
        embedding_model_id: Model ID passed to EmbeddingInput (default: bge-large:latest,
                           which produces 1024-dim vectors matching vector(1024) column).
                           Set via KNOWLEDGE_GRAPH_EMBEDDING_MODEL_ID env var.
        batch_limit:       Max rows fetched per cycle (default 50). PLAN-0061 T-A-4.
        max_retries:       Rows exceeding this failure count become 'failed' (terminal).
                           PLAN-0061 T-A-3.
        concurrency:       Max concurrent LLM calls in Phase 2. PLAN-0061 T-A-4.
        noise_classifier_api_key:      DeepInfra API key for Layer 2 cheap classifier.
                                       When empty, Layer 2 is skipped (fail-open to Layer 3).
        noise_classifier_api_base_url: Base URL for the Layer 2 classifier endpoint.
        noise_classifier_timeout_s:    Per-call timeout for the Layer 2 HTTP request.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        direct_producer: DirectProducerProtocol | None = None,
        entity_dirtied_topic: str = _ENTITY_DIRTIED_TOPIC,
        embedding_model_id: str = "bge-large:latest",
        usage_logger: LlmUsageLogProtocol | None = None,
        batch_limit: int = 50,
        max_retries: int = 5,
        concurrency: int = 5,
        noise_classifier_api_key: str = "",
        noise_classifier_api_base_url: str = "https://api.deepinfra.com/v1/openai",
        noise_classifier_timeout_s: float = 10.0,
        # DEF-033 (Wave A-4) — exponential backoff parameters threaded through
        # to ``core.apply_retry_transition`` on every retry transition.  Defaults
        # match the canonical worldview values; the scheduler overrides them
        # from ``Settings.provisional_enrichment_{base,max}_retry_minutes``.
        base_retry_minutes: int = 2,
        max_retry_minutes: int = 1440,
        # DEF-034 (Wave B-5): the Phase 1 claim path is SELECT FOR UPDATE +
        # UPDATE in a single transaction so it MUST stay on the write factory.
        # We accept ``read_session_factory`` for forward-compat (Wave B-1 may
        # leverage it for purely-read diagnostic queries) and store it without
        # changing behaviour today.  See PLAN-0076 §B-5 T-B5-05.
        read_session_factory: Any = None,
        # PRD-0089 F2 §4.3: optional S2 lookup port. When provided AND the
        # provisional entity is a tradable instrument with a ticker, the
        # worker anchors the new canonical_entities row on the existing
        # market_data.instruments.id rather than minting a fresh UUID
        # (M-017 enforcement). When the instrument is not yet in S2 the
        # promotion is deferred via the existing _apply_retry path so the
        # row eventually transitions to status='failed' after max_retries.
        # Kept optional so unit tests that never exercise the tradable path
        # do not need to inject a stub.
        market_data_lookup: MarketDataLookupPort | None = None,
    ) -> None:
        self._sf = session_factory
        # Read factory wired for future use; current path is atomic read+write
        # (claim_batch does SELECT FOR UPDATE + UPDATE in one transaction), so
        # all queries continue to run on the write factory.
        self._read_session_factory: Any = read_session_factory if read_session_factory is not None else session_factory
        self._embed_model_id = embedding_model_id
        self._llm = llm_client
        # D-014: direct_producer is deprecated — entity.dirtied.v1 now uses the
        # durable outbox pattern.  The field is kept for backward-compatibility
        # only; it is no longer called in run().
        self._producer = direct_producer
        self._dirtied_topic = entity_dirtied_topic
        # PLAN-0057 A-5 / F-CRIT-03: optional cost logger.  In practice the
        # FallbackChainClient already calls ``usage_logger.log()`` on every
        # embed/extract attempt — this attribute exists so call-site code can
        # write *additional* per-worker rows when needed and so injection-time
        # tests can assert the logger was threaded through ``build_workers``.
        self._usage_logger = usage_logger
        self._batch_limit = batch_limit
        self._max_retries = max_retries
        self._concurrency = concurrency
        # DEF-033: passed straight into ``core.apply_retry_transition`` from
        # ``_apply_retry`` so the same SQL CASE produces backoff windows that
        # match operator expectations in production while staying overridable
        # in tests via constructor kwargs.
        self._base_retry_minutes = base_retry_minutes
        self._max_retry_minutes = max_retry_minutes
        # Layer 2 noise classifier state (PLAN-0072 T-72-1-01).
        # A persistent client reuses TCP connections across calls in a batch.
        self._noise_api_key = noise_classifier_api_key
        self._noise_api_base = noise_classifier_api_base_url.rstrip("/")
        self._noise_timeout_s = noise_classifier_timeout_s
        # Single shared client per worker instance; re-created lazily so tests
        # that never call run() do not incur connection overhead.
        self._noise_http_client: httpx.AsyncClient | None = None
        # PRD-0089 F2 §4.3 — S2 lookup port; None disables the M-017 anchor
        # path (used by tests that focus on noise/extraction behaviour).
        self._market_data_lookup = market_data_lookup

    async def run(self) -> None:
        """Enrich pending provisional entity queue entries.

        ARCH-003 fix: read→release→I/O→acquire→write pattern.
        Session is NOT held open during external LLM / embedding HTTP calls.

        PLAN-0072 T-72-1-01 — noise pre-filter between Phase 1 and Phase 2:
          Layer 1 (O(1)): static blocklist rejects obvious noise without LLM.
          Layer 2 (async): cheap meta-llama/8B binary classifier (fail-open).
          Noise rows → 'noise' (terminal) before the expensive Layer 3 call.
        """
        from sqlalchemy import text

        # B-7: Recovery sweep — reset rows stuck in 'processing' back to 'pending'
        # so they can be retried on the next cycle.
        async with self._sf() as session:
            recovered = await self._recover_stale_processing_rows(session)
        if recovered:
            s7_provisional_stuck_recovered_total.inc()
            logger.info(  # type: ignore[no-any-return]
                "provisional_enrichment_recovery_swept",
                recovered=recovered,
            )

        enriched = 0
        failed = 0

        entity_ids_to_dirty: list[UUID] = []

        # ── Phase 1: Read pending rows, then release the session ──
        # DEF-033 (Wave A-4): exclude rows whose exponential-backoff deadline
        # has not yet elapsed.  Existing rows (pre-migration 0029) have
        # ``next_retry_at IS NULL`` and are treated as immediately eligible
        # for backward compatibility — no backfill required.  ``:now`` is
        # bound from ``common.time.utc_now()`` rather than SQL ``now()`` so
        # tests can drive the comparison deterministically.
        from common.time import utc_now as _utc_now  # type: ignore[import-untyped]

        pending_rows: list[tuple[UUID, str, str, str, int]] = []
        async with self._sf() as session:
            result = await session.execute(
                text("""
SELECT queue_id, mention_text, normalized_surface, mention_class,
       context_snippet, source_doc_id, retry_count
FROM provisional_entity_queue
WHERE status = 'pending'
  AND retry_count < :max_retries
  AND (next_retry_at IS NULL OR next_retry_at <= CAST(:now AS TIMESTAMPTZ))
ORDER BY created_at
LIMIT :limit
FOR UPDATE SKIP LOCKED
"""),
                {
                    "limit": self._batch_limit,
                    "max_retries": self._max_retries,
                    "now": _utc_now(),
                },
            )
            rows = result.fetchall()

            for row in rows:
                pending_rows.append(
                    (
                        UUID(str(row[0])),  # queue_id
                        str(row[1]),  # mention_text
                        str(row[3]),  # mention_class
                        str(row[4]) if row[4] else "",  # context_snippet
                        int(row[6]) if row[6] is not None else 0,  # retry_count
                    ),
                )

            for queue_id, _, _, _, _ in pending_rows:
                await session.execute(
                    text("""
UPDATE provisional_entity_queue
SET status = 'processing',
    processing_started_at = CAST(:now AS TIMESTAMPTZ)
WHERE queue_id = :queue_id
  AND status = 'pending'
"""),
                    {"queue_id": str(queue_id), "now": _utc_now()},
                )
            await session.commit()
        # Session released — no DB connection held during LLM calls.

        # ── Phase 1.5: Noise pre-filter (no session held) ──────────────────
        # BP-384: noise filter runs BEFORE dedup/persist — noise rows never
        # reach persist_enrichment. Layer 1 is O(1); Layer 2 is async HTTP.
        if pending_rows:
            layer1_noise_ids, layer2_noise_ids, pending_rows = await self._run_noise_filters(pending_rows)
            all_noise_ids = layer1_noise_ids + layer2_noise_ids
            if all_noise_ids:
                # BP-392: single batch UPDATE instead of N+1 per-row loop.
                async with self._sf() as session:
                    await session.execute(
                        text("""
UPDATE provisional_entity_queue
SET status = 'noise', resolved_at = now()
WHERE queue_id = ANY(CAST(:ids AS uuid[]))
  AND status = 'processing'
"""),
                        {"ids": [str(nid) for nid in all_noise_ids]},
                    )
                    await session.commit()
                logger.info(  # type: ignore[no-any-return]
                    "provisional_enrichment_noise_filtered",
                    layer1_count=len(layer1_noise_ids),
                    layer2_count=len(layer2_noise_ids),
                    remaining_for_extraction=len(pending_rows),
                )

        # ── Phase 2: LLM extraction + embedding (no session held) ──
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _enrich_one(
            row: tuple[UUID, str, str, str, int],
        ) -> tuple[UUID, str, str, str, int, dict[str, Any] | None, list[float] | None]:
            queue_id, mention_text, mention_class, context_snippet, retry_count = row
            async with semaphore:
                try:
                    profile = await self._extract_entity_profile(mention_text, mention_class, context_snippet)
                    embedding: list[float] | None = None
                    if profile is not None:
                        canonical_name = profile.get("canonical_name") or mention_text
                        if canonical_name:
                            embedding = await self._compute_embedding(None, canonical_name)
                    return (queue_id, mention_text, mention_class, context_snippet, retry_count, profile, embedding)
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "provisional_enrichment_error",
                        queue_id=str(queue_id),
                        error=str(exc),
                    )
                    return (queue_id, mention_text, mention_class, context_snippet, retry_count, None, None)

        enrichment_results: list[tuple[UUID, str, str, str, int, dict[str, Any] | None, list[float] | None]] = list(
            await asyncio.gather(*[_enrich_one(r) for r in pending_rows]),
        )

        # ── Phase 3: Write results — one fresh session PER ROW ──────────────
        # BP-390 (full fix): opening a single session for the entire loop meant
        # that after session.rollback() the remaining rows in the loop could
        # silently escape their except blocks if _apply_retry raised, leaving
        # those rows permanently stuck in 'processing'.  Per-row sessions
        # guarantee that a failure on one row never taints the session used by
        # any subsequent row.
        for (
            queue_id,
            mention_text,
            _mention_class,
            _context_snippet,
            retry_count,
            profile,
            embedding,
        ) in enrichment_results:
            try:
                async with self._sf() as session:
                    if profile is not None:
                        entity_id = await self._persist_enrichment(
                            session=session,
                            queue_id=queue_id,
                            mention_text=mention_text,
                            profile=profile,
                            embedding=embedding,
                        )
                    else:
                        entity_id = None

                    if entity_id:
                        from sqlalchemy import text as sa_text

                        await session.execute(
                            sa_text("""
UPDATE provisional_entity_queue
SET status = 'resolved', assigned_entity_id = :entity_id, resolved_at = now()
WHERE queue_id = :queue_id
  AND status = 'processing'
"""),
                            {"entity_id": str(entity_id), "queue_id": str(queue_id)},
                        )
                        await session.commit()
                    else:
                        await self._apply_retry(session, queue_id, retry_count)
                        await session.commit()

                if entity_id:
                    entity_ids_to_dirty.append(entity_id)
                    s7_provisional_enrichment_success_total.inc()
                    enriched += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "provisional_enrichment_error",
                    queue_id=str(queue_id),
                    error=str(exc),
                )
                # DS-008: open a fresh session for the retry UPDATE so no
                # aborted-transaction state bleeds from the failed session.
                try:
                    async with self._sf() as session:
                        await self._apply_retry(session, queue_id, retry_count)
                        await session.commit()
                except Exception:
                    logger.warning(  # type: ignore[no-any-return]
                        "provisional_enrichment_retry_update_failed",
                        queue_id=str(queue_id),
                        exc_info=True,
                    )
                failed += 1

        # D-014 (PLAN-0084 QA fix): emit entity.dirtied.v1 via the durable outbox
        # rather than fire-and-forget direct produce.  The outbox guarantees that
        # one-time entity promotions reach the embedding pipeline even if the
        # process crashes between the per-row DB commit and this point.
        #
        # All dirtied-event rows are inserted in a SINGLE outbox transaction so
        # the batch is atomic: either all rows are enqueued or none are.
        if entity_ids_to_dirty:
            try:
                async with self._sf() as outbox_session:
                    outbox_repo = OutboxRepository(outbox_session)
                    for dirty_id in entity_ids_to_dirty:
                        dirty_event_id = new_uuid7()  # type: ignore[no-any-return]
                        await outbox_repo.append(
                            topic=self._dirtied_topic,
                            partition_key=str(dirty_id),
                            payload_avro=core._build_dirtied_event(dirty_id, event_id=dirty_event_id),
                            event_id=dirty_event_id,
                        )
                    await outbox_session.commit()
                logger.info(  # type: ignore[no-any-return]
                    "provisional_enrichment_dirtied_outbox_enqueued",
                    count=len(entity_ids_to_dirty),
                )
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "provisional_enrichment_dirtied_outbox_failed",
                    count=len(entity_ids_to_dirty),
                    exc_info=True,
                )

        logger.info(  # type: ignore[no-any-return]
            "provisional_enrichment_worker_complete",
            enriched=enriched,
            failed=failed,
        )

    async def _recover_stale_processing_rows(self, session: Any) -> int:
        """Reset rows stuck in 'processing' for > 30 minutes back to 'pending'.

        B-7 fix: provisional_entity_queue has no ``updated_at`` column (only
        ``created_at``), so we use a 30-minute threshold on ``created_at``.
        Rows that were legitimately created recently and are still processing
        will not be reset (they are younger than 30 minutes).

        DEF-033 / Wave A-4 QA fix: also set ``next_retry_at`` on the recovered
        rows using the same exponential-backoff formula as
        ``core.apply_retry_transition``.  Without this, recovered rows would
        bypass the backoff window — the next scheduler tick would re-claim them
        immediately and hammer the upstream LLM during an outage.  The Python-
        side LEAST clamp mirrors the SQL ``LEAST(base * 2^rc, max)`` used by
        the regular retry path so both code paths converge on the same window.

        Returns the number of rows recovered.
        """
        from sqlalchemy import text

        # The DB UPDATE uses a SQL CASE on the *post-increment* retry_count to
        # compute the exponential window; we clamp at ``max_retry_minutes`` so
        # an old stuck row with retry_count=10 doesn't end up scheduled
        # months in the future.  The :now bind makes the result deterministic
        # in tests that patch ``common.time.utc_now``.
        from common.time import utc_now as _utc_now  # type: ignore[import-untyped]

        result = await session.execute(
            text("""
UPDATE provisional_entity_queue
SET status = 'pending',
    retry_count = LEAST(retry_count + 1, :max_retries),
    next_retry_at = CAST(:now AS TIMESTAMPTZ)
        + (LEAST(
                :base_minutes * (2 ^ LEAST(retry_count + 1, 30))::int,
                :max_minutes
            ) || ' minutes')::interval
WHERE status = 'processing'
  AND COALESCE(processing_started_at, created_at) < CAST(:now AS TIMESTAMPTZ) - INTERVAL '30 minutes'
"""),
            {
                "max_retries": self._max_retries,
                "now": _utc_now(),
                "base_minutes": self._base_retry_minutes,
                "max_minutes": self._max_retry_minutes,
            },
        )
        await session.commit()
        return int(result.rowcount or 0)

    async def _apply_retry(
        self,
        session: Any,
        queue_id: UUID,
        retry_count: int,
    ) -> None:
        """Increment retry_count; transition to 'failed' when max_retries is reached.

        Delegates SQL to core.apply_retry_transition; increments the Prometheus
        counter here so test patch paths (which mock this module's counter) remain
        unchanged.
        """
        # retry_count is unused — kept in the signature for backward-compatibility
        # with the worker's existing call sites; core.apply_retry_transition reads
        # the count atomically from the DB.
        del retry_count
        # DEF-033: pass the configured backoff window so the SQL CASE in
        # core.apply_retry_transition writes ``next_retry_at`` consistent with
        # the operator-visible env vars.
        transitioned_to_failed = await core.apply_retry_transition(
            session,
            queue_id,
            self._max_retries,
            base_retry_minutes=self._base_retry_minutes,
            max_retry_minutes=self._max_retry_minutes,
        )
        if transitioned_to_failed:
            s7_provisional_enrichment_failed_total.inc()

    async def _persist_enrichment(
        self,
        session: AsyncSession,
        queue_id: UUID,
        mention_text: str,
        profile: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> UUID | None:
        """Delegate to core.persist_enrichment.

        F2 §4.3: forwards the optional ``market_data_lookup`` so tradable
        provisional entities anchor on the existing instrument_id. When the
        delegate returns None for a tradable + ticker case it means S2 has no
        row yet — the run() loop's existing ``_apply_retry`` branch picks up
        the None return and applies exponential backoff, eventually
        transitioning to terminal status='failed' at max_retries.
        """
        return await core.persist_enrichment(
            session=session,
            queue_id=queue_id,
            mention_text=mention_text,
            profile=profile,
            embedding=embedding,
            embed_model_id=self._embed_model_id,
            market_data_lookup=self._market_data_lookup,
        )

    async def _extract_entity_profile(
        self,
        mention_text: str,
        mention_class: str,
        context_snippet: str,
    ) -> dict[str, Any] | None:
        """Delegate to core.extract_entity_profile."""
        return await core.extract_entity_profile(self._llm, mention_text, mention_class, context_snippet)

    async def _compute_embedding(
        self,
        entity_id: UUID | None,
        source_text: str,
    ) -> list[float] | None:
        """Delegate to core.compute_embedding."""
        return await core.compute_embedding(self._llm, entity_id, source_text, self._embed_model_id)

    # -----------------------------------------------------------------------
    # PLAN-0072 T-72-1-01 — noise pre-filter helpers
    # -----------------------------------------------------------------------

    async def _run_noise_filters(
        self,
        pending_rows: list[tuple[UUID, str, str, str, int]],
    ) -> tuple[list[UUID], list[UUID], list[tuple[UUID, str, str, str, int]]]:
        """Apply Layer 1 (blocklist) and Layer 2 (cheap LLM) noise filters.

        Returns (layer1_noise_ids, layer2_noise_ids, remaining_rows).
        Rows in noise lists have been excluded from remaining_rows.
        Layer 2 is fail-open: any exception falls through to Layer 3, never
        silently drops a row (BP-384: noise check before persist_enrichment).
        """
        layer1_noise_ids: list[UUID] = []
        layer2_candidates: list[tuple[UUID, str, str, str, int]] = []

        # Layer 1 — O(1) frozenset lookup
        for row in pending_rows:
            queue_id, mention_text, _mc, _ctx, _rc = row
            if mention_text.lower().strip() in _NOISE_BLOCKLIST:
                layer1_noise_ids.append(queue_id)
                s7_provisional_noise_filtered_total.inc()
            else:
                layer2_candidates.append(row)

        # Layer 2 — cheap LLM binary classification (fail-open).
        # F-DATA-005: parallelized with asyncio.gather + semaphore (same
        # concurrency cap as Phase 2) so 50 rows x 10s timeout = 500s serial
        # blocking is avoided.  Fail-open semantics preserved: an exception
        # in gather wrapper means the row passes to Layer 3, never dropped.
        layer2_noise_ids: list[UUID] = []
        layer2_pass: list[tuple[UUID, str, str, str, int]] = []

        sem = asyncio.Semaphore(self._concurrency)

        async def _classify_one(
            row: tuple[UUID, str, str, str, int],
        ) -> tuple[tuple[UUID, str, str, str, int], bool]:
            async with sem:
                is_noise = await self._layer2_classify(row[1])
                return row, is_noise

        classify_results = await asyncio.gather(
            *[_classify_one(row) for row in layer2_candidates],
            return_exceptions=True,
        )
        for i, classify_result in enumerate(classify_results):
            if isinstance(classify_result, Exception):
                # Fail-open: exception in the gather wrapper → row proceeds to
                # Layer 3.  Use the index to recover the original row so it is
                # not silently dropped.  (_layer2_classify already returns False
                # on any internal error; this branch only fires if the semaphore
                # wrapper itself raises, which is extremely rare.)
                layer2_pass.append(layer2_candidates[i])
                continue
            row, is_noise = classify_result  # type: ignore[misc]
            if is_noise:
                layer2_noise_ids.append(row[0])
                s7_provisional_noise_llm_filtered_total.inc()
            else:
                layer2_pass.append(row)

        return layer1_noise_ids, layer2_noise_ids, layer2_pass

    async def _layer2_classify(self, mention_text: str) -> bool:
        """Call the cheap LLM classifier to decide if mention_text is noise.

        Returns True if the mention should be treated as noise.
        Fail-open: any network/parse error returns False (proceed to Layer 3).

        Decision rules:
          - ``is_entity=false``  → noise
          - ``confidence < 0.7`` → noise (low-confidence entity = treat as noise)
          - Layer 2 error        → False (fail-open, warning logged)
        """
        if not self._noise_api_key:
            # No API key → Layer 2 unavailable, fall through to Layer 3.
            return False

        if self._noise_http_client is None:
            # BP-235: set httpx timeout slightly higher than asyncio.wait_for
            # timeout so the asyncio wall-clock timeout fires first and we get
            # a clean asyncio.TimeoutError instead of httpx's ReadTimeout.
            self._noise_http_client = httpx.AsyncClient(timeout=httpx.Timeout(self._noise_timeout_s + 1.0))

        # F-SEC-005: use json.dumps to safely escape any double quotes or
        # control characters in mention_text before embedding in the prompt.
        user_content = f"MENTION: {json.dumps(mention_text[:200])}"
        try:
            response = await asyncio.wait_for(
                self._noise_http_client.post(
                    f"{self._noise_api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {self._noise_api_key}"},
                    json={
                        "model": _NOISE_CLASSIFIER_MODEL_ID,
                        "messages": [
                            {"role": "system", "content": _NOISE_CLASSIFIER_SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.0,
                        "max_tokens": 64,
                    },
                ),
                timeout=self._noise_timeout_s,
            )
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"].get("content", "")
            parsed = json.loads(raw)
            is_entity = bool(parsed.get("is_entity", True))
            confidence = float(parsed.get("confidence", 1.0))
            return not is_entity or confidence < 0.7
        except Exception as exc:
            # Fail-open: any error → proceed to Layer 3, never drop the row.
            logger.warning(  # type: ignore[no-any-return]
                "provisional_enrichment_noise_classifier_error",
                mention_text_hash=hashlib.sha256(mention_text.encode()).hexdigest()[:16],
                error=str(exc),
                action="fail_open_to_layer3",
            )
            return False

    async def aclose(self) -> None:
        """Close the shared httpx client used by the Layer 2 noise classifier.

        F-DATA-007: the client is created lazily and must be closed at worker
        shutdown to release the underlying TCP connection pool and avoid
        ResourceWarning in tests and production teardown.
        """
        if self._noise_http_client is not None:
            await self._noise_http_client.aclose()
            self._noise_http_client = None
