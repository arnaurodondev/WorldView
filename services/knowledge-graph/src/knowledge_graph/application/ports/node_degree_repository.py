"""Port interface for the node-degree / graph-stats repository (PLAN-0112 T-3-02).

The connection-discovery redesign scores each path's ``unexpectedness`` (the
hub-demoting term) from the graph's per-vertex degree.  Recomputing degree per
query is wasteful, so the AGE-sync worker materialises it once per cycle into the
``node_degree`` table (and a single-row ``graph_stats`` normaliser) via this
write port.  The ``WeirdnessScorer`` consumes the result through pure lookups
built from the read methods here.

Architecture (R25): this is an application-layer port (ABC).  The AGE-sync
worker depends on this abstraction, never on the concrete asyncpg repository.

No infrastructure imports permitted (R12) — only stdlib + domain.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True)
class GraphStats:
    """Single-row graph-wide normaliser store (the ``2m`` term + max degree).

    ``total_edges`` is the configuration-model normaliser ``m`` (so ``2m`` =
    ``2 * total_edges``); ``total_meaningful_edges`` is the same count after
    membership edges are excluded; ``max_degree`` is the highest single-vertex
    degree (diagnostics / future normalisation).
    """

    total_edges: int
    total_meaningful_edges: int
    max_degree: int
    refreshed_at: datetime | None = None


class NodeDegreeRepositoryPort(ABC):
    """Materialise + read per-vertex degree and graph-wide stats (FR-5)."""

    @abstractmethod
    async def refresh_from_age(self) -> GraphStats:
        """Recompute degree + meaningful-degree from the AGE edge table and upsert.

        Aggregates the undirected degree of every vertex from
        ``worldview_graph._ag_label_edge`` (joining the internal graphids back to
        the ``entity`` vertices' ``entity_id`` property), and a *meaningful*
        degree that excludes ``MEMBERSHIP_RELATIONS`` edge labels.  Upserts every
        vertex row into ``node_degree`` and the single ``graph_stats`` row.

        Returns the freshly-computed :class:`GraphStats` (so the caller can log /
        emit metrics without an extra read).
        """
        ...

    @abstractmethod
    async def get_degree_map(self) -> dict[UUID, tuple[int, int]]:
        """Return ``{entity_id: (degree, degree_meaningful)}`` for every vertex.

        Used by the discovery worker to build the pure ``degree_of`` /
        ``meaningful_degree_of`` lookups injected into the ``WeirdnessScorer``.
        """
        ...

    @abstractmethod
    async def get_graph_stats(self) -> GraphStats | None:
        """Return the single ``graph_stats`` row, or ``None`` if never refreshed."""
        ...
