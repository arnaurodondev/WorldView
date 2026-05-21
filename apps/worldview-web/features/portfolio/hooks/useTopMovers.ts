/**
 * useTopMovers — derives top-4 contributors and bottom-4 detractors.
 *
 * WHY THIS EXISTS: ContributorsStrip needs sorted top/bottom movers.
 * Deriving client-side from enrichedHoldings avoids a separate backend
 * endpoint (the backend v1.1 endpoint for historical movers is deferred
 * — OQ1). Pure computation: no fetch, no side effects.
 * DATA SOURCE: enrichedHoldings from usePortfolioData.
 * DESIGN REFERENCE: PRD-0089 W2 §4.16
 */
import { useMemo } from "react";
import type { EnrichedHolding } from "@/features/portfolio/lib/kpi";

interface MoverEntry {
  ticker: string;
  pnlPct: number;
}

interface UseTopMoversResult {
  contributors: MoverEntry[];
  detractors: MoverEntry[];
}

export function useTopMovers(enrichedHoldings: EnrichedHolding[]): UseTopMoversResult {
  return useMemo(() => {
    // WHY filter pnlPct null: holdings without a price cannot be ranked.
    // Ranking $0.00 would put all unpriced holdings at the extremes.
    const ranked = enrichedHoldings
      .filter((h) => typeof h.unrealised_pnl_pct === "number")
      .map((h) => ({
        ticker: h.ticker ?? h.instrument_id,
        pnlPct: h.unrealised_pnl_pct as number,
      }))
      .sort((a, b) => b.pnlPct - a.pnlPct);

    return {
      contributors: ranked.slice(0, 4),
      // WHY reverse(): detractors are the bottom-4 sorted worst-first so the
      // strip shows "most negative at top" — matching Bloomberg PORT layout.
      detractors: ranked.slice(-4).reverse(),
    };
  }, [enrichedHoldings]);
}
