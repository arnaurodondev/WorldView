/**
 * lib/api/knowledge-graph.ts — Entity graph + contradictions (S7 KG).
 *
 * SCOPE: egocentric knowledge-graph for sigma.js + the Intelligence tab's
 * contradictions panel.
 */

import type { EntityGraph, ContradictionsResponse } from "@/types/api";
import { apiFetch } from "./_client";

export function createKnowledgeGraphApi(t: string | undefined) {
  return {
    /**
     * getEntityGraph — egocentric knowledge graph for sigma.js
     *
     * WHY limit is derived from depth, NOT sent to S7 as depth:
     * S7's GET /api/v1/entities/{id}/graph does NOT have a `depth` param —
     * it only has `limit` (max relations to return, default 50, max 200).
     * The `depth` concept (1-hop vs 2-hop) does NOT exist in S7's SQL query;
     * S7 returns all direct relations up to `limit`.
     *
     * Sending `?depth=2` is silently ignored by S7 (FastAPI discards unknown
     * query params). The graph size is controlled entirely by `limit`.
     *
     * WHY cap by depth level:
     * - depth=1 (compact sidebar SVG in EntityGraphPanel): needs at most 15
     *   relations. More causes visual clutter and N+1 entity lookups in S7's
     *   GetEntityGraphUseCase (one DB round-trip per unique entity in relations).
     * - depth=2 (full sigma.js graph in IntelligenceTab): can absorb more data
     *   but capping at 40 prevents >40 sequential entity fetches in S7.
     *   The sigma.js renderer handles 40 nodes comfortably at 60fps.
     *
     * WHY pass `min_confidence=0.3` for depth=1:
     * Low-confidence edges add visual noise in the compact SVG sidebar.
     * The full Intelligence tab (depth=2) keeps min_confidence=0 to show
     * the full relationship picture.
     *
     * @param entityId - Entity UUID
     * @param depth - Visual depth level: 1 = compact sidebar, 2 = full graph
     */
    getEntityGraph(
      entityId: string,
      depth = 2,
      // WHY timeWindow param: the Intelligence tab filter toolbar lets analysts select
      // 7d / 30d / 90d / all. Changing the time window busts the TanStack Query cache
      // (queryKey includes timeWindow) and sends the new value to S9 as ?time_window=.
      // S9 may ignore unknown params gracefully — the query is additive and never breaks
      // the response shape. "all" is the default (no param sent).
      timeWindow = "all",
    ): Promise<EntityGraph> {
      // WHY separate limits: depth=1 sidebar has limited visual space (320×280px
      // SVG); fetching more than 15 relations causes N+1 lookups in S7 with no
      // visual benefit. depth=2 uses WebGL sigma.js which handles more nodes.
      const limit = depth === 1 ? 15 : 40;

      // WHY min_confidence for depth=1: sidebar SVG should show only high-quality
      // edges (≥0.3 confidence). The full Intelligence tab shows all edges.
      const minConfidence = depth === 1 ? 0.3 : 0.0;

      const params = new URLSearchParams({
        limit: String(limit),
        min_confidence: String(minConfidence),
      });

      // WHY only add time_window when not "all": S9 default is already "all" — sending
      // the parameter explicitly is unnecessary and adds URL noise. Omitting it for "all"
      // keeps the request URL stable (no spurious cache misses across browser sessions).
      if (timeWindow !== "all") {
        params.set("time_window", timeWindow);
      }

      return apiFetch<EntityGraph>(
        `/v1/entities/${encodeURIComponent(entityId)}/graph?${params.toString()}`,
        { token: t },
      );
    },

    /**
     * getContradictions — detected contradictory claims for an entity
     * Used by Instrument Detail → Intelligence tab
     */
    getContradictions(entityId: string): Promise<ContradictionsResponse> {
      return apiFetch<ContradictionsResponse>(
        `/v1/entities/${encodeURIComponent(entityId)}/contradictions`,
        { token: t },
      );
    },
  };
}
