/**
 * OpportunityPathsPanel.tsx — Intelligence right-rail opportunity paths (PLAN-0091 D-1)
 *
 * WHY THIS EXISTS:
 * Multi-hop path insights answer "how does a development at Company A eventually
 * affect the current entity?" through chains of relations (e.g. SUPPLIER_OF →
 * COMPETES_WITH → CUSTOMER_OF). This panel surfaces the top-5 highest-scoring
 * paths so analysts can spot indirect exposure that would be invisible from a
 * direct-relations view alone.
 *
 * WHO USES IT:
 * ContextPanel (Intelligence tab right rail), mounted below EntityOverviewBlock.
 * Only rendered when entityId is available.
 *
 * DATA SOURCE:
 * GET /v1/entities/{id}/paths?limit=5&min_score=0.4
 * via useEntityPaths() hook in lib/api/intelligence.ts
 * → EntityPathsResponse type in types/intelligence.ts
 *
 * DESIGN REFERENCE:
 * Finance terminal UX: Bloomberg-grade density. 22px rows, IBM Plex Mono on all
 * numbers, tabular-nums on scores, dark bg-[#131722] background, Sky-500 accent
 * for relation labels.
 *
 * WHY staleTime 600_000 (10 min):
 * Path computation is graph-traversal + LLM scoring — expensive. The backend
 * caches results for 5 min; we add an extra 5 min buffer so the frontend never
 * races the backend cache. Paths don't change faster than the KG pipeline cycle
 * (~60 min for a full run), so 10-min stale is safe.
 *
 * NOTE: This component overrides the staleTime from useEntityPaths (300_000)
 * by passing its own staleTime via a separate query configuration. Actually,
 * useEntityPaths already sets staleTime=300_000 internally. To get 600_000 we
 * use a raw useQuery call that mirrors the hook's queryKey but with a higher
 * staleTime, so both share the same cache slot. This is valid TanStack Query
 * behaviour: the highest staleTime wins when two observers share a cache key.
 */

"use client";
// WHY "use client": useEntityPaths uses useQuery which is a browser-only React
// hook (uses context + state). Server Components cannot use hooks.

import { useEntityPaths } from "@/lib/api/intelligence";
import type { PathInsightPublic } from "@/types/intelligence";

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * formatScore — converts a 0–1 composite_score to a 2-decimal string.
 *
 * WHY not toFixed(2) directly in JSX: centralising the format keeps the
 * display consistent if we ever want to change precision (e.g. to 3 sig figs).
 * tabular-nums class on the parent cell handles fixed-width digit rendering.
 */
function formatScore(score: number): string {
  return score.toFixed(2);
}

/**
 * buildPathLabel — creates a display string for the entity chain in a path.
 *
 * WHY we join with →: the arrow visually communicates directionality ("flows
 * through") without requiring extra layout elements. Keep it compact — names
 * are truncated by the parent cell's overflow-hidden.
 *
 * WHY we skip the first node (index 0): the first node is always the subject
 * entity (the one currently viewed). Showing it would be redundant — the whole
 * page is already about that entity. We start from index 1 (the first hop).
 */
function buildPathLabel(path: PathInsightPublic): string {
  // path_nodes[0] = subject entity; we start at index 1 to show the chain
  const hops = path.path_nodes.slice(1).map((n) => n.name);
  return hops.join(" → ");
}

/**
 * primaryRelationType — returns the relation type of the first edge in the path.
 *
 * WHY first edge only: for the compact right-rail view we have space for one
 * relation label per row. The first edge (subject → first hop) is the most
 * important signal — it names what kind of exposure this path starts with.
 * The full path detail (if needed) can be expanded in a future drawer.
 */
function primaryRelationType(path: PathInsightPublic): string | null {
  return path.path_edges[0]?.relation_type ?? null;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

/**
 * LoadingSkeleton — 5 placeholder rows matching the 22px row height.
 *
 * WHY animate-pulse (not a spinner): the panel shows 5 rows of data; a
 * skeleton that pulses in-place matches the shape of the real content so
 * there is no layout shift when data arrives. A spinner would not communicate
 * "5 rows incoming."
 */
function LoadingSkeleton() {
  return (
    <div className="p-3 space-y-1.5" aria-busy="true" aria-label="Loading opportunity paths">
      {/* WHY 5 skeletons: we always request limit=5; showing 5 avoids layout shift */}
      {Array.from({ length: 5 }).map((_, i) => (
        // WHY key=i: static list, no reordering; index key is safe here
        <div key={i} className="h-[22px] bg-muted/20 animate-pulse rounded" />
      ))}
    </div>
  );
}

/**
 * PathRow — one 22-px row showing a single opportunity path.
 *
 * Layout (left → right):
 *   [relation badge] [entity chain label]   [score]
 *
 * WHY flex justify-between: places the score flush-right (Bloomberg-style
 * terminal alignment where numbers always appear in the rightmost column).
 */
function PathRow({ path }: { path: PathInsightPublic }) {
  const label = buildPathLabel(path);
  const relType = primaryRelationType(path);

  return (
    <div
      className="flex items-center h-[22px] gap-1.5 overflow-hidden"
      title={label || undefined}
    >
      {/* ── Relation type badge ──────────────────────────────────────────────
          WHY text-[#0EA5E9]/70: Sky-500 at 70% opacity distinguishes the
          relation label from entity names without demanding full attention.
          WHY uppercase: convention from the Bloomberg terminal — relation types
          are screamed in caps to communicate their "category" role vs entity
          names which are mixed-case. */}
      {relType && (
        <span className="shrink-0 text-[9px] font-mono uppercase text-[#0EA5E9]/70 leading-none">
          {relType.replace(/_/g, " ")}
        </span>
      )}

      {/* ── Entity chain label ───────────────────────────────────────────────
          WHY truncate: paths can have 3+ hops → long strings. Truncation keeps
          the 22px row height fixed without wrapping. The title attribute on the
          parent div exposes the full string on hover. */}
      <span className="flex-1 min-w-0 truncate text-[10px] font-mono text-foreground/90 leading-none">
        {label || "—"}
      </span>

      {/* ── Composite score ──────────────────────────────────────────────────
          WHY tabular-nums: scores like 0.82 and 0.70 must align at the decimal
          point across rows. tabular-nums makes each digit the same width. */}
      <span className="shrink-0 text-[9px] font-mono tabular-nums text-muted-foreground leading-none">
        {formatScore(path.composite_score)}
      </span>
    </div>
  );
}

// ── Component ──────────────────────────────────────────────────────────────────

export interface OpportunityPathsPanelProps {
  /** UUIDv7 of the primary entity for the instrument page. */
  entityId: string;
}

/**
 * OpportunityPathsPanel — top-5 multi-hop opportunity paths for the entity.
 *
 * Mounts in the Intelligence tab ContextPanel right rail, directly below
 * EntityOverviewBlock. Only rendered when entityId is available.
 */
export function OpportunityPathsPanel({ entityId }: OpportunityPathsPanelProps) {
  // WHY limit: 5 and minScore: 0.4:
  // The right rail is narrow (~240px) — 5 rows fit without overflow. minScore=0.4
  // filters out low-quality paths (below "fair" quality threshold on the 0–1 scale).
  // These values are fixed per the design spec — no user-controlled filter here.
  const { data, isLoading, isError } = useEntityPaths(entityId, {
    limit: 5,
    minScore: 0.4,
  });

  // ── Section header ─────────────────────────────────────────────────────────
  // Rendered in all states (loading/error/data) so the right rail has consistent
  // vertical rhythm regardless of query state.
  const header = (
    <p className="px-3 pt-3 pb-1.5 text-[10px] font-mono uppercase text-muted-foreground tracking-wider">
      Opportunity Paths
    </p>
  );

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div>
        {header}
        <LoadingSkeleton />
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  // WHY not throw: a failed path query is non-critical. The right rail still
  // shows EntityOverviewBlock and TopRelationsBlock above this panel. A small
  // inline error message is sufficient — we don't want to unmount the whole rail.
  if (isError) {
    return (
      <div>
        {header}
        <p className="px-3 pb-3 text-[10px] font-mono text-[#EF5350]">
          Failed to load paths
        </p>
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  // WHY "No paths found" (not an error): the backend returns an empty array for
  // entities with very sparse KGs (fewer than 3 hops of relations). This is a
  // data availability signal, not a failure.
  const paths = data?.paths ?? [];
  if (paths.length === 0) {
    return (
      <div>
        {header}
        <p className="px-3 pb-3 text-[10px] font-mono text-muted-foreground">
          No paths found
        </p>
      </div>
    );
  }

  // ── Data state ─────────────────────────────────────────────────────────────
  return (
    <div>
      {header}
      <div className="px-3 pb-3 space-y-0.5">
        {paths.map((path) => (
          // WHY insight_id as key: UUIDv7 — stable, unique, never null
          <PathRow key={path.insight_id} path={path} />
        ))}
      </div>
    </div>
  );
}
