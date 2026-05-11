"""LLMScoreRepository port — append-only LLM provenance ledger (PLAN-0055 C-2).

The application layer depends on this Protocol; the infrastructure layer
implements it against ``document_source_llm_scores``. Workers use the port to
record every LLM scoring decision with full provenance (model_id, prompt_version,
input_hash) so that:

  - Re-scoring with a new model preserves prior history (audit trail).
  - The replay endpoint (Wave C-4) can target a specific model+prompt without
    overwriting unrelated scores.
  - The materialized view (Wave C-3) projects "latest score per (doc, type)"
    deterministically by ``generated_at DESC``.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class LLMScoreRepository(Protocol):
    """Port for append-only LLM scoring writes."""

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
        """INSERT a score row.

        Returns ``True`` when a new row was inserted, ``False`` when the same
        ``(doc_id, score_type, model_id, prompt_version)`` tuple already exists
        (silently deduped via ON CONFLICT DO NOTHING — the prior row is the
        canonical record for that combination).
        """
        ...

    async def exists(
        self,
        *,
        doc_id: UUID,
        score_type: str,
        model_id: str,
        prompt_version: str,
        input_hash: str,
    ) -> bool:
        """Whether this exact (doc, type, model, prompt, hash) combination has been scored.

        Used by workers as a cheap pre-flight check to skip the LLM call entirely
        when the result is already on disk.
        """
        ...
