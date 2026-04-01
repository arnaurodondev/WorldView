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
    async def fetch(self, source: Source, *, is_backfill: bool = False, from_date: str = "") -> list[FetchResult]:
        """Fetch articles from the external source.

        Args:
            source: The configured polling source with API config.
            is_backfill: Whether this is a historical backfill run.
            from_date: Optional date (YYYY-MM-DD) to start fetching from.
                Overrides source.config["from_date"] when provided (e.g. from watermarks).

        Returns:
            List of FetchResult objects for new (non-duplicate) articles.
        """
