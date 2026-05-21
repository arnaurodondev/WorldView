/**
 * useTopMovers — derives top-4 contributors and bottom-4 detractors.
 *
 * WHY THIS EXISTS: ContributorsStrip needs sorted top/bottom movers.
 * Deriving client-side from enrichedHoldings avoids a separate backend
 * endpoint (the backend v1.1 endpoint for historical movers is deferred
 * — OQ1). Pure computation: no fetch, no side effects.
 * DATA SOURCE: enrichedHoldings + holdingsQuotes from usePortfolioData.
 * DESIGN REFERENCE: PRD-0089 W2 §4.16
 *
 * WHY quotes param (not unrealised_pnl_pct): getHoldings() initialises
 * unrealised_pnl_pct=null on every holding — price enrichment is computed
 * client-side from live quotes via livePriceFor(). Using unrealised_pnl_pct
 * caused this hook to always return empty arrays (BP-503).
 */
import { useMemo } from "react";
import { livePriceFor } from "@/features/portfolio/lib/kpi";
import type { EnrichedHolding, QuoteMap } from "@/features/portfolio/lib/kpi";

interface MoverEntry {
  ticker: string;
  pnlPct: number;
}

interface UseTopMoversResult {
  contributors: MoverEntry[];
  detractors: MoverEntry[];
}

export function useTopMovers(
  enrichedHoldings: EnrichedHolding[],
  quotes: QuoteMap = {},
): UseTopMoversResult {
  return useMemo(() => {
    // WHY filter average_cost > 0: zero-cost holdings (gifted positions) would
    // produce +Infinity pnlPct and dominate the contributor slot permanently.
    const ranked = enrichedHoldings
      .filter((h) => h.average_cost > 0)
      .map((h) => {
        // WHY livePriceFor: same three-way fallback used by kpi.ts so the
        // contributor percentages match the KPI strip totals exactly.
        // Before quotes arrive livePriceFor falls back to average_cost →
        // pnlPct=0 → excluded from both contributors and detractors, which
        // keeps the strip empty (shows "—") during the loading window.
        const livePrice = livePriceFor(h, quotes);
        const pnlPct = ((livePrice - h.average_cost) / h.average_cost) * 100;
        return { ticker: h.ticker || h.instrument_id, pnlPct };
      })
      .sort((a, b) => b.pnlPct - a.pnlPct);

    return {
      contributors: ranked.filter((m) => m.pnlPct > 0).slice(0, 4),
      // WHY reverse(): detractors are the bottom-4 sorted worst-first so the
      // strip shows "most negative at top" — matching Bloomberg PORT layout.
      detractors: ranked.filter((m) => m.pnlPct < 0).slice(-4).reverse(),
    };
  }, [enrichedHoldings, quotes]);
}
