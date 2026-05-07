"""S6 NLP Pipeline HTTP client adapter (T-E-3-01).

Endpoints:
  POST /api/v1/entities/resolve  → entity resolution
  POST /api/v1/search/chunks     → ANN chunk search
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from rag_chat.application.ports.upstream_clients import ChunkSearchRequest, EnrichedChunkResult
from rag_chat.domain.entities.chat import ResolvedEntity
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

if TYPE_CHECKING:
    from uuid import UUID


class S6Client(BaseUpstreamClient):
    """Concrete HTTP adapter for S6 NLP Pipeline."""

    # ── Entity resolution ──────────────────────────────────────────────────────

    async def resolve_entities(self, query_text: str) -> list[ResolvedEntity]:
        """POST /api/v1/entities/resolve → list of resolved entities.

        Returns an empty list on timeout or HTTP error (safe degradation).
        """
        raw = await self._post(
            "/api/v1/entities/resolve",
            {"query_text": query_text},
        )
        entities: list[dict] = raw.get("entities", [])
        results: list[ResolvedEntity] = []
        for item in entities:
            try:
                entity_id: UUID = item["entity_id"]  # type: ignore[assignment]
                results.append(
                    ResolvedEntity(
                        entity_id=entity_id,
                        canonical_name=item.get("canonical_name", ""),
                        entity_type=item.get("entity_type", ""),
                        confidence=float(item.get("confidence", 0.0)),
                        matched_text=item.get("matched_text", ""),
                        ticker=item.get("ticker"),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    # ── Chunk search ───────────────────────────────────────────────────────────

    async def search_chunks(self, request: ChunkSearchRequest) -> list[EnrichedChunkResult]:
        """POST /api/v1/search/chunks → ranked enriched chunk results.

        Returns an empty list on timeout or HTTP error (safe degradation, R9).
        """
        payload: dict = {
            "top_k": request.top_k,
            "min_score": request.min_score,
            "granularity": request.granularity,
            "include_entities": request.include_entities,
            "source_types": request.source_types,
            # PLAN-0063 W5-3: forward the orchestrator's search_type choice
            # over the wire. S6 validates the literal set; the port stayed
            # loose so older callers (set to "ann") keep working unchanged.
            "search_type": request.search_type,
        }
        if request.query_text is not None:
            payload["query_text"] = request.query_text
        # Truthy check: empty list [] means embed failed → omit field so
        # query_text fallback path is used (prevents 422 from nlp-pipeline
        # ChunkSearchRequest "exactly_one_query" validator). BP-183 fix.
        if request.query_embedding:
            payload["query_embedding"] = request.query_embedding
        if request.date_from is not None:
            payload["date_from"] = request.date_from.date().isoformat()
        if request.date_to is not None:
            payload["date_to"] = request.date_to.date().isoformat()

        raw = await self._post("/api/v1/search/chunks", payload)
        results_raw: list[dict] = raw.get("results", [])
        results: list[EnrichedChunkResult] = []
        for item in results_raw:
            try:
                meta: dict = item.get("source_metadata", {})
                published_at = None
                if meta.get("published_at"):
                    from datetime import datetime

                    published_at = datetime.fromisoformat(meta["published_at"].replace("Z", "+00:00")).replace(
                        tzinfo=UTC
                    )
                results.append(
                    EnrichedChunkResult(
                        chunk_id=item["chunk_id"],
                        doc_id=item["doc_id"],
                        text=item.get("text", ""),
                        score=float(item.get("score", 0.0)),
                        source_type=meta.get("source_type", ""),
                        title=meta.get("title"),
                        url=meta.get("url"),
                        published_at=published_at,
                        source_name=meta.get("source_name"),
                        section_id=item.get("section_id"),
                        granularity=item.get("granularity", "chunk"),
                        section_type=item.get("section_type"),
                        heading_path=item.get("heading_path"),
                        entities=item.get("entities", []),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results
