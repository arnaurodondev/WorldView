"""Use case: batch cluster-size and cluster-id lookup for near-duplicate awareness.

Returns the number of near-duplicate siblings detected for each requested
doc_id, and one cluster_id per doc_id (for docs in a cluster).  Used by the
API gateway enrichment path to add ``cluster_size`` and ``cluster_id``
to ranked article responses (SA-4, news density redesign).

WHY a use case (not inline in the route): keeps the infrastructure import
(DuplicateClusterRepository) out of the API layer (R25 / IG-LAYER-002).

WHY Protocol (not direct import of DuplicateClusterRepository): the
architecture guard (test_ports.py) forbids imports of
``content_store.infrastructure`` inside application/use_cases/.  Using
a structural Protocol keeps the use case infrastructure-independent while
still allowing mypy to type-check call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass
class ClusterSizeAndIdResult:
    """Result bundle for a single doc_id's cluster enrichment data.

    WHY a dataclass (not a tuple): named fields make it impossible to
    accidentally swap cluster_size and cluster_id in the API layer.
    """

    cluster_size: int
    cluster_id: UUID | None  # None when doc is alone (cluster_size=1)


class ClusterSizeRepositoryPort(Protocol):
    """Structural protocol for the DuplicateClusterRepository read method.

    WHY Protocol: avoids an infrastructure import in the application layer.
    The concrete implementation (DuplicateClusterRepository) satisfies this
    protocol structurally — no explicit inheritance required.
    """

    async def get_cluster_sizes(self, doc_ids: list[UUID]) -> dict[UUID, int]:
        """Return cluster size per doc_id (1 = no duplicates)."""
        ...

    async def get_cluster_ids(self, doc_ids: list[UUID]) -> dict[UUID, UUID]:
        """Return one cluster_id per doc_id for docs in a cluster (absent = no cluster)."""
        ...


class BatchClusterSizesUseCase:
    """Return cluster sizes for a batch of document IDs.

    A cluster size of 1 means the document has no detected near-duplicates.
    A size of N (N > 1) means there are N-1 near-duplicate siblings.

    Accepts at most 100 doc_ids per call (hard limit to cap query size).
    """

    MAX_BATCH = 100

    def __init__(self, repo: ClusterSizeRepositoryPort) -> None:
        # WHY no UoW: this is a read-only use case (R27); the repository
        # receives a read-only session from the dependency injector.
        self._repo = repo

    async def execute(self, doc_ids: list[UUID]) -> dict[UUID, ClusterSizeAndIdResult]:
        """Return cluster size and cluster_id per doc_id.

        Args:
            doc_ids: Batch of document UUIDs (max 100).

        Returns:
            Mapping of doc_id → ClusterSizeAndIdResult.  Every requested
            doc_id is present in the output; docs with no duplicates have
            cluster_size=1 and cluster_id=None.

        Raises:
            ValueError: if more than MAX_BATCH doc_ids are requested.
        """
        if len(doc_ids) > self.MAX_BATCH:
            raise ValueError(f"batch size {len(doc_ids)} exceeds maximum {self.MAX_BATCH}")
        # Fetch sizes and cluster_ids in parallel — both are cheap index scans.
        sizes = await self._repo.get_cluster_sizes(doc_ids)
        cluster_ids = await self._repo.get_cluster_ids(doc_ids)
        return {
            doc_id: ClusterSizeAndIdResult(
                cluster_size=sizes.get(doc_id, 1),
                cluster_id=cluster_ids.get(doc_id),
            )
            for doc_id in doc_ids
        }
