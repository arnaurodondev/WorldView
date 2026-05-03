"""Worker 13C: LLM summary generation (PRD §6.7 Block 13C).

Runs every 60 minutes.  Processes relations with ``summary_stale=true``:
  1. Fetch top-10 evidence (ORDER BY source_weight DESC, evidence_date DESC).
  2. Build a prompt from evidence texts.
  3. Call ExtractionClient (via FallbackChainClient) to generate a summary.
  4. Compute evidence_hash (SHA-256) for change detection — skip if unchanged.
  5. Insert new summary row (is_current=true), retire old one.
  6. Mark summary_stale=false on the relation.

All LLM calls are logged to llm_usage_log.
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
_SUMMARY_MODEL_ID = "kg-summary-v1"
_PROMPT_TEMPLATE_ID = "00000000-0000-0000-0000-000000000001"  # seeded in prompt_templates


class SummaryWorker:
    """Generates LLM summaries for stale relations (Worker 13C).

    Args:
    ----
        session_factory: Read/write sessionmaker for intelligence_db.
        llm_client:      FallbackChainClient for extraction.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: FallbackChainClient,
    ) -> None:
        self._sf = session_factory
        self._llm = llm_client

    async def run(self) -> None:
        """Generate summaries for stale relations."""
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_evidence import (
            RelationEvidenceRepository,
        )
        from knowledge_graph.infrastructure.intelligence_db.repositories.relation_summary import (
            RelationSummaryRepository,
        )

        summaries_created = 0
        summaries_skipped = 0

        async with self._sf() as session:
            rel_repo = RelationRepository(session)
            ev_repo = RelationEvidenceRepository(session)
            summary_repo = RelationSummaryRepository(session)

            stale_relations = await rel_repo.fetch_stale_summary(_BATCH_LIMIT)  # type: ignore[attr-defined]
            batch_size = len(stale_relations)

            logger.info(  # type: ignore[no-any-return]
                "summary_worker_batch_start",
                stale_relations=batch_size,
            )

            immutable_hits_total = 0
            raw_fallback_hits_total = 0
            skipped_no_evidence = 0
            skipped_null_evidence_text = 0

            for rel in stale_relations:
                relation_id = rel["relation_id"]  # type: ignore[assignment]

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
                if not evidence_rows:
                    skipped_no_evidence += 1
                    continue

                # Track which evidence source contributed
                if evidence_source == "immutable":
                    immutable_hits_total += len(evidence_rows)
                else:
                    raw_fallback_hits_total += len(evidence_rows)

                evidence_texts = [
                    str(e.get("evidence_text", "")) or str(e.get("canonicalized_evidence_text", ""))
                    for e in evidence_rows
                    if e.get("evidence_text") or e.get("canonicalized_evidence_text")
                ]
                null_count = len(evidence_rows) - len(evidence_texts)
                if null_count > 0:
                    logger.warning(  # type: ignore[no-any-return]
                        "summary_worker_null_evidence_text",
                        relation_id=str(relation_id),
                        null_evidence_count=null_count,
                        total_rows=len(evidence_rows),
                        message="evidence_text NULL on pre-migration rows — consider promoting to immutable",
                    )
                if not evidence_texts:
                    skipped_null_evidence_text += 1
                    continue

                # SHA-256 of combined evidence for change detection
                combined = "\n".join(sorted(evidence_texts))
                evidence_hash = hashlib.sha256(combined.encode()).hexdigest()

                existing = await summary_repo.get_current(relation_id)  # type: ignore[arg-type]
                if existing and existing.get("evidence_hash") == evidence_hash:
                    # No change — skip expensive LLM call
                    await rel_repo.mark_summary_updated(relation_id)  # type: ignore[arg-type, attr-defined]
                    await session.commit()
                    summaries_skipped += 1
                    continue

                # Build prompt and call LLM
                summary_text = await self._generate_summary(evidence_texts, relation_id)  # type: ignore[arg-type]
                if summary_text is None:
                    logger.warning(  # type: ignore[no-any-return]
                        "summary_worker_llm_failed",
                        relation_id=str(relation_id),
                    )
                    continue

                await summary_repo.insert_new(
                    relation_id=relation_id,  # type: ignore[arg-type]
                    summary_text=summary_text,
                    evidence_count=len(evidence_texts),
                    evidence_hash=evidence_hash,
                    model_id=_SUMMARY_MODEL_ID,
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
            model_id=_SUMMARY_MODEL_ID,
            template_id=_PROMPT_TEMPLATE_ID,
        )

        result = await self._llm.extract(inp, entity_id=None)
        if result is None:
            return None
        return str(result.result.get("summary", "")) or None
