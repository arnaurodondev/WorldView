"""Worker 13C: LLM summary generation (PRD §6.7 Block 13C).

Runs every 60 minutes.  Processes relations with ``summary_stale=true``:
  1. Fetch top-10 evidence (ORDER BY source_weight DESC, evidence_date DESC).
  2. Build a prompt from evidence texts.
  3. Call ExtractionClient (via FallbackChainClient) to generate a summary.
  4. Compute evidence_hash (SHA-256) for change detection — skip if unchanged.
  5. Insert new summary row (is_current=true), retire old one.
  6. Mark summary_stale=false on the relation.

All LLM calls are logged to llm_usage_log.

Session discipline (DS-001 / ARCH-003 / DEF-018, Wave B-1):
  DB connections are held only for the duration of each DB operation.  The LLM
  call (which can take 5-30 s) is always issued with NO open session to prevent
  connection-pool starvation under a 20-relation batch.

  Three-phase split:
    Phase 1 (READ session via ``self._read_session_factory``): fetch the stale
            relation list.  When ``DATABASE_URL_READ`` is configured this
            targets the read replica; otherwise it falls back to the write
            pool (Wave B-5 wired ``read_session_factory`` from the scheduler).
    Phase 2 (NO session): call the LLM for each relation.
    Phase 3 (WRITE session per row via ``self._sf``): insert the summary and
            clear the stale flag.  On LLM failure (per F-DS-208) the stale
            flag is still cleared to prevent indefinite retry storms.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ml_clients.protocols import EmbeddingClient, ExtractionClient  # type: ignore[import-untyped]
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

# SA-2: retry-with-exponential-backoff schedule for the primary LLM call.
# 3 total attempts: initial → 2 s wait → 5 s wait → give up → Gemini fallback.
# Delays are short because the caller (SummaryWorker) holds no DB session
# during LLM I/O — sleeping here is safe and does not block the DB pool.
_SUMMARY_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0)

_BATCH_LIMIT = 20
_EVIDENCE_LIMIT = 10
_PROMPT_TEMPLATE_ID = "00000000-0000-0000-0000-000000000001"  # seeded in prompt_templates

# BP-121: BGE-large has a 512-token context window (~1500 chars) — truncate
# summary text before embedding to avoid GGML runtime crashes.
_MAX_EMBED_CHARS = 1500


class SummaryWorker:
    """Generates LLM summaries for stale relations (Worker 13C).

    Args:
    ----
        session_factory: Write sessionmaker for intelligence_db.  Used for
                         Phase 3 writes (insert summary + clear stale flag).
        llm_client:      FallbackChainClient for extraction.
        force_regen_batch_size:
            When > 0, skip the evidence-hash equality check for up to this many
            relations per cycle.  Allows forced refresh after prompt-template
            upgrades.  0 (default) uses normal hash-based skip logic.
        read_session_factory:
            Optional read-replica sessionmaker (DEF-034 / Wave B-5).  Used for
            Phase 1 (fetch stale list) and Phase 2 (fetch evidence + existing
            summary) so heavy summary cycles do not contend with write traffic.
            When ``None`` (default), falls back to ``session_factory`` so
            existing call sites and tests that pass only the write factory
            continue to work unchanged.
        gemini_extraction_client:
            SA-2: optional direct Gemini extraction client.  Used as an
            explicit last-resort fallback when the primary FallbackChainClient
            is fully exhausted (returns None).  When ``None``, the Gemini
            fallback path is skipped.
        summary_retry_delays:
            SA-2: delays (seconds) between retries of the primary LLM call.
            Default ``_SUMMARY_RETRY_DELAYS`` = (2 s, 5 s) → 3 total attempts.
            Pass ``()`` in unit tests to skip sleeping.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        force_regen_batch_size: int = 0,
        read_session_factory: Any = None,
        embedding_port: EmbeddingClient | None = None,
        *,
        gemini_extraction_client: ExtractionClient | None = None,
        summary_retry_delays: tuple[float, ...] = _SUMMARY_RETRY_DELAYS,
        batch_limit: int = _BATCH_LIMIT,
        concurrency: int = 1,
    ) -> None:
        # BACKLOG-DRAIN (2026-07-16): batch size + LLM concurrency are now
        # constructor-injected from settings (defaults preserve the historical
        # 20-row / sequential behaviour so existing call sites + tests are
        # unaffected).  ``concurrency`` bounds the number of relations whose LLM
        # summary call is in flight at once — each call holds NO DB session
        # (see the three-phase discipline in the module docstring), so running
        # several in parallel does not touch the DB pool; only the write phase
        # briefly opens a per-row session.
        self._batch_limit = max(1, int(batch_limit))
        self._concurrency = max(1, int(concurrency))
        self._sf = session_factory
        # DEF-018 / Wave B-1: route Phase 1 + Phase 2 reads through the read
        # replica when one is wired in by the scheduler.  Falling back to the
        # write factory preserves backward-compat with existing tests that
        # construct the worker with only ``session_factory``.
        self._read_session_factory: Any = read_session_factory if read_session_factory is not None else session_factory
        self._llm = llm_client
        self._force_regen_batch_size = force_regen_batch_size
        # T-B-04: optional embedding port for summary_embedding population.
        # When None, embedding is skipped (does not block summary write).
        self._embedding_port = embedding_port
        # SA-2: Gemini 2.5 Flash Lite direct fallback client.  Used when the
        # FallbackChainClient returns None (all primary+secondary providers
        # exhausted).  None = Gemini fallback disabled.
        self._gemini_ext: ExtractionClient | None = gemini_extraction_client
        # SA-2: retry delays for the primary LLM call before escalating to Gemini.
        self._summary_retry_delays = summary_retry_delays

    async def run(self) -> None:
        """Generate summaries for stale relations.

        Session discipline — three phases per relation, each with its own
        short-lived ``async with self._sf() as session:`` block:

          Phase 1  Fetch the stale-relation list (list query only).
          Phase 2  Fetch evidence rows + existing summary (read-only).
          Phase 3a Hash unchanged → mark updated (single UPDATE + commit).
          Phase 3b Hash changed  → LLM call (NO session open), then write
                   summary + mark updated in one final session.

        BACKLOG-DRAIN (2026-07-16): Phases 2-4 for each relation are dispatched
        concurrently (bounded by ``self._concurrency``) via
        :meth:`_process_relation`; the per-relation session discipline is
        unchanged.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository

        # ── Phase 1: fetch stale list (READ session, short-lived) ───────────
        # DEF-018 / Wave B-1: open the read-replica session so the stale-list
        # SELECT does not contend with the write pool.  ``fetch_stale_summary``
        # no longer uses ``FOR UPDATE SKIP LOCKED`` (per F-DS-201:
        # ``max_instances=1`` APScheduler coalescing prevents concurrency).
        # BACKLOG-DRAIN (2026-07-16): pull ``self._batch_limit`` rows (was the
        # hardcoded ``_BATCH_LIMIT=20``) so a large summary backlog drains in
        # far fewer cycles.
        async with self._read_session_factory() as session:
            rel_repo = RelationRepository(session)
            stale_relations = await rel_repo.fetch_stale_summary(self._batch_limit)  # type: ignore[attr-defined]

        batch_size = len(stale_relations)

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_batch_start",
            stale_relations=batch_size,
            phase1_fetched_count=batch_size,
            batch_limit=self._batch_limit,
            concurrency=self._concurrency,
        )

        # BACKLOG-DRAIN (2026-07-16): pre-assign the force-regen slots to the
        # first ``_force_regen_batch_size`` relations *in fetch order*.  The old
        # sequential loop consumed a slot lazily when each relation reached the
        # hash check; under concurrency that running counter is racy, so we
        # assign slots deterministically up front instead.  ``fetch_stale_summary``
        # returns a stable ORDER BY (confidence DESC, latest_evidence_at DESC),
        # so the same relations are force-regenerated each cycle.
        force_regen_flags = [i < self._force_regen_batch_size for i in range(batch_size)]

        # ── Phases 2-4: process each relation, bounded by a semaphore ────────
        # Each relation's LLM call (Phase 3, 5-30 s) holds NO DB session, so
        # running ``self._concurrency`` of them in flight only multiplies
        # network I/O — it never widens the DB connection footprint beyond the
        # short per-row write sessions.  ``_process_relation`` swallows its own
        # commit failures (returns counter deltas), so one bad row cannot abort
        # the batch.  ``return_exceptions=True`` is the belt-and-braces guard:
        # if a relation's LLM call ever *raises* (rather than returning None) —
        # e.g. an unexpected client-side error not caught inside
        # ``_generate_summary`` — gather must NOT propagate it, because that
        # would abort the whole cycle and leave the sibling coroutines detached
        # as orphans that may still commit after ``run`` returns.  Instead we
        # collect the Exception, log it as a per-relation failure, and continue
        # aggregating the rest of the batch.
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _bounded(rel: Any, force_regen: bool) -> dict[str, int]:
            async with semaphore:
                return await self._process_relation(rel, force_regen=force_regen)

        outcomes = await asyncio.gather(
            *(_bounded(rel, force_regen_flags[i]) for i, rel in enumerate(stale_relations)),
            return_exceptions=True,
        )

        # Aggregate per-relation outcome counters into the batch summary.
        # An ``Exception`` element means that relation's coroutine raised (the
        # ``return_exceptions=True`` guard above); log-and-skip it so it counts
        # as a failure but never corrupts the totals sum or aborts the batch.
        totals: dict[str, int] = {}
        for rel, outcome in zip(stale_relations, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                totals["relation_errors"] = totals.get("relation_errors", 0) + 1
                logger.error(  # type: ignore[no-any-return]
                    "summary_worker_relation_error",
                    relation_id=str(rel.get("relation_id")),
                    error=str(outcome),
                    error_type=type(outcome).__name__,
                )
                continue
            for key, value in outcome.items():
                totals[key] = totals.get(key, 0) + value

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_complete",
            stale_relations=batch_size,
            summaries_created=totals.get("created", 0),
            summaries_skipped=totals.get("skipped", 0),
            skipped_no_evidence=totals.get("skipped_no_evidence", 0),
            skipped_null_evidence_text=totals.get("skipped_null_evidence_text", 0),
            immutable_hits=totals.get("immutable_hits", 0),
            raw_fallback_hits=totals.get("raw_fallback_hits", 0),
            # BACKLOG-DRAIN (2026-07-16): relations whose coroutine raised and
            # were log-and-skipped (return_exceptions guard).  Non-zero here
            # means an uncaught error path exists in _process_relation.
            relation_errors=totals.get("relation_errors", 0),
            # DEF-018 / Wave B-1 phase metrics:
            phase1_fetched_count=batch_size,
            phase2_llm_calls=totals.get("llm_calls", 0),
            phase3_written_count=totals.get("created", 0),
        )

    async def _process_relation(self, rel: Any, *, force_regen: bool) -> dict[str, int]:
        """Process one stale relation (Phases 2-4) and return counter deltas.

        BACKLOG-DRAIN (2026-07-16): extracted verbatim from the old sequential
        ``run`` loop body so it can be dispatched concurrently via
        ``asyncio.gather``.  The three-phase session discipline is unchanged —
        Phase 2 reads run on the read replica, the LLM call (Phase 3) holds no
        session, and each write opens its own short-lived write session.

        Returns a dict of counter deltas (all keys optional); the caller sums
        them across the batch for the ``summary_worker_complete`` log.
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        relation_id = rel["relation_id"]

        # ── Phase 2: fetch evidence + existing summary (READ session) ───
        async with self._read_session_factory() as session:
            ev_repo = RelationEvidenceRepository(session)
            summary_repo = RelationSummaryRepository(session)

            evidence_rows = await ev_repo.get_all_for_relation(  # type: ignore[attr-defined]
                relation_id,
                limit=_EVIDENCE_LIMIT,
            )
            evidence_source = "immutable"
            # Fall back to raw staging table when the immutable partition
            # table is empty (insert_immutable promotion not yet implemented).
            if not evidence_rows:
                evidence_rows = await ev_repo.get_raw_for_relation_id(  # type: ignore[attr-defined]
                    relation_id,
                    limit=_EVIDENCE_LIMIT,
                )
                evidence_source = "raw_fallback"
                if evidence_rows:
                    logger.debug(  # type: ignore[no-any-return]
                        "summary_worker_raw_fallback_triggered",
                        relation_id=str(relation_id),
                        evidence_source=evidence_source,
                        row_count=len(evidence_rows),
                    )

            # Get existing summary for hash check — read while session is still open.
            existing = await summary_repo.get_current(relation_id)

        # ── Outside any session: process evidence texts ──────────────────
        if not evidence_rows:
            return {"skipped_no_evidence": 1}

        # Track which evidence source contributed
        source_counter = "immutable_hits" if evidence_source == "immutable" else "raw_fallback_hits"

        evidence_texts = []
        for e in evidence_rows:
            # Prefer evidence_text; fall back to canonicalized_evidence_text (immutable rows only).
            # Avoid str(None) = "None" bug from the old list-comprehension approach.
            text = e.get("evidence_text") or e.get("canonicalized_evidence_text")
            if text:
                evidence_texts.append(str(text))

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_relation_evidence_audit",
            relation_id=str(relation_id),
            evidence_rows_fetched=len(evidence_rows),
            evidence_text_null_count=sum(1 for e in evidence_rows if not e.get("evidence_text")),
            # Fix DATA-008: only count nulls when the key is present in the dict.
            # relation_evidence_raw has NO canonicalized_evidence_text column, so
            # counting absent keys as nulls would inflate the metric for raw-path rows.
            canonicalized_text_null_count=sum(
                1
                for e in evidence_rows
                if "canonicalized_evidence_text" in e and not e.get("canonicalized_evidence_text")
            ),
            evidence_texts_available=len(evidence_texts),
        )
        if not evidence_texts:
            return {source_counter: len(evidence_rows), "skipped_null_evidence_text": 1}

        # SHA-256 of combined evidence for change detection
        combined = "\n".join(sorted(evidence_texts))
        evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

        # ── Determine whether the LLM call is needed ─────────────────────
        # Force-regen mode: skip the hash check for the pre-assigned slots
        # (see ``force_regen_flags`` in ``run``).
        if not force_regen and existing and existing.get("evidence_hash") == evidence_hash:
            # Hash unchanged — skip expensive LLM call; just clear the stale flag.
            # QA-fix §2.1: per-relation try/except so one commit failure does
            # not abort the whole batch.
            try:
                async with self._sf() as session:
                    rel_repo = RelationRepository(session)
                    await rel_repo.mark_summary_updated(relation_id)  # type: ignore[attr-defined]
                    await session.commit()
                return {source_counter: len(evidence_rows), "skipped": 1}
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "summary_worker_phase4_commit_failed",
                    phase="hash_unchanged_clear_stale",
                    relation_id=str(relation_id),
                    error=str(exc),
                )
                return {source_counter: len(evidence_rows)}

        # ── Phase 3 (LLM): NO session is open here ──────────────────────
        summary_text = await self._generate_summary(evidence_texts, relation_id)
        if summary_text is None:
            # F-DS-208: on permanent LLM failure clear the stale flag
            # rather than retry every cycle (retry-storm prevention).
            # The flag is re-set when fresh evidence arrives via upsert.
            logger.warning(  # type: ignore[no-any-return]
                "summary_worker_llm_failed",
                relation_id=str(relation_id),
                summary_last_failed_at=utc_now().isoformat(),
            )
            try:
                async with self._sf() as session:
                    rel_repo = RelationRepository(session)
                    await rel_repo.mark_summary_updated(relation_id)  # type: ignore[attr-defined]
                    await session.commit()
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "summary_worker_phase4_commit_failed",
                    phase="llm_failure_clear_stale",
                    relation_id=str(relation_id),
                    error=str(exc),
                )
            return {source_counter: len(evidence_rows), "llm_calls": 1}

        # ── Phase 3 (write): WRITE session per row ──────────────────────
        new_summary_id: UUID | None = None
        result: dict[str, int] = {source_counter: len(evidence_rows), "llm_calls": 1}
        try:
            async with self._sf() as session:
                summary_repo = RelationSummaryRepository(session)
                rel_repo = RelationRepository(session)
                new_summary_id = await summary_repo.insert_new(
                    relation_id=relation_id,
                    summary_text=summary_text,
                    evidence_count=len(evidence_texts),
                    evidence_hash=evidence_hash,
                    model_id="kg-summary-v1",
                    prompt_template_id=UUID(_PROMPT_TEMPLATE_ID),
                    generation_trigger="worker_13c_scheduled",
                )
                await rel_repo.mark_summary_updated(relation_id)  # type: ignore[attr-defined]
                await session.commit()
            result["created"] = 1
        except Exception as exc:
            logger.error(  # type: ignore[no-any-return]
                "summary_worker_phase4_commit_failed",
                phase="insert_new",
                relation_id=str(relation_id),
                error=str(exc),
            )

        # ── Phase 4 (embedding): populate summary_embedding (T-B-04) ────
        if new_summary_id is not None and self._embedding_port is not None:
            await self._embed_and_persist_summary(
                summary_id=new_summary_id,
                summary_text=summary_text,
                relation_id=relation_id,
            )

        return result

    async def _embed_and_persist_summary(
        self,
        summary_id: UUID,
        summary_text: str,
        relation_id: Any,
    ) -> None:
        """Compute and store the summary_embedding for a freshly written summary row.

        T-B-04 requirements:
        - BP-121 guard: truncate summary_text to _MAX_EMBED_CHARS before calling
          the embedding port to prevent BGE-large GGML context-overflow crashes.
        - On any embedding failure: log ``summary_embedding_skip`` and return
          without raising — the summary write is already committed and must not
          be rolled back.
        - The UPDATE is committed in its own short-lived WRITE session.
        """
        from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        # BP-121: truncate to prevent BERT 512-token overflow in BGE-large.
        embed_text = summary_text[:_MAX_EMBED_CHARS]

        try:
            outputs = await self._embedding_port.embed(  # type: ignore[union-attr]
                [EmbeddingInput(text=embed_text, model_id="summary-embed-v1")]
            )
            if not outputs:
                raise ValueError("empty embedding output")
            embedding = outputs[0].embedding
            model_id = outputs[0].model_id
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "summary_embedding_skip",
                summary_id=str(summary_id),
                relation_id=str(relation_id),
                error=str(exc),
                message="Embedding failed; summary_embedding left NULL",
            )
            return

        try:
            async with self._sf() as session:
                summary_repo = RelationSummaryRepository(session)
                await summary_repo.update_embedding(
                    summary_id=summary_id,
                    embedding=embedding,
                    model_id=model_id,
                    embedded_at=utc_now(),  # type: ignore[no-any-return]
                )
                await session.commit()
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "summary_embedding_persist_failed",
                summary_id=str(summary_id),
                relation_id=str(relation_id),
                error=str(exc),
            )

    async def _generate_summary(
        self,
        evidence_texts: list[str],
        relation_id: Any,
    ) -> str | None:
        """Generate a summary via LLM with retry-with-backoff + Gemini fallback.

        SA-2 retry/fallback chain:
          1. FallbackChainClient.extract() — attempt 1 (primary: DeepInfra → Ollama → Gemini chain).
          2. On None: wait ``_summary_retry_delays[0]`` seconds, retry once.
          3. On None: wait ``_summary_retry_delays[1]`` seconds, retry once more.
          4. On None after all retries: escalate to direct Gemini 2.1 Flash Lite client
             (``self._gemini_ext``) with ``summary_worker_fallback_invoked`` log.
          5. On Gemini failure or ``self._gemini_ext=None``: return None (caller handles).
        """
        from ml_clients.dataclasses import ExtractionInput  # type: ignore[import-untyped]
        from prompts.knowledge.summary import RELATION_SUMMARY  # type: ignore[import-untyped]

        context = "\n".join(f"- {t}" for t in evidence_texts[:_EVIDENCE_LIMIT])
        prompt = RELATION_SUMMARY.render(evidence_statements=context)
        inp = ExtractionInput(
            prompt=prompt,
            context=context,
            output_schema={"summary": "string"},
            model_id="kg-summary-v1",
            template_id=_PROMPT_TEMPLATE_ID,
        )

        # ── Primary path: FallbackChainClient with retry-with-backoff ────────
        # The FallbackChainClient itself already applies per-provider retries
        # internally (DeepInfra: 2 attempts; Ollama/Gemini: configurable).
        # The outer retry loop here is an additional layer applied at the
        # WORKER level, independent of per-provider retries inside the chain.
        # This ensures transient "chain exhausted" events (e.g. a brief network
        # blip that hits all providers simultaneously) are retried before
        # escalating to the explicit Gemini fallback.
        result = None
        for attempt, delay in enumerate(self._summary_retry_delays):
            result = await self._llm.extract(inp, entity_id=None)
            if result is not None:
                break
            logger.warning(  # type: ignore[no-any-return]
                "summary_worker_primary_retry",
                relation_id=str(relation_id),
                attempt=attempt + 1,
                delay_s=delay,
            )
            await asyncio.sleep(delay)
        else:
            # Final attempt after the last delay has been served.
            result = await self._llm.extract(inp, entity_id=None)

        if result is not None:
            raw_resp = getattr(result, "raw_response", None)
            # Fix SEC-003: downgrade from INFO to DEBUG — raw LLM responses may
            # contain financial data excerpted from news articles.
            # Fix SEC-204: raw_response_preview removed — even truncated text may
            # contain PII or proprietary financial data; length alone is sufficient
            # for debugging truncation/empty-response issues.
            logger.debug(  # type: ignore[no-any-return]
                "summary_worker_llm_raw_response",
                relation_id=str(relation_id),
                raw_response_length=len(raw_resp) if raw_resp else 0,
            )
            return str(result.result.get("summary", "")) or None

        # ── Gemini 2.5 Flash Lite explicit fallback (SA-2) ───────────────────
        # Primary chain exhausted after retries.  Escalate to the Gemini client
        # wired in at construction time (via ``gemini_extraction_client``).
        # ``summary_worker_fallback_invoked`` is the validation-gate log event.
        if self._gemini_ext is None:
            return None

        logger.warning(  # type: ignore[no-any-return]
            "summary_worker_fallback_invoked",
            relation_id=str(relation_id),
            fallback_provider="gemini",
        )
        try:
            fallback_result = await self._gemini_ext.extract(inp)
        except Exception as exc:
            logger.error(  # type: ignore[no-any-return]
                "summary_worker_fallback_failed",
                relation_id=str(relation_id),
                fallback_provider="gemini",
                error=str(exc),
            )
            return None

        if fallback_result is None:
            return None

        raw_resp = getattr(fallback_result, "raw_response", None)
        logger.debug(  # type: ignore[no-any-return]
            "summary_worker_llm_raw_response",
            relation_id=str(relation_id),
            raw_response_length=len(raw_resp) if raw_resp else 0,
            provider="gemini_fallback",
        )
        return str(fallback_result.result.get("summary", "")) or None
