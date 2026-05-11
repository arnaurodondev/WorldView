"""Use case: fetch all articles belonging to a near-duplicate cluster.

Returns all sibling articles for a given cluster_id so the frontend can show
a "similar articles" drawer when the user clicks the "+N sim" chip.

WHY a use case (not inline in the route): keeps the infrastructure import
(DuplicateClusterRepository, DocumentRepository) out of the API layer
(R25 / IG-LAYER-002).

WHY Protocol (not direct import of the repositories): the architecture guard
(test_ports.py) forbids imports of ``content_store.infrastructure`` inside
application/use_cases/.  Using structural Protocols keeps the use case
infrastructure-independent while still allowing mypy to type-check call sites.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

# ── Data transfer object ───────────────────────────────────────────────────────


@dataclass
class ClusterArticleDTO:
    """Lightweight article summary for the cluster-articles endpoint.

    WHY a separate DTO (not DocumentMetadataDTO): the cluster endpoint also
    needs cluster_id and cluster_size — fields that don't belong on the
    general-purpose DocumentMetadataDTO.
    """

    id: UUID
    title: str | None
    url: str | None
    published_at: datetime | None
    source_name: str | None  # always None — documents table has no source_name column
    cluster_id: UUID
    cluster_size: int  # total rows in duplicate_clusters for this cluster_id


# ── Repository protocols ───────────────────────────────────────────────────────


class ClusterArticlesRepositoryPort(Protocol):
    """Structural protocol for the repository used by GetClusterArticlesUseCase.

    WHY Protocol: avoids an infrastructure import in the application layer.
    The concrete implementation (DuplicateClusterRepository) satisfies this
    protocol structurally — no explicit inheritance required.
    """

    async def get_cluster_article_dtos(self, cluster_id: UUID) -> list[ClusterArticleDTO]:
        """Return all articles in the cluster plus cluster metadata.

        Returns an empty list if the cluster_id does not exist.
        """
        ...


# ── Use case ──────────────────────────────────────────────────────────────────


class GetClusterArticlesUseCase:
    """Fetch all articles in a near-duplicate cluster.

    WHY no UoW: this is a read-only use case (R27); the repository
    receives a read-only session from the dependency injector.
    """

    def __init__(self, repo: ClusterArticlesRepositoryPort) -> None:
        self._repo = repo

    async def execute(self, cluster_id: UUID) -> list[ClusterArticleDTO]:
        """Return all articles in the cluster.

        Args:
            cluster_id: The UUID of the duplicate cluster to look up.

        Returns:
            List of ClusterArticleDTOs.  Empty list if cluster not found.
        """
        return await self._repo.get_cluster_article_dtos(cluster_id)
