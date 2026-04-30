"""SQLAlchemy implementation of ``LLMScoreRepository`` (PLAN-0055 C-2).

INSERT ON CONFLICT DO NOTHING gives us idempotent appends keyed on
``(doc_id, score_type, model_id, prompt_version)``. ``rowcount`` distinguishes
new inserts from deduped no-ops so callers can avoid wasted LLM calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlaLLMScoreRepository:
    """Concrete repository writing to ``document_source_llm_scores``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        doc_id: UUID,
        score_type: str,
        score_value: float | None,
        score_label: str | None,
        model_id: str,
        prompt_version: str,
        input_hash: str,
    ) -> bool:
        # ON CONFLICT targets uq_dsls_dedup, the named UNIQUE on the
        # (doc_id, score_type, model_id, prompt_version) tuple. DO NOTHING
        # keeps the operation a single statement (BP-007) and the rowcount
        # distinguishes "first write" (1) from "already there" (0).
        stmt = text(
            """
            INSERT INTO document_source_llm_scores
                (doc_id, score_type, score_value, score_label,
                 model_id, prompt_version, input_hash)
            VALUES
                (:doc_id, :score_type, :score_value, :score_label,
                 :model_id, :prompt_version, :input_hash)
            ON CONFLICT ON CONSTRAINT uq_dsls_dedup DO NOTHING
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "doc_id": str(doc_id),
                "score_type": score_type,
                "score_value": score_value,
                "score_label": score_label,
                "model_id": model_id,
                "prompt_version": prompt_version,
                "input_hash": input_hash,
            },
        )
        # ``rowcount`` lives on CursorResult (which Result extends for DML execute);
        # mypy's narrow Result type doesn't expose it, so we read defensively.
        # IMPORTANT: ``getattr(mock, "rowcount", default)`` returns a MagicMock
        # (auto-created truthy attribute), not the default — so ``or 0`` is not
        # enough. Coerce to int and fall through to 0 on any non-int value.
        raw = getattr(result, "rowcount", 0)
        rowcount = raw if isinstance(raw, int) else 0
        return rowcount > 0

    async def exists(
        self,
        *,
        doc_id: UUID,
        score_type: str,
        model_id: str,
        prompt_version: str,
        input_hash: str,
    ) -> bool:
        stmt = text(
            """
            SELECT 1 FROM document_source_llm_scores
            WHERE doc_id = :doc_id
              AND score_type = :score_type
              AND model_id = :model_id
              AND prompt_version = :prompt_version
              AND input_hash = :input_hash
            LIMIT 1
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "doc_id": str(doc_id),
                "score_type": score_type,
                "model_id": model_id,
                "prompt_version": prompt_version,
                "input_hash": input_hash,
            },
        )
        return result.scalar() is not None
