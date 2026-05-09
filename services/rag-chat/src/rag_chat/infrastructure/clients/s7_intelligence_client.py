"""S7 Intelligence HTTP client adapter — calls S9-proxied intelligence endpoints (PLAN-0080 Wave A).

WHY S9-proxied (not S7 direct): R14/R7 — all internal service-to-service calls go through
the public gateway (S9) for the intelligence endpoints, which apply auth and rate limiting.

Endpoints (via S9 proxy):
  GET /api/v1/entities/{id}/narratives   → latest entity narrative
  GET /api/v1/entities/{id}/paths        → top-N multi-hop paths
  GET /api/v1/entities/{id}/intelligence → full intelligence bundle
"""

from __future__ import annotations

from uuid import UUID

from rag_chat.application.ports.upstream_clients import (
    EntityIntelligenceResult,
    EntityPathsResult,
    NarrativeResult,
)
from rag_chat.infrastructure.clients.base import BaseUpstreamClient


class S7IntelligenceClient(BaseUpstreamClient):
    """Concrete HTTP adapter for S9-proxied S7 intelligence endpoints."""

    async def get_narrative(self, entity_id: UUID) -> NarrativeResult | None:
        """GET /api/v1/entities/{id}/narratives → latest narrative."""
        raw = await self._get(f"/api/v1/entities/{entity_id}/narratives")
        if not raw:
            return None
        try:
            return NarrativeResult(
                entity_id=str(entity_id),
                content=raw.get("content") or raw.get("narrative") or raw.get("text") or "",
                version=int(raw.get("version", 1)),
                generated_at=raw.get("generated_at"),
            )
        except (KeyError, TypeError, ValueError):
            return None

    async def get_entity_paths(self, entity_id: UUID, top_n: int = 5) -> EntityPathsResult:
        """GET /api/v1/entities/{id}/paths → top-N multi-hop paths."""
        raw = await self._get(
            f"/api/v1/entities/{entity_id}/paths",
            params={"top_n": top_n},
        )
        if not raw:
            return EntityPathsResult(entity_id=str(entity_id))
        try:
            paths = raw.get("paths") or []
            return EntityPathsResult(
                entity_id=str(entity_id),
                paths=paths[:top_n],
                total_paths=int(raw.get("total", len(paths))),
            )
        except (KeyError, TypeError, ValueError):
            return EntityPathsResult(entity_id=str(entity_id))

    async def get_entity_intelligence(self, entity_id: UUID) -> EntityIntelligenceResult | None:
        """GET /api/v1/entities/{id}/intelligence → full intelligence bundle."""
        raw = await self._get(f"/api/v1/entities/{entity_id}/intelligence")
        if not raw:
            return None
        try:
            return EntityIntelligenceResult(
                entity_id=str(entity_id),
                narrative=raw.get("narrative") or raw.get("summary"),
                health_score=float(raw["health_score"]) if raw.get("health_score") is not None else None,
                key_metrics=raw.get("key_metrics") or {},
                source_distribution=raw.get("source_distribution") or {},
                paths=raw.get("paths") or [],
                relations_summary=raw.get("relations_summary"),
            )
        except (KeyError, TypeError, ValueError):
            return None
