/**
 * context/PathInsightsBlock.tsx — multi-hop path insights for Intelligence right rail (W7 T-11)
 *
 * WHY THIS EXISTS: PRD-0089 W7 — multi-hop paths reveal indirect connections that
 * are invisible in the depth=1 direct-relation view. An analyst tracking a supply
 * chain risk wants to know "Apple → TSMC → ASML" even when ASML is not directly
 * linked to Apple. PathInsightsBlock surfaces 3 such paths at a glance.
 *
 * WHY PORTFOLIO POST-FILTER:
 * The raw paths from S9 are entity-agnostic. Post-filtering to paths that contain
 * a ticker in the user's portfolio makes the insights immediately actionable —
 * "this path passes through a stock I already own". If no holding-intersecting
 * paths exist, we fall back to the 3 highest-scored paths so the block is never
 * empty for active analysts.
 *
 * WHO USES IT: ContextPanel (Intelligence tab right rail, entity-overview mode).
 * DATA SOURCE:
 *   GET /v1/entities/{id}/paths → EntityPathsResponse (via useEntityPaths)
 *   TanStack Query cache read: qk.portfolios.holdings(activePortfolioId)
 * DESIGN REFERENCE: W7 design doc §5.3 (PathInsightsBlock, 38px cards).
 */

"use client";
// WHY "use client": useQuery + useQueryClient + useActivePortfolio require browser.

import { useMemo } from "react";
import { useEntityPaths } from "@/lib/api/intelligence";
import { Skeleton } from "@/components/ui/skeleton";
import type { PathInsightPublic } from "@/types/intelligence";

export interface PathInsightsBlockProps {
  readonly entityId: string;
  readonly limit?: number;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PathInsightsBlock({ entityId, limit = 3 }: PathInsightsBlockProps) {
  // WHY useEntityPaths (not direct useQuery): the hook already centralises the
  // qk.kg.paths key, auth token plumbing, and 5-min staleTime that matches
  // the backend's own path-computation cache TTL.
  const { data: pathsData, isLoading, isError } = useEntityPaths(entityId);

  // WHY top-scored only (no portfolio filter): PathNodePublic has no ticker field,
  // so comparing n.name ("Apple Inc.") against portfolio tickers ("AAPL") always
  // returns false. Showing top-scored paths is more useful than an always-empty filter.
  const display = useMemo<PathInsightPublic[]>(() => {
    return (pathsData?.paths ?? []).slice(0, limit);
  }, [pathsData, limit]);

  // Round-3 item 2: label-level accent bar — uniform Round-1 section marker.
  // WHY mx-3 + pl-1.5 (was px-3): the 2px accent replaces the left padding's
  // first pixels so the bar aligns with the rail's other section markers.
  const sectionLabel = (
    <span className="mx-3 my-1 block border-l-2 border-l-primary pl-1.5 text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground">
      PATH INSIGHTS
    </span>
  );

  if (isLoading) {
    return (
      <div>
        {sectionLabel}
        <div className="px-3 py-1">
          <Skeleton className="h-[38px] w-full" />
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">Path insights unavailable.</p>
      </div>
    );
  }

  if (display.length === 0) {
    return (
      <div>
        {sectionLabel}
        <p className="text-[11px] text-muted-foreground px-3 py-2">No multi-hop paths discovered.</p>
      </div>
    );
  }

  return (
    <div>
      {sectionLabel}
      <div className="space-y-1 px-3">
        {display.map((path) => {
          // Build a readable path label: "Apple → TSMC → ASML"
          const pathLabel = path.path_nodes.map((n) => n.name).join(" → ");

          // Collect unique relation types for the subtitle line
          const relationTypes = Array.from(
            new Set(path.path_edges.map((e) => e.relation_type.toLowerCase().replace(/_/g, " "))),
          );
          const relSummary = relationTypes.slice(0, 3).join(", ");

          // PLAN-0112 T-5-03: surface the "weirdness" headline in the rail.
          // Prefer the explicit `weirdness` field; fall back to `composite_score`
          // for pre-PLAN-0112 rows (they are the same number when both present).
          // If BOTH are missing/null we omit the chip entirely (back-compat).
          const weird = path.weirdness ?? path.composite_score;
          const weirdPct =
            typeof weird === "number" && Number.isFinite(weird)
              ? Math.round(Math.min(1, Math.max(0, weird)) * 100)
              : null;

          return (
            <button
              key={path.insight_id}
              type="button"
              onClick={() =>
                console.debug("[intelligence] path.viewed", { entityId, path })
              }
              className="w-full min-h-[38px] py-1 px-2 flex flex-col justify-center text-left border border-border-subtle hover:bg-muted/20 transition-color-only duration-100"
            >
              <div className="flex w-full items-center justify-between gap-2">
                {/* WHY ellipsis on path: long paths ("A → B → C → D") overflow the narrow rail */}
                <span className="text-[11px] text-foreground/90 truncate">{pathLabel}</span>
                {/* Weirdness chip (relabelled from the old composite score). */}
                {weirdPct !== null && (
                  <span className="shrink-0 rounded-[2px] bg-primary/15 px-1 py-0.5 text-[8px] font-mono uppercase tracking-wider text-primary">
                    weird {weirdPct}%
                  </span>
                )}
              </div>
              <span className="text-[9px] text-muted-foreground mt-0.5">
                {path.hop_count} hop{path.hop_count !== 1 ? "s" : ""} · {relSummary}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
