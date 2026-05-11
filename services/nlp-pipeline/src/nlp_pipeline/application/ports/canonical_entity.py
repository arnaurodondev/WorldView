"""CanonicalEntityPort — abstract port for canonical entity read/create operations.

R25: use cases depend on this ABC; the concrete ``CanonicalEntityRepository``
(``infrastructure/intelligence_db/repositories/canonical_entity.py``) implements it.

This module contains only the ABC definition. Infrastructure imports are
strictly forbidden here — the port sits at the application layer boundary.

PLAN-0084 D-2: extracted so that application-layer use cases (e.g.
``EnhancedChunkSearchUseCase``, ``QueryEntityResolverUseCase``) and blocks
(``entity_resolution``) depend on this interface rather than importing the
concrete infrastructure class directly.

Methods lifted from ``CanonicalEntityRepository`` (verified 2026-05-07):
  - ``get`` — single-entity fetch by ID
  - ``batch_get`` — multi-entity fetch by ID list
  - ``create`` — insert new canonical entity
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class CanonicalEntityPort(ABC):
    """Port for canonical entity read/create in intelligence_db.

    Read methods are used by:
      - ``EnhancedChunkSearchUseCase._enrich_raw_results`` (``batch_get``)
      - ``QueryEntityResolverUseCase.execute`` stages 1-4 (``get``)

    Write method is used by:
      - ``ArticleProcessingConsumer`` / ``run_entity_resolution_block`` (``create``)
    """

    @abstractmethod
    async def get(self, entity_id: UUID) -> dict[str, object] | None:
        """Fetch a canonical entity by ID.

        Returns a dict with keys: entity_id, canonical_name, entity_type,
        isin, ticker, exchange.  Returns ``None`` when not found.
        """
        ...

    @abstractmethod
    async def batch_get(self, entity_ids: list[UUID]) -> dict[UUID, dict[str, object]]:
        """Fetch multiple canonical entities by ID in a single query.

        Returns a dict keyed by entity_id; missing IDs are omitted.
        """
        ...

    @abstractmethod
    async def create(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        isin: str | None = None,
        ticker: str | None = None,
        exchange: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> UUID:
        """Insert a new canonical entity and return its ID."""
        ...
