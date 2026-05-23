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
    ) -> None:
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
        """
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        summaries_created = 0
        summaries_skipped = 0
        immutable_hits_total = 0
        raw_fallback_hits_total = 0
        skipped_no_evidence = 0
        skipped_null_evidence_text = 0
        # DEF-018 / Wave B-1: per-phase counters for observability.  Emitted in
        # the final ``summary_worker_complete`` structlog record below.
        phase1_fetched_count = 0
        phase2_llm_calls = 0
        phase3_written_count = 0

        # ── Phase 1: fetch stale list (READ session, short-lived) ───────────
        # DEF-018 / Wave B-1: open the read-replica session so the stale-list
        # SELECT does not contend with the write pool.  ``fetch_stale_summary``
        # no longer uses ``FOR UPDATE SKIP LOCKED`` (per F-DS-201:
        # ``max_instances=1`` APScheduler coalescing prevents concurrency).
        async with self._read_session_factory() as session:
            rel_repo = RelationRepository(session)
            stale_relations = await rel_repo.fetch_stale_summary(_BATCH_LIMIT)  # type: ignore[attr-defined]

        batch_size = len(stale_relations)
        phase1_fetched_count = batch_size

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_batch_start",
            stale_relations=batch_size,
            phase1_fetched_count=phase1_fetched_count,
        )

        # Track how many relations in this cycle have been force-regenerated so
        # we can stop once _force_regen_batch_size is reached.
        force_regen_used = 0

        for rel in stale_relations:
            relation_id = rel["relation_id"]  # type: ignore[assignment]

            # ── Phase 2: fetch evidence + existing summary (READ session) ───
            # DEF-018 / Wave B-1: also routed through the read replica — these
            # are pure SELECTs against ``relation_evidence_*`` and
            # ``relation_summaries``.  No session is held while the LLM runs.
            async with self._read_session_factory() as session:
                ev_repo = RelationEvidenceRepository(session)
                summary_repo = RelationSummaryRepository(session)

                evidence_rows = await ev_repo.get_all_for_relation(  # type: ignore[attr-defined]
                    relation_id,  # type: ignore[arg-type]
                    limit=_EVIDENCE_LIMIT,
                )
                evidence_source = "immutable"
                # Fall back to raw staging table when the immutable partition
                # table is empty (insert_immutable promotion not yet implemented).
                if not evidence_rows:
                    evidence_rows = await ev_repo.get_raw_for_relation_id(  # type: ignore[attr-defined]
                        relation_id,  # type: ignore[arg-type]
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
                existing = await summary_repo.get_current(relation_id)  # type: ignore[arg-type]

            # ── Outside any session: process evidence texts ──────────────────

            if not evidence_rows:
                skipped_no_evidence += 1
                continue

            # Track which evidence source contributed
            if evidence_source == "immutable":
                immutable_hits_total += len(evidence_rows)
            else:
                raw_fallback_hits_total += len(evidence_rows)

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
                skipped_null_evidence_text += 1
                continue

            # SHA-256 of combined evidence for change detection
            combined = "\n".join(sorted(evidence_texts))
            evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

            # ── Determine whether the LLM call is needed ─────────────────────
            # Force-regen mode: skip the hash check for the first
            # _force_regen_batch_size relations in this cycle.
            # QA-fix §3.1: increment the counter BEFORE the hash check so a
            # force-regen slot is not consumed by a no-op hash-unchanged skip.
            force_regen_active = self._force_regen_batch_size > 0 and force_regen_used < self._force_regen_batch_size
            if force_regen_active:
                force_regen_used += 1

            if not force_regen_active and existing and existing.get("evidence_hash") == evidence_hash:
                # Hash unchanged — skip expensive LLM call; just clear the stale flag.
                # QA-fix §2.1: per-relation try/except so one commit failure does
                # not abort the whole batch.
                try:
                    async with self._sf() as session:
                        rel_repo = RelationRepository(session)
                        await rel_repo.mark_summary_updated(relation_id)  # type: ignore[arg-type, attr-defined]
                        await session.commit()
                    summaries_skipped += 1
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "summary_worker_phase4_commit_failed",
                        phase="hash_unchanged_clear_stale",
                        relation_id=str(relation_id),
                        error=str(exc),
                    )
                continue

            # ── Phase 3 (LLM): NO session is open here ──────────────────────
            # DEF-018 / Wave B-1 / ARCH-003: this is the single most expensive
            # step in the cycle (5-30 s per relation).  Holding a DB session
            # across this call is the original ARCH-003 violation we are
            # fixing — ``self._read_session_factory`` was already exited above.
            phase2_llm_calls += 1
            summary_text = await self._generate_summary(evidence_texts, relation_id)  # type: ignore[arg-type]
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
                        await rel_repo.mark_summary_updated(relation_id)  # type: ignore[arg-type, attr-defined]
                        await session.commit()
                except Exception as exc:
                    logger.error(  # type: ignore[no-any-return]
                        "summary_worker_phase4_commit_failed",
                        phase="llm_failure_clear_stale",
                        relation_id=str(relation_id),
                        error=str(exc),
                    )
                continue

            # ── Phase 3 (write): WRITE session per row ──────────────────────
            # QA-fix §2.1: per-relation try/except — Phase 4 commit failure
            # must not abort the remaining batch.
            new_summary_id: UUID | None = None
            try:
                async with self._sf() as session:
                    summary_repo = RelationSummaryRepository(session)
                    rel_repo = RelationRepository(session)
                    new_summary_id = await summary_repo.insert_new(
                        relation_id=relation_id,  # type: ignore[arg-type]
                        summary_text=summary_text,
                        evidence_count=len(evidence_texts),
                        evidence_hash=evidence_hash,
                        model_id="kg-summary-v1",
                        prompt_template_id=UUID(_PROMPT_TEMPLATE_ID),
                        generation_trigger="worker_13c_scheduled",
                    )
                    await rel_repo.mark_summary_updated(relation_id)  # type: ignore[arg-type, attr-defined]
                    await session.commit()
                summaries_created += 1
                phase3_written_count += 1
            except Exception as exc:
                logger.error(  # type: ignore[no-any-return]
                    "summary_worker_phase4_commit_failed",
                    phase="insert_new",
                    relation_id=str(relation_id),
                    error=str(exc),
                )

            # ── Phase 4 (embedding): populate summary_embedding (T-B-04) ────
            # Runs OUTSIDE the write session — the embedding call can take
            # several seconds and must not hold a DB connection open (DS-001).
            # On any failure: log and continue; the NULL embedding is not fatal
            # (Worker 13F will back-fill missing embeddings in a future wave).
            if new_summary_id is not None and self._embedding_port is not None:
                await self._embed_and_persist_summary(
                    summary_id=new_summary_id,
                    summary_text=summary_text,
                    relation_id=relation_id,
                )

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_complete",
            stale_relations=batch_size,
            summaries_created=summaries_created,
            summaries_skipped=summaries_skipped,
            skipped_no_evidence=skipped_no_evidence,
            skipped_null_evidence_text=skipped_null_evidence_text,
            immutable_hits=immutable_hits_total,
            raw_fallback_hits=raw_fallback_hits_total,
            # DEF-018 / Wave B-1 phase metrics:
            phase1_fetched_count=phase1_fetched_count,
            phase2_llm_calls=phase2_llm_calls,
            phase3_written_count=phase3_written_count,
        )

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
                [EmbeddingInput(text=embed_text, model_id="summary-embed-v1")],
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
