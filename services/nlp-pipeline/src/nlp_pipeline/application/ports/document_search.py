"""Port interface for full-text document search (PLAN-0064 W6).

R12: this module is at the application layer boundary — no infrastructure
imports (no sqlalchemy, no asyncpg, no httpx). Concrete implementations live
under infrastructure/nlp_db/repositories/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from nlp_pipeline.api.schemas import (
        SearchDocumentResult,
        SearchDocumentsFacet,
        SearchDocumentsRequest,
    )


class DocumentSearchRepositoryPort(ABC):
    """Abstract repository for full-text document search.

    Pure interface — no SQL, no asyncpg, no SQLAlchemy imports.
    search() returns snippet_marked (with \\x02/\\x03 sentinel bytes).
    Snippet post-processing (bytes → plain text + offsets) happens in the use case.
    """

    @abstractmethod
    async def search(self, request: SearchDocumentsRequest) -> tuple[list[SearchDocumentResult], int]:
        """Execute FTS query. Returns (results_with_raw_snippets, total_count).

        results_with_raw_snippets have snippet field containing sentinel-marked text.
        The use case calls _strip_markers() to convert to plain text + offsets.
        """
        ...

    @abstractmethod
    async def facets(self, request: SearchDocumentsRequest, hit_doc_ids: list[UUID]) -> list[SearchDocumentsFacet]:
        """Return top 25 entity facets for the given hit doc_ids (name field left empty).

        Entity names must be filled in by the use case via S7 batch HTTP.
        """
        ...
