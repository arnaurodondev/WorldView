"""Port interfaces for PathInsight and PathInsightJob repositories (T-E1-02).

Use cases depend only on these ABCs — no infrastructure imports permitted.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from knowledge_graph.domain.entities.path_insight import PathInsight, PathInsightJob


class PathInsightJobRepositoryPort(ABC):
    """Write-oriented job queue for PathInsightWorker (SKIP LOCKED claim pattern)."""

    @abstractmethod
    async def claim_batch(
        self,
        instance_uuid: UUID,
        batch_size: int = 10,
    ) -> list[PathInsightJob]:
        """Atomically claim up to ``batch_size`` pending jobs for this worker instance.

        Uses ``FOR UPDATE SKIP LOCKED`` so concurrent workers claim disjoint sets.
        Only jobs with ``retry_count < 3`` and ``status='pending'`` are eligible.
        """
        ...

    @abstractmethod
    async def mark_done(self, job_id: UUID, paths_found: int) -> None:
        """Transition a job to ``done``, recording the number of paths written."""
        ...

    @abstractmethod
    async def mark_failed(self, job_id: UUID, error_text: str) -> str | None:
        """Transition a job on failure.

        - ``retry_count < 3`` → increment retry_count, reset to ``pending``,
          clear ``claimed_by``.
        - ``retry_count == 3`` → set ``status='failed'`` (terminal).

        Returns the resulting status ('failed' on the terminal transition,
        otherwise 'pending'; ``None`` if the job_id was not found) so callers can
        emit ``path_jobs_failed_total`` only on the terminal transition
        (PLAN-0112 T-1-03).
        """
        ...

    @abstractmethod
    async def reclaim_stuck(self, timeout_seconds: int = 600) -> int:
        """Reset jobs stuck in ``running`` for longer than ``timeout_seconds``.

        Returns the count of reclaimed rows (BP-112 pattern).
        """
        ...

    @abstractmethod
    async def insert_pending(self, entity_id: UUID) -> bool:
        """Insert a pending job for the given entity, idempotently.

        Returns True if a new row was inserted, False if one already existed
        (``uq_path_insight_jobs_active`` partial unique index fires).
        """
        ...


class PathInsightRepositoryPort(ABC):
    """Read/write access to ``path_insights`` rows."""

    @abstractmethod
    async def replace_for_anchor(
        self,
        anchor_entity_id: UUID,
        insights: list[PathInsight],
    ) -> None:
        """Delete all existing insights for ``anchor_entity_id`` then bulk-insert
        ``insights`` in a single transaction (no N+1).
        """
        ...

    @abstractmethod
    async def list_by_anchor(
        self,
        anchor_entity_id: UUID,
        *,
        limit: int = 50,
        min_score: float = 0.0,
        min_hops: int = 2,
        max_hops: int = 5,
    ) -> list[PathInsight]:
        """Return insights for ``anchor_entity_id`` ordered by composite_score DESC."""
        ...

    @abstractmethod
    async def list_global_weird(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        min_weirdness: float = 0.0,
        since_days: int | None = None,
        entity_type: str | None = None,
    ) -> list[PathInsight]:
        """Return the globally most-weird path insights (PLAN-0112 W5, T-5-01).

        Rows where ``weirdness IS NOT NULL`` ordered by ``weirdness`` DESC.
        Filters:
          - ``min_weirdness``: only paths with ``weirdness >= min_weirdness``.
          - ``since_days``: only paths with a *recent* edge — approximated by
            ``novelty > 0`` (the scorer already computed the recent-edge
            fraction, so ``novelty > 0`` ⇔ at least one edge inside the novelty
            window).  ``since_days`` itself is validated by the caller; the
            value is not re-applied here because the recency window is fixed at
            scorer time.
          - ``entity_type``: only paths whose anchor OR dst endpoint canonical
            entity matches the given ``entity_type``.

        Deduplicated to distinct (anchor, dst) endpoint pairs keeping the
        single best (highest weirdness) row per pair (OQ-6 default).  Pagination
        (``limit`` / ``offset``) is applied AFTER dedup.
        """
        ...

    @abstractmethod
    async def update_explanation(
        self,
        insight_id: UUID,
        llm_explanation: str,
        explanation_model: str,
    ) -> None:
        """Persist the LLM-generated explanation for an insight (Wave E2)."""
        ...
