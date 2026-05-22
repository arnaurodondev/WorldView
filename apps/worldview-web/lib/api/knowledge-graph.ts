/**
 * lib/api/knowledge-graph.ts — Entity graph + contradictions (S7 KG).
 *
 * SCOPE: egocentric knowledge-graph for sigma.js + the Intelligence tab's
 * contradictions panel.
 */

import type { EntityGraph, ContradictionsResponse, EntityPublic } from "@/types/api";
import type { NarrativeHistoryPage } from "@/types/intelligence";
import { apiFetch, GatewayError } from "./_client";

export function createKnowledgeGraphApi(t: string | undefined) {
  return {
    /**
     * getEntityGraph — egocentric knowledge graph for sigma.js
     *
     * WHY depth is now sent as a query param (ISSUE-5 fix, 2026-05-10):
     * S9 forwards depth to S7 which supports AGE Cypher multi-hop traversal.
     * depth=1 → 1-hop direct relations (S7 SQL); depth=2/3 → AGE Cypher 2/3-hop.
     * Requires KNOWLEDGE_GRAPH_CYPHER_ENABLED=true in knowledge-graph service.
     * limit is still derived from depth to bound N+1 entity lookups.
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
     * @param depth - Traversal depth: 1 = compact sidebar (SQL), 2/3 = AGE Cypher
     */
    async getEntityGraph(
      entityId: string,
      depth = 2,
      // WHY timeWindow param: the Intelligence tab filter toolbar lets analysts select
      // 7d / 30d / 90d / all. Changing the time window busts the TanStack Query cache
      // (queryKey includes timeWindow) and sends the new value to S9 as ?time_window=.
      // S9 may ignore unknown params gracefully — the query is additive and never breaks
      // the response shape. "all" is the default (no param sent).
      timeWindow = "all",
      // WHY signal param (T-D-01 BUG 2): callers can pass an AbortSignal so they
      // can enforce a client-side timeout (e.g. depth=3 backend queries often
      // exceed 5s — we abort at 3s and surface a friendly fallback instead of
      // showing a generic 504 / spinner-of-death).  The fetch() call propagates
      // the signal so the underlying HTTP connection is torn down on abort.
      signal?: AbortSignal,
    ): Promise<EntityGraph | null> {
      // WHY separate limits per depth level:
      // S7 returns 1-hop direct relations only (no true multi-hop traverse). The
      // depth slider controls how many relations are returned — more relations =
      // more neighbor nodes visible = feels "deeper". True multi-hop would require
      // the Cypher traversal endpoint (feature-flagged, not in S9 currently).
      // PLAN-0088 P0-8 (2026-05-10): each slider step now actually moves the
      // requested edge count. The previous ladder topped out at 50 and silently
      // ignored slider values 4 and 5 (Slider min=1 max=5), so dragging the
      // slider past 3 had no visible effect on the graph. The S9 gateway cap was
      // also lifted from 50→200 in the same change so depth=5 can deliver up
      // to 160 edges when the underlying KG supports it.
      // depth=1 → limit=15  (compact sidebar SVG, N+1 latency concern)
      // depth=2 → limit=40  (Intelligence tab default, sigma.js WebGL comfort)
      // depth=3 → limit=80
      // depth=4 → limit=120
      // depth=5 → limit=160 (analyst "show me everything" extreme)
      const limitByDepth: Record<number, number> = { 1: 15, 2: 40, 3: 80, 4: 120, 5: 160 };
      const limit = limitByDepth[depth] ?? 40;

      // WHY min_confidence for depth=1: sidebar SVG should show only high-quality
      // edges (≥0.3 confidence). The full Intelligence tab shows all edges.
      const minConfidence = depth === 1 ? 0.3 : 0.0;

      const params = new URLSearchParams({
        limit: String(limit),
        min_confidence: String(minConfidence),
      });

      // WHY send depth as query param: S9 now forwards depth to S7 which uses it
      // for AGE Cypher multi-hop traversal (depth=2/3). Previously stripped at S9.
      // depth=1 is S7's default, so we only send when >1 to avoid redundant params.
      if (depth > 1) {
        params.set("depth", String(depth));
      }

      // WHY evidence_snippets_limit=2: limits evidence text returned per edge to
      // 2 snippets. The GraphDetailSidebar renders up to 2 snippets per relation;
      // requesting more wastes bandwidth (S7 default is 3).
      params.set("evidence_snippets_limit", "2");

      // WHY only add time_window when not "all": S9 default is already "all" — sending
      // the parameter explicitly is unnecessary and adds URL noise. Omitting it for "all"
      // keeps the request URL stable (no spurious cache misses across browser sessions).
      if (timeWindow !== "all") {
        params.set("time_window", timeWindow);
      }

      // T-D-01 BUG 2: forward the optional AbortSignal so callers can enforce a
      // 3s client-side timeout for depth=3 graphs.  apiFetch spreads the options
      // into fetch(), which natively understands `signal`.
      // HIGH-011 / INC-003: mirror getEntityDetail's 404→null pattern so the
      // entire entity domain is consistent — 404 means the entity has no graph
      // edges yet, not an error callers need to handle.
      try {
        return await apiFetch<EntityGraph>(
          `/v1/entities/${encodeURIComponent(entityId)}/graph?${params.toString()}`,
          { token: t, signal },
        );
      } catch (err) {
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },

    /**
     * getContradictions — detected contradictory claims for an entity
     * Used by Instrument Detail → Intelligence tab
     *
     * Returns null when the entity has no contradiction data yet (404 from S7).
     * Mirrors getEntityDetail's 404→null pattern (HIGH-011 / INC-003).
     */
    async getContradictions(entityId: string): Promise<ContradictionsResponse | null> {
      try {
        return await apiFetch<ContradictionsResponse>(
          `/v1/entities/${encodeURIComponent(entityId)}/contradictions`,
          { token: t },
        );
      } catch (err) {
        // WHY catch here: 404 means no contradictions computed yet — not an error.
        // Consistent with getEntityDetail and getEntityGraph (all return null on 404).
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },

    /**
     * getEntityDetail — enrichment fields for a single entity (PRD-0073 Worker 13J).
     *
     * WHY separate from getEntityGraph: getEntityGraph returns the relational graph
     * structure (nodes + edges) while getEntityDetail returns the entity's own
     * enrichment fields (description, metadata, data_completeness).  Two separate
     * endpoints let the Intelligence tab load both independently with different
     * staleTime values — descriptions are stable for hours; graph edges refresh
     * every 10 minutes.
     *
     * Returns null when the entity has not been enriched yet (404 from S7).
     */
    async getEntityDetail(entityId: string): Promise<EntityPublic | null> {
      try {
        return await apiFetch<EntityPublic>(
          `/v1/entities/${encodeURIComponent(entityId)}`,
          { token: t },
        );
      } catch (err) {
        // WHY catch here: 404 means enrichment has not run yet — not an error the
        // caller needs to handle.  All other errors propagate normally.
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },

    /**
     * getEntityContradictions — alias for getContradictions (W7 T-20).
     *
     * WHY alias: W7 component code uses `gateway.getEntityContradictions(id)` for
     * naming consistency with other entity-scoped methods. Both call the same
     * endpoint so the cache key and response shape are identical.
     */
    getEntityContradictions(entityId: string): Promise<ContradictionsResponse | null> {
      return this.getContradictions(entityId);
    },

    /**
     * getNarratives — first page of narrative version history (W7 T-21).
     *
     * WHY non-infinite (not cursor-paginated): NarrativeHistoryDisclosure renders
     * a collapsed Accordion that shows at most ~10 versions before the user needs
     * to visit the full history page. Loading only the first page (default 20
     * versions) avoids the complexity of useInfiniteQuery inside a disclosure.
     * The full pagination is available via useEntityNarrativeHistory.
     *
     * Returns null when the entity has no narrative history yet (404).
     */
    async getNarratives(entityId: string): Promise<NarrativeHistoryPage | null> {
      try {
        return await apiFetch<NarrativeHistoryPage>(
          `/v1/entities/${encodeURIComponent(entityId)}/narratives`,
          { token: t },
        );
      } catch (err) {
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },
  };
}
