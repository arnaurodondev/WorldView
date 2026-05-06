"""Worker 13C: LLM summary generation (PRD §6.7 Block 13C).

Runs every 60 minutes.  Processes relations with ``summary_stale=true``:
  1. Fetch top-10 evidence (ORDER BY source_weight DESC, evidence_date DESC).
  2. Build a prompt from evidence texts.
  3. Call ExtractionClient (via FallbackChainClient) to generate a summary.
  4. Compute evidence_hash (SHA-256) for change detection — skip if unchanged.
  5. Insert new summary row (is_current=true), retire old one.
  6. Mark summary_stale=false on the relation.

All LLM calls are logged to llm_usage_log.

Session discipline (DS-001):
  DB connections are held only for the duration of each DB operation.  The LLM
  call (which can take 5-30 s) is always issued with NO open session to prevent
  connection-pool starvation under a 20-relation batch.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]

_BATCH_LIMIT = 20
_EVIDENCE_LIMIT = 10
_PROMPT_TEMPLATE_ID = "00000000-0000-0000-0000-000000000001"  # seeded in prompt_templates


class SummaryWorker:
    """Generates LLM summaries for stale relations (Worker 13C).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.
        llm_client:      FallbackChainClient for extraction.
        force_regen_batch_size:
            When > 0, skip the evidence-hash equality check for up to this many
            relations per cycle.  Allows forced refresh after prompt-template
            upgrades.  0 (default) uses normal hash-based skip logic.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
        force_regen_batch_size: int = 0,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client
        self._force_regen_batch_size = force_regen_batch_size

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

        # ── Phase 1: fetch stale list (short-lived session) ──────────────────
        async with self._sf() as session:
            rel_repo = RelationRepository(session)
            stale_relations = await rel_repo.fetch_stale_summary(_BATCH_LIMIT)  # type: ignore[attr-defined]

        batch_size = len(stale_relations)

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_batch_start",
            stale_relations=batch_size,
        )

        # Track how many relations in this cycle have been force-regenerated so
        # we can stop once _force_regen_batch_size is reached.
        force_regen_used = 0

        for rel in stale_relations:
            relation_id = rel["relation_id"]  # type: ignore[assignment]

            # ── Phase 2: fetch evidence + existing summary (short-lived session)
            async with self._sf() as session:
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
            force_regen_active = self._force_regen_batch_size > 0 and force_regen_used < self._force_regen_batch_size

            if not force_regen_active and existing and existing.get("evidence_hash") == evidence_hash:
                # Hash unchanged — skip expensive LLM call; just clear the stale flag.
                async with self._sf() as session:
                    rel_repo = RelationRepository(session)
                    await rel_repo.mark_summary_updated(relation_id)  # type: ignore[arg-type, attr-defined]
                    await session.commit()
                summaries_skipped += 1
                continue

            if force_regen_active:
                force_regen_used += 1

            # ── Phase 3: LLM call — NO session is open here ─────────────────
            summary_text = await self._generate_summary(evidence_texts, relation_id)  # type: ignore[arg-type]
            if summary_text is None:
                logger.warning(  # type: ignore[no-any-return]
                    "summary_worker_llm_failed",
                    relation_id=str(relation_id),
                )
                # Clear stale flag to prevent indefinite retry on permanent LLM
                # failures; the flag is re-set when new evidence arrives via upsert.
                async with self._sf() as session:
                    rel_repo = RelationRepository(session)
                    await rel_repo.mark_summary_updated(relation_id)  # type: ignore[arg-type, attr-defined]
                    await session.commit()
                continue

            # ── Phase 4: write summary (short-lived session) ─────────────────
            async with self._sf() as session:
                summary_repo = RelationSummaryRepository(session)
                rel_repo = RelationRepository(session)
                await summary_repo.insert_new(
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

        logger.info(  # type: ignore[no-any-return]
            "summary_worker_complete",
            stale_relations=batch_size,
            summaries_created=summaries_created,
            summaries_skipped=summaries_skipped,
            skipped_no_evidence=skipped_no_evidence,
            skipped_null_evidence_text=skipped_null_evidence_text,
            immutable_hits=immutable_hits_total,
            raw_fallback_hits=raw_fallback_hits_total,
        )

    async def _generate_summary(
        self,
        evidence_texts: list[str],
        relation_id: Any,
    ) -> str | None:
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

        result = await self._llm.extract(inp, entity_id=None)
        if result is None:
            return None
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
