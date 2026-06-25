/**
 * lib/api/knowledge-graph.ts — Entity graph + contradictions (S7 KG).
 *
 * SCOPE: egocentric knowledge-graph for sigma.js + the Intelligence tab's
 * contradictions panel.
 */

import type { EntityGraph, ContradictionsResponse, EntityPublic } from "@/types/api";
import { apiFetch, GatewayError } from "./_client";

/**
 * EntityIntelligenceBundleResponse — PLAN-0099 H composite for the Intelligence tab.
 *
 * WHY a new bundle shape (vs. DashboardBundleResponse):
 * The Intelligence tab fires 5 independent S9 calls on mount (entity detail,
 * brief, depth=2 graph, paths, intelligence_summary). This composite collapses
 * them into a single round-trip server-side via asyncio.gather. The frontend
 * then hydrates the per-widget TanStack caches via setQueryData so child
 * components render without firing their own initial fetches.
 *
 * All legs are independently nullable — failed legs degrade to null at the
 * gateway and the page renders skeletons / "—" for them.
 */
export interface EntityIntelligenceBundleResponse {
  /** GET /v1/entities/{id} payload (canonical_name, description, metadata, …). */
  detail: unknown | null;
  /** GET /v1/briefings/instrument/{id} payload (AI brief narrative + sections). */
  brief: unknown | null;
  /** Depth=2 EntityGraph {entity_id, nodes, edges} — already transformed S7→FE. */
  graph_d2: unknown | null;
  /** GET /v1/entities/{id}/paths payload (top-N multi-hop opportunity paths). */
  paths: unknown | null;
  /** GET /v1/entities/{id}/intelligence aggregate (health, narrative, confidence). */
  intelligence_summary: unknown | null;
}

// ── PLAN-0099 Wave-2 enriched-entity / relation-detail / events types ─────────
//
// WHY these types live HERE (not types/api.ts): types/api.ts is a shared file
// touched by several parallel agents this sprint. The Wave-1 backend additions
// (enriched GET /v1/entities/{id}, GET /v1/relations/{id}, GET
// /v1/entities/{id}/events) are consumed exclusively by the Intelligence tab,
// so defining them in the KG api module keeps the change inside the
// intelligence-owned surface and avoids merge conflicts on the shared file.

/**
 * EntityAlias — one alias row from the enriched entity detail endpoint.
 * alias_type examples: "EXACT", "TICKER", "ABBREVIATION", "FORMER_NAME".
 */
export interface EntityAlias {
  alias_text: string;
  alias_type: string | null;
}

/**
 * EntityTopRelation — one authority-ranked relation summary row from
 * GET /v1/entities/{id} `top_relations` (PLAN-0099 Wave 1).
 *
 * WHY relation_id is load-bearing: clicking a top-relation row in the dossier
 * or node inspector selects that edge (same flow as clicking the edge on the
 * sigma canvas) — the id feeds GET /v1/relations/{relation_id}.
 */
export interface EntityTopRelation {
  relation_id: string;
  canonical_type: string;
  /** "outbound" | "inbound" relative to the entity being viewed. */
  direction: string;
  other_entity_id: string;
  other_entity_name: string;
  other_entity_type: string | null;
  confidence: number | null;
  evidence_count: number | null;
  relation_summary: string | null;
}

/**
 * EntityDetailEnriched — GET /v1/entities/{id} after the PLAN-0099 Wave-1
 * enrichment: the base EntityPublic fields PLUS health_score, aliases,
 * top_relations and relation_count.
 *
 * WHY `extends EntityPublic`: the base shape (canonical_name, description,
 * metadata, …) is unchanged — the new fields are additive (R11 forward-compat).
 * All new fields are optional so cached pre-Wave-1 payloads still type-check.
 */
export interface EntityDetailEnriched extends EntityPublic {
  health_score?: number | null;
  aliases?: EntityAlias[];
  top_relations?: EntityTopRelation[];
  relation_count?: number | null;
}

/**
 * RelationEntitySummary — subject/object entity block inside the relation
 * detail response. Mirrors S7's EntitySummary (NOT EntityPublic — no metadata).
 */
export interface RelationEntitySummary {
  entity_id: string;
  canonical_name: string;
  entity_type: string | null;
  isin: string | null;
  ticker: string | null;
  exchange: string | null;
  description: string | null;
  sector: string | null;
  industry: string | null;
  market_cap: number | null;
}

/**
 * RelationEvidenceItem — one evidence row from GET /v1/relations/{id}.
 *
 * NOTE (R9): article title/url/published_at are NOT included — intelligence_db
 * has no article metadata. The UI renders source_name + evidence_date as the
 * provenance line; if a future gateway change adds `article_title`/`article_url`
 * the EvidenceRow component picks them up without an API-layer change.
 */
export interface RelationEvidenceItem {
  raw_id: string;
  /** The chunk of source text the extraction was made from — the centrepiece. */
  evidence_text: string | null;
  document_id: string | null;
  source_name: string | null;
  source_type: string | null;
  /** "positive" | "negative" | "neutral" — extraction polarity. */
  polarity: string | null;
  evidence_date: string | null;
  extraction_confidence: number | null;
  source_trust_weight: number | null;
  is_backfill: boolean | null;
  extracted_at: string | null;
  /** Forward-compat slots — not emitted by the gateway today (see NOTE above). */
  article_title?: string | null;
  article_url?: string | null;
}

/**
 * RelationDetail — GET /v1/relations/{relation_id} (PLAN-0099 Wave 1).
 * The full edge dossier: type/mode/decay, confidence + staleness, temporal
 * validity, contradiction stats, LLM summary provenance, both endpoint entity
 * summaries, and the evidence list with the raw text chunks.
 */
export interface RelationDetail {
  relation_id: string;
  canonical_type: string;
  semantic_mode: string | null;
  decay_class: string | null;
  confidence: number | null;
  confidence_stale: boolean | null;
  summary_authority: number | null;
  evidence_count: number | null;
  first_evidence_at: string | null;
  latest_evidence_at: string | null;
  valid_from: string | null;
  valid_to: string | null;
  relation_period_type: string | null;
  strongest_contra_score: number | null;
  latest_contra_at: string | null;
  relation_source: string | null;
  created_at: string | null;
  updated_at: string | null;
  relation_summary: string | null;
  summary_generated_at: string | null;
  summary_model_id: string | null;
  subject: RelationEntitySummary | null;
  object: RelationEntitySummary | null;
  evidence: RelationEvidenceItem[];
}

/**
 * EntityEventItem — one temporal event from GET /v1/entities/{id}/events.
 * lifecycle_phase is computed server-side: "PENDING" | "ACTIVE" | "RESIDUAL"
 * | "EXPIRED" (case per S7 — UI normalises for display).
 */
export interface EntityEventItem {
  event_id: string;
  event_type: string | null;
  scope: string | null;
  region: string | null;
  title: string | null;
  description: string | null;
  active_from: string | null;
  active_until: string | null;
  residual_impact_days: number | null;
  lifecycle_phase: string | null;
  confidence: number | null;
  exposed_entity_count: number | null;
  created_at: string | null;
}

/** Envelope for GET /v1/entities/{id}/events. */
export interface EntityEventsResponse {
  events: EntityEventItem[];
  total: number;
}

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
    async getEntityDetail(entityId: string): Promise<EntityDetailEnriched | null> {
      try {
        // WHY EntityDetailEnriched (PLAN-0099 Wave 2): the endpoint now also
        // returns health_score / aliases / top_relations / relation_count.
        // The enriched type extends EntityPublic so existing callers that only
        // read description/metadata keep compiling unchanged.
        return await apiFetch<EntityDetailEnriched>(
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
     * getRelationDetail — full edge dossier for the Intelligence tab inspector.
     *
     * GET /v1/relations/{relation_id}?evidence_limit=N (PLAN-0099 Wave 1).
     *
     * WHY 404→null (not throw): a stale graph cache can hold an edge id that
     * the KG has since re-canonicalised away. The inspector renders a named
     * "relation no longer available" state for null — that is a data lifecycle
     * event, not an error the analyst can retry their way out of.
     *
     * @param relationId   The GraphEdge.id from the graph payload (== KG relation_id).
     * @param evidenceLimit Max evidence rows (gateway default 25, max 100).
     */
    async getRelationDetail(
      relationId: string,
      evidenceLimit = 25,
    ): Promise<RelationDetail | null> {
      try {
        return await apiFetch<RelationDetail>(
          `/v1/relations/${encodeURIComponent(relationId)}?evidence_limit=${evidenceLimit}`,
          { token: t },
        );
      } catch (err) {
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },

    /**
     * getEntityEvents — entity-scoped temporal events for the Intelligence tab
     * EVENTS rail block.
     *
     * GET /v1/entities/{id}/events (PLAN-0099 Wave 1). The gateway injects the
     * entity_id filter from the path (cannot be overridden) and computes
     * lifecycle_phase per event.
     *
     * WHY active_only=false: the rail shows the event TIMELINE — an event in
     * its RESIDUAL/EXPIRED phase is still investigation-relevant context (the
     * lifecycle chip communicates the phase). The backend default (true) is
     * tuned for alerting surfaces, not investigation ones.
     */
    async getEntityEvents(
      entityId: string,
      opts: { activeOnly?: boolean; limit?: number } = {},
    ): Promise<EntityEventsResponse | null> {
      const params = new URLSearchParams({
        active_only: String(opts.activeOnly ?? false),
        limit: String(opts.limit ?? 20),
      });
      try {
        return await apiFetch<EntityEventsResponse>(
          `/v1/entities/${encodeURIComponent(entityId)}/events?${params.toString()}`,
          { token: t },
        );
      } catch (err) {
        // 404 mirrors the rest of the entity domain: no events ingested yet.
        if (err instanceof GatewayError && err.status === 404) return null;
        throw err;
      }
    },

    /**
     * getEntityIntelligenceBundle — PLAN-0099 H Intelligence-tab composite.
     *
     * WHY THIS METHOD EXISTS (Agent D audit I1+I2): the Intelligence tab used
     * to fire 5 independent gateway calls on mount (entity detail, brief,
     * depth=2 graph, paths, intelligence_summary) plus a redundant depth=1
     * graph from ContextPanel. Each call is its own TLS handshake — the tab
     * was wave-serialized by the slowest leg.
     *
     * This single call fans out server-side via asyncio.gather and returns
     * all 5 legs in one round-trip. The caller (useEntityIntelligenceBundle
     * + IntelligenceTab) hydrates the per-widget TanStack caches via
     * setQueryData so the child queries see the data as already-fetched.
     *
     * 404 is NOT special-cased here: the bundle endpoint always returns 200
     * with null legs for failures; a 404 would mean the entity_id is malformed
     * (422 from FastAPI before the route runs) or the route is misregistered —
     * both should propagate as errors so they're visible in dev.
     */
    async getEntityIntelligenceBundle(
      entityId: string,
    ): Promise<EntityIntelligenceBundleResponse> {
      return await apiFetch<EntityIntelligenceBundleResponse>(
        `/v1/entities/${encodeURIComponent(entityId)}/intelligence-bundle`,
        { token: t },
      );
    },
  };
}
