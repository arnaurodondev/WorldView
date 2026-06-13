"""S7 Intelligence HTTP client adapter — calls S9-proxied intelligence endpoints (PLAN-0080 Wave A).

WHY S9-proxied (not S7 direct): R14/R7 — all internal service-to-service calls go through
the public gateway (S9) for the intelligence endpoints, which apply auth and rate limiting.

Endpoints (via S9 proxy):
  GET /api/v1/entities/{id}/narratives   → latest entity narrative
  GET /api/v1/entities/{id}/paths        → top-N multi-hop paths
  GET /api/v1/entities/{id}/intelligence → full intelligence bundle
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from rag_chat.application.ports.upstream_clients import (
    EntityIntelligenceResult,
    EntityPathsResult,
    NarrativeResult,
    PathBetweenResult,
)
from rag_chat.infrastructure.clients.base import BaseUpstreamClient


class S7IntelligenceClient(BaseUpstreamClient):
    """Concrete HTTP adapter for S9-proxied S7 intelligence endpoints."""

    async def get_narrative(self, entity_id: UUID) -> NarrativeResult | None:
        """GET /api/v1/entities/{id}/narratives → latest narrative.

        S7 returns a paginated ``NarrativeVersionListResponse`` shaped as
        ``{entity_id, versions: [{narrative_text, generated_at, ...}], next_cursor}``.
        We take the first (newest) version. BP-602: previously this method
        looked for top-level ``content`` / ``narrative`` / ``text`` keys that
        never existed in the schema, so it silently returned an empty string
        and the downstream handler dropped the item.
        """
        raw = await self._get(f"/api/v1/entities/{entity_id}/narratives")
        if not raw:
            return None
        try:
            versions = raw.get("versions") or []
            if not versions:
                return None
            latest = versions[0] if isinstance(versions[0], dict) else {}
            # Fall back to legacy flat shape (raw.get("narrative_text") / "content")
            # so any test fixtures or future endpoint variants still parse.
            content = (
                latest.get("narrative_text")
                or raw.get("narrative_text")
                or raw.get("content")
                or raw.get("narrative")
                or raw.get("text")
                or ""
            )
            if not content:
                return None
            return NarrativeResult(
                entity_id=str(entity_id),
                content=content,
                version=int(raw.get("version", 1)),
                generated_at=latest.get("generated_at") or raw.get("generated_at"),
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

    async def get_path_between(
        self,
        source: UUID,
        target: UUID,
        max_hops: int = 3,
    ) -> PathBetweenResult:
        """GET /v1/paths/between → on-demand pairwise paths between two entities.

        Calls the S9-proxied pairwise endpoint (R14/R7 — never S7 directly). The
        underlying ``BaseUpstreamClient._get`` sets an explicit httpx timeout
        (BP-235) and promotes transport failures to ``UpstreamTransportError``.
        A 4xx (e.g. source==target → 400, missing entity → 404) returns ``{}`` →
        a disconnected result, never a crash (R9 safe degradation).
        """
        raw = await self._get(
            "/v1/paths/between",
            params={
                "source": str(source),
                "target": str(target),
                "max_hops": max_hops,
            },
        )
        if not raw:
            return PathBetweenResult(source_entity_id=str(source), target_entity_id=str(target))
        try:
            paths = raw.get("paths") or []
            return PathBetweenResult(
                source_entity_id=str(raw.get("source_entity_id") or source),
                target_entity_id=str(raw.get("target_entity_id") or target),
                connected=bool(raw.get("connected", False)),
                shortest_hops=raw.get("shortest_hops"),
                paths=paths if isinstance(paths, list) else [],
            )
        except (KeyError, TypeError, ValueError):
            return PathBetweenResult(source_entity_id=str(source), target_entity_id=str(target))

    async def get_entity_intelligence(self, entity_id: UUID) -> EntityIntelligenceResult | None:
        """GET /api/v1/entities/{id}/intelligence → full intelligence bundle.

        S7's ``EntityIntelligencePublic`` exposes:

        * ``current_narrative: {narrative_text, ...} | None`` (nested)
        * ``health_score: float | None``
        * ``confidence_breakdown.source_distribution: list[{source_type, source_name,
          count, pct}]`` (nested under ``confidence_breakdown``)
        * ``key_metrics: dict``
        * ``data_completeness: float``

        BP-602: the previous implementation read ``raw["narrative"]`` and
        ``raw["source_distribution"]`` at the top level — these keys do not
        exist in the schema, so the narrative text (the highest-leverage
        signal — it names competitors, themes, and exposures) was silently
        dropped and the handler emitted only a one-line "Health Score: X"
        bundle. Fixed by reading the nested paths with safe ``isinstance``
        walks. ``paths`` and ``relations_summary`` are NOT part of this
        schema (paths live under a separate ``/paths`` endpoint already wired
        via ``get_entity_paths``); we keep the fields on
        ``EntityIntelligenceResult`` for API stability but populate them as
        empty / None here.
        """
        raw = await self._get(f"/api/v1/entities/{entity_id}/intelligence")
        if not raw:
            return None
        try:
            # Narrative text — nested under current_narrative.
            current_narrative = raw.get("current_narrative")
            narrative_text: str | None = None
            if isinstance(current_narrative, dict):
                narrative_text = current_narrative.get("narrative_text")
            # Backward-compat fallback for any old flat shape / test fixtures.
            narrative_text = narrative_text or raw.get("narrative") or raw.get("summary")

            # Source distribution — nested under confidence_breakdown.
            breakdown = raw.get("confidence_breakdown") or {}
            src_dist_raw: Any = breakdown.get("source_distribution") if isinstance(breakdown, dict) else None
            if src_dist_raw is None:
                src_dist_raw = raw.get("source_distribution")
            # Normalise list-of-dicts (S7 schema) into a name→pct dict that
            # the downstream handler/agent can render compactly. If we got a
            # dict already (legacy), keep it as-is.
            source_distribution: dict
            if isinstance(src_dist_raw, list):
                source_distribution = {
                    str(row.get("source_name") or row.get("source_type") or "unknown"): float(row.get("pct") or 0.0)
                    for row in src_dist_raw
                    if isinstance(row, dict)
                }
            elif isinstance(src_dist_raw, dict):
                source_distribution = src_dist_raw
            else:
                source_distribution = {}

            return EntityIntelligenceResult(
                entity_id=str(entity_id),
                narrative=narrative_text,
                health_score=float(raw["health_score"]) if raw.get("health_score") is not None else None,
                key_metrics=raw.get("key_metrics") or {},
                source_distribution=source_distribution,
                # paths + relations_summary are not in EntityIntelligencePublic;
                # leave as defaults for API back-compat.
                paths=raw.get("paths") or [],
                relations_summary=raw.get("relations_summary"),
            )
        except (KeyError, TypeError, ValueError):
            return None
