"""Use case: batch cluster-size lookup for near-duplicate awareness.

Returns the number of near-duplicate siblings detected for each requested
doc_id.  Used by the API gateway enrichment path to add ``cluster_size``
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

from typing import Protocol
from uuid import UUID


class ClusterSizeRepositoryPort(Protocol):
    """Structural protocol for the DuplicateClusterRepository read method.

    WHY Protocol: avoids an infrastructure import in the application layer.
    The concrete implementation (DuplicateClusterRepository) satisfies this
    protocol structurally — no explicit inheritance required.
    """

    async def get_cluster_sizes(self, doc_ids: list[UUID]) -> dict[UUID, int]:
        """Return cluster size per doc_id (1 = no duplicates)."""
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

    async def execute(self, doc_ids: list[UUID]) -> dict[UUID, int]:
        """Return cluster size per doc_id.

        Args:
            doc_ids: Batch of document UUIDs (max 100).

        Returns:
            Mapping of doc_id → cluster size.  Every requested doc_id is
            present in the output; docs with no duplicates map to 1.

        Raises:
            ValueError: if more than MAX_BATCH doc_ids are requested.
        """
        if len(doc_ids) > self.MAX_BATCH:
            raise ValueError(f"batch size {len(doc_ids)} exceeds maximum {self.MAX_BATCH}")
        return await self._repo.get_cluster_sizes(doc_ids)
