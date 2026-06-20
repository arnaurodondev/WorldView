/**
 * features/portfolio/lib/kpi.ts — Pure KPI / allocation / scope-hint logic.
 *
 * WHY THIS FILE EXISTS: The portfolio page held ~150 LOC of derived-state
 * computation inside three big useMemo blocks (KPI strip values, sector/type
 * allocations, scope hint). Inlining them in the page made the logic
 * untestable in isolation — any change required mounting the entire page
 * with React Testing Library + mocking 8 useQuery results. Pulling them
 * out into pure functions lets us drive them with hand-built fixtures and
 * assert against numeric outputs without rendering anything.
 *
 * WHY NOT a class: the inputs are the entire holding/quote/overview snapshot,
 * computed once per memo dep change. Pure functions match React's mental
 * model (memoise the call, not the state).
 *
 * SCOPE: imported by `app/(app)/portfolio/page.tsx` (and any future drill-
 * down panel that needs the same numbers). Tests live next to this file.
 */

import { formatPrice } from "@/lib/utils";
import type { Holding, Quote, Transaction, Portfolio } from "@/types/api";

// ── Types: narrow inputs the page actually has after enrichment ──────────

/**
 * Holding after the page's company-overview enrichment. The base `Holding`
 * type carries `ticker`/`name`/`entity_id` already, but the page also runs
 * a fallback chain (overview → holding field → derived placeholder); the
 * KPI logic just needs whatever shape is fed in.
 *
 * WHY a type alias (not extend Holding): nothing here needs more than the
 * base shape, so we avoid coupling KPI tests to the enrichment merge.
 */
export type EnrichedHolding = Holding;

/**
 * Map of instrument_id → Quote for the holding instruments. The page derives
 * this from `holdingsQuotesData?.quotes ?? {}` — we accept the raw map.
 */
export type QuoteMap = Record<string, Quote | undefined>;

/**
 * Map of instrument_id → company-overview enrichment row. The page uses
 * `sector` for allocation grouping and `ticker`/`name`/`entity_id` for
 * holding-row display; `ticker`/`name`/`entity_id` are merged BEFORE this
 * function sees the data, so we only need `sector` here.
 */
export type HoldingOverviewMap = Record<
  string,
  { sector: string | null; ticker: string | null; name: string | null; entity_id: string | null } | undefined
>;

// ── Output shapes ─────────────────────────────────────────────────────────

export interface PortfolioKPI {
  totalValue: number;
  dayPnl: number | null;
  unrealisedPnl: number;
  unrealisedPnlPct: number;
  topGainer: { ticker: string; pnlPct: number } | null;
  topLoser: { ticker: string; pnlPct: number } | null;
  positionCount: number;
  // null when transactions haven't loaded yet — the UI renders "—" so the
  // trader doesn't mistake "loading" for "no realized P&L" (BP — see
  // page.tsx comment block).
  realizedPnl: number | null;
}

export interface AllocationSlice {
  label: string;
  value: number;
  pct: number;
}

export interface PortfolioAllocations {
  bySector: AllocationSlice[];
  byType: AllocationSlice[];
}

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * livePriceFor — three-way fallback: live quote → server-enriched
 * current_price → average_cost. WHY q.price > 0 (not just non-null):
 * delisted instruments return 0 from the batch endpoint; treating 0 as
 * a real value previously made KPI flag the position as -100% top loser.
 *
 * Exported so the allocation calculation can reuse the exact same rule
 * (otherwise sector weights diverge from the KPI total value).
 */
export function livePriceFor(holding: EnrichedHolding, quotes: QuoteMap): number {
  const q = quotes[holding.instrument_id];
  if (q?.price && q.price > 0) return q.price;
  return holding.current_price ?? holding.average_cost;
}

/**
 * formatStalenessAwarePrice — prefix "~" when the quote is stale/delayed.
 *
 * "~$185.42" reads as "approximately $185.42" — universal approximation
 * signal that doesn't require a tooltip to understand. Used by the
 * holdings table cell renderer when a Quote.freshness != "live".
 */
export function formatStalenessAwarePrice(price: number, freshness?: string): string {
  const isStale = freshness != null && freshness !== "live";
  return isStale ? `~${formatPrice(price)}` : formatPrice(price);
}

// ── Main computations ─────────────────────────────────────────────────────

/**
 * computePortfolioKPI — produces the values rendered by `PortfolioKPIStrip`.
 *
 * Inputs:
 *  - enrichedHoldings: holdings list AFTER ticker/name/entity_id merge
 *    from company overviews (we need `ticker` for top-gainer/loser labels)
 *  - quotes: latest live-quote map (15s refresh on the page)
 *  - transactions: paginated transaction list (may be undefined if still
 *    loading — we surface that as `realizedPnl=null`)
 *
 * Behavior pinned by the previous inline implementation:
 *  - Top-gainer requires pnlPct > 0; top-loser requires pnlPct < 0. When
 *    every position is profitable, top-loser = null (UI renders "—"),
 *    NOT "smallest gainer" — F-202 fix avoids mis-signalling MSFT +1.7%
 *    as "Top Loser".
 *  - Day P&L = sum(quote.change × quantity) but null when NO quote has
 *    a change (so we don't conflate "loading" with "$0 day").
 *  - Realized P&L: simplified — uses CURRENT holding average_cost (FIFO
 *    running average) and only captures partial sells of positions that
 *    are still open. Closed positions can't be reconstructed without a
 *    cost-basis ledger, so they're skipped. The dedicated server-side
 *    FIFO endpoint (PLAN-0051 T-A-1-04) is where the page now sources
 *    the authoritative number; this approximation is the legacy fallback.
 *  - When transactions hasn't loaded yet (undefined), realizedPnl = null
 *    so the tile renders "—" instead of "$0".
 */
export function computePortfolioKPI(
  enrichedHoldings: readonly EnrichedHolding[],
  quotes: QuoteMap,
  transactions: { transactions?: readonly Transaction[] } | undefined,
): PortfolioKPI {
  let totalValue = 0;
  let totalCost = 0;
  let dayPnl: number | null = null;
  let topGainer: { ticker: string; pnlPct: number } | null = null;
  let topLoser: { ticker: string; pnlPct: number } | null = null;

  for (const h of enrichedHoldings) {
    const q = quotes[h.instrument_id];
    const livePrice = livePriceFor(h, quotes);
    totalValue += livePrice * h.quantity;
    totalCost += h.average_cost * h.quantity;

    // WHY null-guard: if no quote has a `change` field yet (batch query
    // pending), we can't compute day P&L — render "—" rather than $0.
    if (q?.change != null) {
      dayPnl = (dayPnl ?? 0) + q.change * h.quantity;
    }

    const pnlPct =
      h.average_cost > 0
        ? ((livePrice - h.average_cost) / h.average_cost) * 100
        : 0;

    // F-202 fix: pnlPct > 0 / pnlPct < 0 — symmetric, never label a
    // gaining position as the top loser.
    if (pnlPct > 0 && (topGainer == null || pnlPct > topGainer.pnlPct)) {
      topGainer = { ticker: h.ticker, pnlPct };
    }
    if (pnlPct < 0 && (topLoser == null || pnlPct < topLoser.pnlPct)) {
      topLoser = { ticker: h.ticker, pnlPct };
    }
  }

  const unrealisedPnl = totalValue - totalCost;
  const unrealisedPnlPct = totalCost > 0 ? unrealisedPnl / totalCost : 0;

  // ── Realized P&L from SELL transactions (legacy approximation) ────────
  // See block comment above — only captures partial sells of currently-
  // open positions. Closed positions are dropped (avgCost == null).
  const costByInstrument = Object.fromEntries(
    enrichedHoldings.map((h) => [h.instrument_id, h.average_cost] as const),
  );
  let realizedPnl = 0;
  for (const tx of transactions?.transactions ?? []) {
    if (tx.type !== "SELL") continue;
    const avgCost = costByInstrument[tx.instrument_id];
    if (avgCost == null) continue;
    realizedPnl += (tx.price - avgCost) * tx.quantity;
  }
  const realizedPnlOrNull = transactions != null ? realizedPnl : null;

  return {
    totalValue,
    dayPnl,
    unrealisedPnl,
    unrealisedPnlPct,
    topGainer,
    topLoser,
    positionCount: enrichedHoldings.length,
    realizedPnl: realizedPnlOrNull,
  };
}

/**
 * computeAllocations — sector + asset-type weighting for the allocation panel.
 *
 * Sector weights MUST agree with the KPI strip's totalValue (same live-price
 * fallback rule), otherwise the trader sees inconsistent numbers. The
 * `byType` slice is currently a single 100% "Equity" bar — when fixed-income
 * or crypto support lands, branch on overview.asset_class here.
 *
 * Edge cases:
 *  - empty holdings or missing overviews → both arrays empty
 *  - totalValue === 0 → both arrays empty (avoids NaN% from divide-by-zero
 *    when every position is at zero quantity)
 *  - missing overview for a holding → bucketed under "Unknown" sector
 *    (more honest than dropping the position from the chart)
 */
export function computeAllocations(
  enrichedHoldings: readonly EnrichedHolding[],
  overviews: HoldingOverviewMap | undefined,
  quotes: QuoteMap,
): PortfolioAllocations {
  if (!enrichedHoldings.length || !overviews) {
    return { bySector: [], byType: [] };
  }

  // First pass: market value per instrument using the SAME fallback rule
  // as KPI so sector weights line up with the KPI total exactly.
  const valueByInstrument: Record<string, number> = {};
  let totalVal = 0;
  for (const h of enrichedHoldings) {
    const price = livePriceFor(h, quotes);
    const val = price * h.quantity;
    valueByInstrument[h.instrument_id] = val;
    totalVal += val;
  }

  if (totalVal === 0) return { bySector: [], byType: [] };

  // Group by GICS sector
  const sectorMap: Record<string, number> = {};
  for (const h of enrichedHoldings) {
    const sector = overviews[h.instrument_id]?.sector ?? "Unknown";
    sectorMap[sector] =
      (sectorMap[sector] ?? 0) + (valueByInstrument[h.instrument_id] ?? 0);
  }
  // WHY pct is a 0-1 fraction (not 0-100): AllocationSlice.pct must match the
  // server sector-breakdown `weight` field (0-1) so the client-fallback path
  // and the server path are interchangeable. All live consumers
  // (SectorAllocationBar, ConcentrationSectorTeaseStrip) treat pct as 0-1 and
  // multiply by 100 at render time via formatPercent. (BP-487)
  const bySector: AllocationSlice[] = Object.entries(sectorMap)
    .map(([label, value]) => ({ label, value, pct: value / totalVal }))
    .sort((a, b) => b.pct - a.pct); // largest sector first

  const byType: AllocationSlice[] = [{ label: "Equity", value: totalVal, pct: 1 }];

  return { bySector, byType };
}

/**
 * computeScopeHint — one-line context string under the portfolio selector.
 *
 * Examples:
 *  - root portfolio with 2 sub-portfolios + 14 unique positions →
 *    "Viewing All Accounts — 2 portfolios, 14 unique positions"
 *  - brokerage portfolio → "Brokerage portfolio"
 *  - manual portfolio → null (selector name is enough)
 *  - no active portfolio → null
 */
export function computeScopeHint(
  activePortfolio: Portfolio | undefined,
  activeIsRoot: boolean,
  sortedPortfolios: readonly Portfolio[] | undefined,
  positionCount: number,
): string | null {
  if (!activePortfolio) return null;
  if (activeIsRoot) {
    const subCount =
      sortedPortfolios?.filter((p) => p.kind !== "root").length ?? 0;
    return `Viewing All Accounts — ${subCount} portfolio${subCount === 1 ? "" : "s"}, ${positionCount} unique position${positionCount === 1 ? "" : "s"}`;
  }
  if (activePortfolio.kind === "brokerage") {
    return "Brokerage portfolio";
  }
  return null;
}
