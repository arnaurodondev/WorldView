"""Port interface for source adapters — application layer boundary.

Concrete adapters in the infrastructure layer implement this ABC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from content_ingestion.domain.entities import FetchResult, Source


class SourceAdapterPort(ABC):
    """Abstract interface for external content source adapters."""

    @abstractmethod
    async def fetch(self, source: Source, *, is_backfill: bool = False) -> list[FetchResult]:
        """Fetch articles from the external source.

        Args:
            source: The configured polling source with API config.
            is_backfill: Whether this is a historical backfill run.

        Returns:
            List of FetchResult objects for new (non-duplicate) articles.
        """
