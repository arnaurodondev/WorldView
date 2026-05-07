"""ChunkSearchPort — abstract port for ANN and lexical chunk search.

R25: use cases depend on this ABC; the concrete ``ChunkANNRepository``
(``infrastructure/nlp_db/repositories/chunk_search.py``) implements it.
DI in ``api/dependencies.py`` wires the concrete class at runtime.

This module contains only the ABC definition. Infrastructure imports are
strictly forbidden here — the port sits at the application layer boundary.

PLAN-0084 D-1: extracted from ``application/ports/repositories.py`` into its
own module so that the ABC can be imported without loading the entire
repository-port bundle. ``repositories.py`` re-exports ``ChunkSearchPort`` for
backward compatibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class ChunkSearchPort(ABC):
    """Port for ANN and lexical chunk search with optional entity filtering.

    R25 — use cases depend on this ABC; concrete ``ChunkANNRepository``
    implements it.  DI in ``api/dependencies.py`` wires the concrete class.

    All filter parameters are additive (AND semantics across parameters;
    OR semantics within list-typed parameters per PLAN-0078 §3).
    """

    @abstractmethod
    async def ann_search(
        self,
        embedding: list[float],
        granularity: str,
        top_k: int,
        min_score: float,
        date_from: Any | None,
        date_to: Any | None,
        source_types: list[str] | None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run HNSW ANN search; return (results, total_searched)."""
        ...

    @abstractmethod
    async def lexical_search(
        self,
        query_text: str,
        *,
        mode: str = "both",
        granularity: str = "chunk",
        top_k: int = 20,
        min_score: float = 0.0,
        date_from: Any | None = None,
        date_to: Any | None = None,
        source_types: list[str] | None = None,
        entity_ids: list[UUID] | None = None,
        entity_types: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Run Postgres full-text search; return (results, total_searched).

        ``mode`` is one of ``"english"`` (stemmed), ``"simple"``
        (no stemming — preserves identifiers like ``AAPL``), or
        ``"both"`` (GREATEST of the two ranks, default).

        ``granularity`` defaults to ``"chunk"``; section-level lexical
        retrieval is deferred to a future wave.
        """
        ...

    @abstractmethod
    async def fetch_entity_mentions(
        self,
        chunk_ids: list[UUID],
        min_confidence: float,
    ) -> list[dict[str, Any]]:
        """Fetch resolved entity mentions for the given chunk_ids.

        Returns rows with: chunk_id, resolved_entity_id, resolution_confidence.
        Only mentions with ``resolved_entity_id IS NOT NULL`` and
        ``resolution_confidence >= min_confidence`` are returned.
        """
        ...
