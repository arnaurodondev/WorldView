/**
 * types/intelligence.ts — TypeScript types for the Intelligence page (PLAN-0074 Wave H)
 *
 * WHY THIS EXISTS: Centralises all types for the 3-column intelligence page.
 * These types mirror the S9 response schemas exactly so components have static
 * type safety when consuming intelligence data.
 *
 * DATA SOURCES:
 * - GET /v1/entities/{id}/intelligence   → EntityIntelligencePublic
 * - GET /v1/entities/{id}/paths          → EntityPathsResponse
 * - GET /v1/entities/{id}/narratives     → NarrativeVersionPublic[]
 * - POST /v1/entities/{id}/narratives/generate (202 Accepted)
 *
 * WHO USES IT:
 * - lib/api/intelligence.ts (TanStack Query hooks)
 * - components/intelligence/* (all panel components)
 */

// ── Confidence breakdown sub-types ──────────────────────────────────────────

/**
 * ConfidenceTrendPoint — a single date/score pair in the confidence time-series.
 * Used by ConfidenceTrendSparkline to render the hand-rolled SVG polyline.
 */
export interface ConfidenceTrendPoint {
  date: string;          // ISO date string "YYYY-MM-DD"
  avg_confidence: number; // 0.0 – 1.0
}

/**
 * SourceSharePublic — breakdown of evidence by source type/name.
 * Used by SourceDistributionList to render CSS-width bars.
 */
export interface SourceSharePublic {
  source_type: string | null;  // "news" | "filing" | "social" | null
  source_name: string | null;  // e.g. "Reuters", null if aggregated
  count: number;               // raw evidence count for this source
  pct: number;                 // 0–100, percentage of total evidence
}

/**
 * ConfidenceBreakdownPublic — aggregated confidence stats for an entity's KG.
 *
 * WHY three separate scores (support/corroboration/contradiction):
 * S7 computes evidence in three categories — direct support (evidence that
 * affirms a relation), corroboration (independent sources that back it up),
 * and contradiction (evidence that disputes the relation). Showing all three
 * lets analysts see how contested a relation is, not just its headline score.
 */
export interface ConfidenceBreakdownPublic {
  mean_support: number | null;
  mean_corroboration: number | null;
  mean_contradiction: number | null;
  latest_evidence_at: string | null;  // ISO datetime of most recent evidence
  relation_count: number;             // total relations in the entity's KG
  source_distribution: SourceSharePublic[];
  confidence_trend: ConfidenceTrendPoint[];
}

// ── Narrative types ──────────────────────────────────────────────────────────

/**
 * NarrativeVersionPublic — one version in the entity's narrative history.
 *
 * WHY version_id (not numeric sequence): UUIDv7 IDs allow the infinite
 * scroll cursor pagination to be stable even if new versions are inserted
 * between paginated fetches.
 */
export interface NarrativeVersionPublic {
  version_id: string;
  narrative_text: string;
  model_id: string;          // e.g. "meta-llama/Meta-Llama-3.1-8B-Instruct"
  generation_reason: string; // INITIAL | PERIODIC_REFRESH | MANUAL_TRIGGER | ...
  generated_at: string;      // ISO datetime
  word_count: number | null;
  quality_score: number | null; // 0.0–1.0 or null if not scored
}

// ── Main intelligence summary type ──────────────────────────────────────────

/**
 * EntityIntelligencePublic — the top-level intelligence summary for an entity.
 * Returned by GET /v1/entities/{id}/intelligence.
 *
 * WHY health_score separate from confidence_breakdown:
 * health_score is a COMPOSITE metric (data freshness + completeness + confidence);
 * confidence_breakdown gives the raw underlying sub-scores. The sidebar shows
 * health_score as the headline badge, while the Evidence tab shows the breakdown.
 */
export interface EntityIntelligencePublic {
  entity_id: string;
  canonical_name: string;
  entity_type: string;  // "company" | "person" | "event" | "concept" | ...
  health_score: number | null;         // 0.0–1.0 composite
  current_narrative: NarrativeVersionPublic | null;
  confidence_breakdown: ConfidenceBreakdownPublic;
  key_metrics: Record<string, unknown>; // entity-type-specific metrics map
  data_completeness: number;            // 0.0–1.0 fraction of expected fields
}

// ── Path insight types ───────────────────────────────────────────────────────

/**
 * PathNodePublic — one entity in a multi-hop path.
 * Rendered as a coloured pill in the path visualization row.
 */
export interface PathNodePublic {
  entity_id: string;
  name: string;
  entity_type: string;
}

/**
 * PathEdgePublic — one relation hop in a multi-hop path.
 * Rendered as an arrow between path node pills.
 */
export interface PathEdgePublic {
  relation_type: string; // e.g. "CEO_OF", "SUBSIDIARY_OF"
  confidence: number;    // 0.0–1.0
}

/**
 * PathInsightPublic — a complete multi-hop path insight.
 *
 * WHY composite_score (not just confidence):
 * The path scoring system considers four dimensions: harmonic mean of edge
 * confidence (harmonic_score), source diversity (diversity_score), how
 * surprising the path is given the entity graph topology (surprise_score),
 * and hop count (shorter paths score higher). composite_score is the weighted
 * combination surfaced as the headline quality indicator.
 *
 * WHY explanation_pending:
 * LLM explanation generation is async (queued after path computation). The
 * PathsTab auto-refetches after 3 s when any path has explanation_pending=true,
 * showing a spinner until the explanation arrives.
 */
export interface PathInsightPublic {
  insight_id: string;
  hop_count: number;
  harmonic_score: number;
  diversity_score: number;
  surprise_score: number;
  template_match: string | null;   // matched narrative template, if any
  composite_score: number;         // 0.0–1.0 headline quality
  path_nodes: PathNodePublic[];
  path_edges: PathEdgePublic[];
  llm_explanation: string | null;  // null while explanation_pending=true
  explanation_pending: boolean;    // true → auto-refetch in 3 s
  computed_at: string;             // ISO datetime
}

/**
 * EntityPathsResponse — paginated container for path insights.
 * Returned by GET /v1/entities/{id}/paths.
 */
export interface EntityPathsResponse {
  entity_id: string;
  paths: PathInsightPublic[];
  total: number;
  freshness_ts: string | null; // ISO datetime of most recent path computation
}

// ── Narrative history pagination ─────────────────────────────────────────────

/**
 * NarrativeHistoryPage — one page of narrative versions (cursor pagination).
 *
 * WHY cursor pagination (not offset/page):
 * Narrative history grows over time. Offset pagination on a growing list causes
 * items to shift between pages (page 2 today may contain different items than
 * page 2 tomorrow). Cursor pagination anchors to a specific version_id so the
 * infinite scroll sequence stays stable even as new versions are generated.
 */
export interface NarrativeHistoryPage {
  // WHY `versions` (not `items`): canonical S7 schema is NarrativeVersionListResponse
  // which serialises this field as `versions`. The earlier FE type guessed `items`
  // and broke runtime rendering (P0-9 PLAN-0088).
  entity_id: string;
  versions: NarrativeVersionPublic[];
  next_cursor: string | null;  // pass as `cursor=` query param for next page
}

// ── Path filter types ────────────────────────────────────────────────────────

/**
 * PathFilters — optional filters for the useEntityPaths hook.
 * Maps directly to S9 query params.
 */
export interface PathFilters {
  limit?: number;    // max paths to return (default 20, max 50)
  minScore?: number; // filter to composite_score >= minScore
  minHops?: number;  // filter to hop_count >= minHops
  maxHops?: number;  // filter to hop_count <= maxHops
}
