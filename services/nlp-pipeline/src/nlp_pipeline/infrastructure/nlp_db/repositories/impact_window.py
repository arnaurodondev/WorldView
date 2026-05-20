"""ArticleImpactWindowRepository — SQLAlchemy implementation (PRD-0026 §6.5)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.application.ports.repositories import ArticleImpactWindowRepositoryPort
from nlp_pipeline.infrastructure.nlp_db.models import ArticleImpactWindowModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import ArticleImpactWindow


class ArticleImpactWindowRepository(ArticleImpactWindowRepositoryPort):
    """SQLAlchemy-backed implementation of :class:`ArticleImpactWindowRepositoryPort`.

    Caller (UoW or worker) is responsible for ``commit()``.
    This class only calls ``execute()`` -- never ``commit()``.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_batch(self, windows: list[ArticleImpactWindow]) -> None:
        """Bulk INSERT ON CONFLICT (article_id, entity_id, window_type, model_id, prompt_version) DO NOTHING.

        PLAN-0055 C-1 swapped the legacy 3-column UNIQUE INDEX
        (``idx_article_impact_windows_unique``) for the 5-column UNIQUE
        CONSTRAINT ``uq_article_impact_windows_dedup`` so two different label
        models can both score the same (article, entity, window). Provenance
        columns get deterministic non-NULL defaults — Postgres treats NULL as
        not-equal-to-anything in UNIQUE checks, so NULL provenance would defeat
        the dedup guard.

        Idempotent (R9): duplicate 5-tuples are silently ignored.
        """
        if not windows:
            return

        # Stable provenance defaults for the labelling-worker lineage. Bumping
        # ``label_prompt_version`` retroactively makes future runs eligible to
        # write a fresh row per (article, entity, window) without trampling history.
        import hashlib

        label_model_id = "price-impact-labeller-v1"
        label_prompt_version = "v1"

        def _input_hash(article_id: UUID, entity_id: UUID, window_type: str) -> str:
            payload = f"{article_id}|{entity_id}|{window_type}".encode()
            return hashlib.sha256(payload).hexdigest()

        values = [
            {
                "id": w.id,
                "article_id": w.article_id,
                "entity_id": w.entity_id,
                "symbol": w.symbol,
                "published_at": w.published_at,
                "window_type": str(w.window_type),
                "window_start": w.window_start,
                "window_end": w.window_end,
                "price_start": w.price_start,
                "price_end": w.price_end,
                "delta_pct": w.delta_pct,
                "high_pct": w.high_pct,
                "low_pct": w.low_pct,
                "volume": w.volume,
                "impact_score": w.impact_score,
                "normalisation_cap_pct": w.normalisation_cap_pct,
                "data_quality": str(w.data_quality),
                "model_id": label_model_id,
                "prompt_version": label_prompt_version,
                "input_hash": _input_hash(w.article_id, w.entity_id, str(w.window_type)),
                # computed_at gets server_default (now()) when not supplied
            }
            for w in windows
        ]

        stmt = (
            pg_insert(ArticleImpactWindowModel)
            .values(values)
            .on_conflict_do_nothing(constraint="uq_article_impact_windows_dedup")
        )
        await self._session.execute(stmt)

    async def get_articles_needing_windows(
        self,
        min_age_hours: int,
        batch_size: int,
    ) -> list[tuple[UUID, UUID, str, datetime]]:
        """Return (doc_id, entity_id, symbol, published_at) for article/entity pairs
        that are missing at least one of their expected daily windows.

        Logic (PRD-0026 §6.7 Flow A Phase 1):
          - Article must be old enough (published_at < now() - min_age_hours)
          - Must have a resolved financial_instrument mention
          - Must be missing at least one day_t0 row in article_impact_windows
            (day_t0 is required for ALL labelled articles; t1/t2/t5 are added later)
          - Must NOT be SUPPRESS-tier (W1-02, BUG-002): joined against
            ``routing_decisions`` and filtered to ``processing_path != 'halt'``.
            See inline comment in the SQL below for the NULL-fallback rationale.
        """
        stmt = text(
            """
            WITH candidate_docs AS (
                SELECT DISTINCT em.doc_id
                FROM entity_mentions em
                JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
                -- W1-02 (BUG-002): JOIN routing_decisions so we can filter out
                -- SUPPRESS-tier articles. Without this join, the price-impact
                -- labelling worker was happily computing windows for HALT-path
                -- documents and the resulting impact scores fed back into the
                -- composite routing score for any future article citing the
                -- same instrument — a noise-amplifying feedback loop.
                JOIN routing_decisions rd ON rd.doc_id = em.doc_id
                WHERE em.resolved_entity_id IS NOT NULL
                  AND em.mention_class = 'financial_instrument'
                  AND dsm.published_at IS NOT NULL
                  AND dsm.published_at < now() - make_interval(hours => :min_age_hours)
                  -- W1-02 (BUG-002): exclude SUPPRESS-tier articles. The
                  -- ``processing_path`` column (added in migration 0015) is
                  -- the canonical suppression-gate output and is set to
                  -- 'halt' for any article whose final path is
                  -- ``ProcessingPath.HALT``. Legacy rows written before the
                  -- migration have NULL here; we treat NULL as "non-suppress"
                  -- so we do not accidentally exclude valid pre-migration
                  -- articles (defensive fallback — those rows pre-date the
                  -- bug anyway and will age out via the multi-window TTL).
                  AND (rd.processing_path IS NULL OR rd.processing_path != 'halt')
                  AND NOT EXISTS (
                      SELECT 1 FROM article_impact_windows aiw
                      WHERE aiw.article_id = em.doc_id
                        AND aiw.entity_id  = em.resolved_entity_id
                        AND aiw.window_type = 'day_t0'
                  )
                LIMIT :batch_size
            )
            SELECT em.doc_id,
                   em.resolved_entity_id AS entity_id,
                   em.mention_text       AS symbol,
                   dsm.published_at
            FROM entity_mentions em
            JOIN document_source_metadata dsm ON dsm.doc_id = em.doc_id
            JOIN candidate_docs cd           ON cd.doc_id = em.doc_id
            WHERE em.resolved_entity_id IS NOT NULL
              AND em.mention_class = 'financial_instrument'
              AND dsm.published_at IS NOT NULL
            ORDER BY em.doc_id
            """
        ).bindparams(min_age_hours=min_age_hours, batch_size=batch_size)

        result = await self._session.execute(stmt)
        rows = result.all()
        return [(row.doc_id, row.entity_id, row.symbol, row.published_at) for row in rows]

    async def get_max_impact_for_doc(self, doc_id: UUID) -> Decimal:
        """Return max ``impact_score`` across all windows and entities for ``doc_id``.

        Returns ``Decimal("0.0")`` when no windows exist yet.
        Used by Block 5 (signal scoring) inside the article consumer.
        """
        result = await self._session.execute(
            sa.select(func.max(ArticleImpactWindowModel.impact_score)).where(
                ArticleImpactWindowModel.article_id == doc_id
            )
        )
        val = result.scalar_one_or_none()
        return Decimal(str(val)) if val is not None else Decimal("0.0")
