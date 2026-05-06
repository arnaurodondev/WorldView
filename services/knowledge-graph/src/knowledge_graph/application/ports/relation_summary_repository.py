"""Port interface for relation summary reads and writes (Wave C-3 + PLAN-0072).

Use cases depend only on this ABC — never on infrastructure classes directly.
No infrastructure imports are permitted in this module.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID

# ── Value objects ─────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class RelationSummarySearchResult:
    """A single relation returned by the ANN search use case.

    ``summary_authority`` is computed in Python as
    ``confidence * log1p(evidence_count)`` — it is NOT a stored DB column.
    """

    relation_id: UUID
    subject_entity_id: UUID
    object_entity_id: UUID
    subject_canonical_name: str
    object_canonical_name: str
    canonical_type: str
    summary: str
    confidence: float
    evidence_count: int
    latest_evidence_at: datetime | None
    semantic_mode: str
    summary_authority: float


# ── Port ──────────────────────────────────────────────────────────────────────


class RelationSummaryRepositoryPort(ABC):
    """Read and write access to ``relation_summaries`` (ANN search + SummaryWorker writes)."""

    @abstractmethod
    async def get_current(self, relation_id: UUID) -> dict[str, Any] | None:
        """Fetch the current summary for a relation (is_current=true).

        Returns a dict with keys: summary_id, summary_text, evidence_count,
        evidence_hash, model_id, prompt_template_id, generated_at, generation_trigger.
        Returns None when no current summary exists.
        """

    @abstractmethod
    async def insert_new(
        self,
        relation_id: UUID,
        summary_text: str,
        evidence_count: int,
        evidence_hash: str,
        model_id: str,
        prompt_template_id: UUID,
        generation_trigger: str,
    ) -> UUID:
        """Insert a new current summary, retiring any previous one.

        Returns the new summary_id.
        Must run inside a single transaction: set old is_current=false, then insert new.
        """

    @abstractmethod
    async def update_embedding(
        self,
        summary_id: UUID,
        embedding: list[float],
        model_id: str,
        embedded_at: datetime,
    ) -> None:
        """Persist a computed embedding for an existing summary row (Worker 13F).

        Wave A-2 / DEF-022: ``model_id`` and ``embedded_at`` are persisted to
        ``summary_embedding_model_id`` and ``summary_last_embedded_at`` so the
        ANN index can be audited for mixed-model drift and re-embedded
        selectively.
        """

    @abstractmethod
    async def search_by_embedding(
        self,
        query_embedding: list[float],
        *,
        entity_ids: list[UUID] | None = None,
        min_confidence: float = 0.30,
        relation_types: list[str] | None = None,
        semantic_mode: str | None = None,
        top_k: int = 15,
    ) -> list[RelationSummarySearchResult]: ...

    @abstractmethod
    async def get_current_summaries_batch(
        self,
        relation_ids: list[UUID],
    ) -> dict[UUID, str | None]:
        """Return the current summary_text per relation in a single WHERE relation_id = ANY(:ids) query.

        Only rows with is_current=true are returned.  Missing relation_ids are absent from the dict.
        # TODO(PRD-0074): upgrade to a denormalized current_summary_text scalar column on relations
        """
