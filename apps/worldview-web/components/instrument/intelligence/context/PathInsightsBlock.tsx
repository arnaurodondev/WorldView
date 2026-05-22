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
import { useQueryClient } from "@tanstack/react-query";
import { useEntityPaths } from "@/lib/api/intelligence";
import { useActivePortfolio } from "@/contexts/ActivePortfolioContext";
import { qk } from "@/lib/query/keys";
import { Skeleton } from "@/components/ui/skeleton";
import type { HoldingsResponse } from "@/types/api";
import type { PathInsightPublic } from "@/types/intelligence";

export interface PathInsightsBlockProps {
  readonly entityId: string;
  readonly limit?: number;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PathInsightsBlock({ entityId, limit = 3 }: PathInsightsBlockProps) {
  const queryClient = useQueryClient();
  const { activePortfolioId } = useActivePortfolio();

  // WHY useEntityPaths (not direct useQuery): the hook already centralises the
  // qk.kg.paths key, auth token plumbing, and 5-min staleTime that matches
  // the backend's own path-computation cache TTL.
  const { data: pathsData, isLoading, isError } = useEntityPaths(entityId);

  // WHY getQueryData (not useQuery): we only OBSERVE the holdings cache that
  // the portfolio page/bundle already populated. Creating a second query here
  // would require a portfolio ID from props and fire a fresh S1 request just
  // for ticker filtering. Reading from cache is free and sufficient — if the
  // cache is empty (user never visited portfolio), the filter set is empty and
  // we fall back to top paths anyway.
  const holdingTickers = useMemo<Set<string>>(() => {
    if (!activePortfolioId) return new Set();
    const holdings = queryClient.getQueryData<HoldingsResponse>(
      qk.portfolios.holdings(activePortfolioId),
    );
    return new Set(holdings?.holdings?.map((h) => h.ticker) ?? []);
  }, [queryClient, activePortfolioId]);

  // Post-filter: prefer paths that pass through a holding ticker.
  // Fallback to top-scored paths when no holding intersection is found.
  const display = useMemo<PathInsightPublic[]>(() => {
    const all = pathsData?.paths ?? [];
    const filtered = all.filter((path) =>
      path.path_nodes.some((n) => holdingTickers.has(n.name)),
    );
    return (filtered.length > 0 ? filtered : all).slice(0, limit);
  }, [pathsData, holdingTickers, limit]);

  const sectionLabel = (
    <span className="text-[9px] font-mono uppercase tracking-[0.1em] text-muted-foreground px-3 py-1 block">
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

          return (
            <button
              key={path.insight_id}
              type="button"
              onClick={() =>
                console.debug("[intelligence] path.viewed", { entityId, path })
              }
              className="w-full min-h-[38px] py-1 px-2 flex flex-col justify-center text-left border border-border-subtle hover:bg-muted/20 transition-color-only duration-100"
            >
              {/* WHY ellipsis on path: long paths ("A → B → C → D") overflow the narrow rail */}
              <span className="text-[11px] text-foreground/90 truncate w-full">{pathLabel}</span>
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
