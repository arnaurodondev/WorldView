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
 * WeirdnessSubScores — the four interpretable sub-scores behind the PLAN-0112
 * "weirdness" headline metric. Shared by PathInsightPublic, WeirdConnectionPublic,
 * and PathBetweenPublic so every path-shaped surface renders the SAME breakdown.
 *
 * WHY a single shared shape: the backend WeirdnessScorer (S6) computes these five
 * numbers identically for the global feed, the pairwise endpoint, AND the per-entity
 * paths endpoint. Mirroring them in one interface means a relabel/format change is
 * made in exactly one place on the frontend.
 *
 * WHY every field is OPTIONAL + nullable (`?: number | null`):
 *   - ADDITIVE / backward-compat (PRD-0112 §AD-2, R5): the columns were added to the
 *     existing `path_insights` table as nullable. Rows scored BEFORE the migration
 *     (or rows the backfill skipped) return these fields as `null` — or the JSON may
 *     omit them entirely on very old cached responses. Components MUST guard with
 *     `?? `/conditional render and never assume a number is present.
 */
export interface WeirdnessSubScores {
  /** Harmonic mean of edge confidences (0–1). Higher = more reliable path. */
  reliability?: number | null;
  /** Topological surprise: low-degree (non-hub) endpoints score high (0–1). */
  unexpectedness?: number | null;
  /** 1 − cosine(src, dst) embedding similarity, mapped to 0–1. Far apart = high. */
  semantic_distance?: number | null;
  /** Fraction of edges first seen within the novelty window (0–1). */
  novelty?: number | null;
  /**
   * Headline composite (0–1) = reliability × weighted blend of the other three.
   * For PathInsightPublic this equals `composite_score` (the backend mirrors them).
   */
  weirdness?: number | null;
}

/**
 * PathInsightPublic — a complete multi-hop path insight.
 *
 * WHY composite_score (not just confidence):
 * Historically the path scoring system considered harmonic mean of edge
 * confidence (harmonic_score), source diversity (diversity_score), and surprise
 * (surprise_score). composite_score is the weighted combination surfaced as the
 * headline quality indicator.
 *
 * PLAN-0112 RELABEL: the headline is now "weirdness" — `composite_score` is kept
 * as the wire field name (mirrored to `weirdness` by the backend), and the new
 * sub-scores (reliability / unexpectedness / semantic_distance / novelty) replace
 * the old harmonic/diversity/surprise breakdown in the UI. The legacy fields are
 * retained on the type for BACKWARD COMPAT (old cached rows still carry them) but
 * the UI no longer renders them.
 *
 * WHY the legacy three are still required (not optional): the backend continues to
 * emit them on every response (additive change = no removals, R5), so making them
 * optional here would be a lie about the contract and would weaken existing tests.
 *
 * WHY explanation_pending:
 * LLM explanation generation is async (queued after path computation). The
 * PathsTab auto-refetches after 3 s when any path has explanation_pending=true,
 * showing a spinner until the explanation arrives.
 */
export interface PathInsightPublic extends WeirdnessSubScores {
  insight_id: string;
  hop_count: number;
  harmonic_score: number;          // LEGACY — retained for back-compat, not rendered
  diversity_score: number;         // LEGACY — retained for back-compat, not rendered
  surprise_score: number;          // LEGACY — retained for back-compat, not rendered
  template_match: string | null;   // matched narrative template, if any
  composite_score: number;         // 0.0–1.0 headline quality (== weirdness)
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

// ── PLAN-0112: Weird-connections feed + pairwise pathfinding ──────────────────

/**
 * WeirdConnectionPublic — one row in the GLOBAL ranked "weird connections" feed.
 * Returned by GET /v1/connections/weird (S9 → S6 GlobalWeirdConnectionsUseCase).
 *
 * WHY this differs from PathInsightPublic: the global feed reads precomputed rows
 * from `path_insights` but exposes only the path + scores + endpoint ids (no LLM
 * explanation / pending flag — the feed is a discovery surface, not an explainer).
 * It additionally carries `src_entity_id` / `dst_entity_id` so the UI can deep-link
 * each endpoint to its intelligence page.
 *
 * The four sub-scores + `weirdness` come from the shared WeirdnessSubScores shape
 * — but here they are guaranteed present (the feed is filtered to `weirdness IS NOT
 * NULL`), so we re-declare them as REQUIRED numbers to drop the null-guard noise in
 * the feed component.
 */
export interface WeirdConnectionPublic {
  path_nodes: PathNodePublic[];
  path_edges: PathEdgePublic[];
  hop_count: number;
  reliability: number;
  unexpectedness: number;
  semantic_distance: number;
  novelty: number;
  weirdness: number;
  src_entity_id: string;
  dst_entity_id: string;
  computed_at: string; // ISO datetime
}

/**
 * WeirdConnectionsResponse — paginated container for the global feed.
 * Returned by GET /v1/connections/weird.
 */
export interface WeirdConnectionsResponse {
  connections: WeirdConnectionPublic[];
  total: number;
  freshness_ts: string | null; // ISO datetime of the most recent computation
}

/**
 * WeirdConnectionsFilters — query params for useWeirdConnections.
 * Maps 1:1 to the S9 query string (snake_case on the wire).
 */
export interface WeirdConnectionsFilters {
  limit?: number;        // page size (default backend 20)
  offset?: number;       // pagination offset
  minWeirdness?: number; // → min_weirdness (0–1 floor)
  sinceDays?: number;    // → since_days (novelty window)
  entityType?: string;   // → entity_type (filter endpoint type)
}

/**
 * PathBetweenPublic — one ranked path returned by the PAIRWISE endpoint.
 * Returned inside PathsBetweenResponse from GET /v1/paths/between.
 *
 * WHY no src/dst ids (unlike WeirdConnectionPublic): the pairwise response already
 * carries source_entity_id / target_entity_id at the top level, so each path row
 * doesn't repeat them. Sub-scores are required (the endpoint always scores).
 */
export interface PathBetweenPublic {
  path_nodes: PathNodePublic[];
  path_edges: PathEdgePublic[];
  hop_count: number;
  reliability: number;
  unexpectedness: number;
  semantic_distance: number;
  novelty: number;
  weirdness: number;
}

/**
 * PathsBetweenResponse — the answer to "how are A and B related?".
 * Returned by GET /v1/paths/between?source&target.
 *
 * WHY connected + shortest_hops are separate from paths[]:
 *   - `connected` answers the yes/no question even when `paths` is empty (e.g. a
 *     pure existence check) — the UI shows a clean "no meaningful connection" state.
 *   - `shortest_hops` is null when disconnected; otherwise the minimum hop count,
 *     useful as a headline ("connected in 3 hops") above the ranked path list.
 */
export interface PathsBetweenResponse {
  source_entity_id: string;
  target_entity_id: string;
  connected: boolean;
  shortest_hops: number | null;
  paths: PathBetweenPublic[];
  computed_at: string; // ISO datetime
}

/**
 * PathBetweenOptions — optional tuning for usePathBetween.
 * Maps to the S9 query string (snake_case on the wire).
 */
export interface PathBetweenOptions {
  maxHops?: number;        // → max_hops (1–3; backend caps at path_max_hops)
  limit?: number;          // → limit (1–20 ranked paths)
  meaningfulOnly?: boolean; // → meaningful_only (prune membership edges)
}
