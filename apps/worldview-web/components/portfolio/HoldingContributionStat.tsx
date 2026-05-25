/**
 * components/portfolio/HoldingContributionStat.tsx — per-holding contribution bps
 * (PRD-0089 SA-B)
 *
 * WHY THIS EXISTS: Portfolio theory uses "contribution to return" (Brinson
 * decomposition) to explain how much of the overall portfolio return was due to
 * each holding. Formula: contribution_bps = weight × period_return × 10000.
 *
 * WHY client-side computation (not a new endpoint):
 *   1. Both inputs (holdings for weight, value-history for period return) are
 *      already cached by the parent HoldingsTab and are available in the TanStack
 *      Query cache. Re-fetching them here costs zero network calls.
 *   2. The computation is trivially cheap — a multiply and a divide.
 *   3. Adding a dedicated endpoint would require a new S1/S9 route for a
 *      per-component convenience number — overengineering for a strip label.
 *
 * DATA SOURCE:
 *   - qk.portfolios.holdingsByPortfolio(portfolioId) → holdings → weight
 *   - qk.portfolios.valueHistory(portfolioId, period)  → equity curve → period_return
 *   (Both queries are already cached by usePortfolioData / EquityCurveChart.)
 *
 * WHO USES IT: HoldingDetailPanel (section 3)
 * DESIGN REFERENCE: PRD-0089 SA-B §E
 */

"use client";
// WHY "use client": useQuery is a browser-only hook from TanStack Query.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import type { Holding, HoldingsResponse, ValueHistoryResponse } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface HoldingContributionStatProps {
  portfolioId: string;
  instrumentId: string;
  /** Period for value history (e.g. "1M", "3M", "1Y"). */
  period: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Compute period return from a ValueHistoryResponse.
 *
 * WHY first/last value (not a server field): the equity curve endpoint returns
 * daily `value` points. The period return is (last - first) / first.
 * This matches how EquityCurveChart computes its % change label.
 */
function periodReturn(history: ValueHistoryResponse): number | null {
  const pts = history.points;
  if (!pts || pts.length < 2) return null;
  const first = pts[0].value;
  const last = pts[pts.length - 1].value;
  if (!first || first === 0) return null;
  return (last - first) / first;
}

/**
 * Map period label to the `days` parameter for getValueHistory.
 *
 * WHY a manual map (not Date arithmetic): getValueHistory accepts a `days`
 * shorthand that the backend converts to `from = today - N`. This avoids
 * repeating the DST / leap-year logic the server already handles.
 */
function periodToDays(period: string): number {
  const map: Record<string, number> = {
    "1D": 1,
    "1W": 7,
    "1M": 30,
    "3M": 90,
    "6M": 180,
    "1Y": 365,
    "YTD": 365, // approximate; server handles real YTD
    "All": 1825, // ~5y fallback
  };
  return map[period] ?? 90; // default 90d
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HoldingContributionStat({
  portfolioId,
  instrumentId,
  period,
}: HoldingContributionStatProps) {
  const { accessToken } = useAuth();

  // ── Query 1: holdings (reads from TanStack cache when parent has fetched) ─
  // WHY holdingsByPortfolio key: this is the SAME key shape usePortfolioData
  // uses (flat ["holdings", id]) so TanStack Query serves the cached copy
  // immediately — no second network request fires.
  const { data: holdingsResp } = useQuery<HoldingsResponse>({
    queryKey: qk.portfolios.holdingsByPortfolio(portfolioId),
    queryFn: () => createGateway(accessToken!).getHoldings(portfolioId),
    enabled: Boolean(accessToken && portfolioId),
    staleTime: 30_000,
  });

  // ── Query 2: value history (reads from cache; EquityCurveChart populates it)
  // WHY valueHistory(portfolioId, period) key: the same key is used by
  // EquityCurveChart in PortfolioAnalyticsSection. When that chart is visible,
  // this query is already cached and the contribution stat renders instantly
  // without a separate fetch.
  const { data: valueHistory } = useQuery<ValueHistoryResponse>({
    queryKey: qk.portfolios.valueHistory(portfolioId, period),
    queryFn: () =>
      createGateway(accessToken!).getValueHistory(portfolioId, {
        days: periodToDays(period),
      }),
    enabled: Boolean(accessToken && portfolioId),
    staleTime: 60_000,
  });

  // ── Derived computation ───────────────────────────────────────────────────
  const { contributionBps, weight } = useMemo(() => {
    // Find the holding row to get its current portfolio weight.
    const holdings: Holding[] = holdingsResp?.holdings ?? [];
    const holding = holdings.find((h) => h.instrument_id === instrumentId);
    if (!holding) return { contributionBps: null, weight: null };

    // Compute weight from quantity × average_cost (approximate market value).
    // WHY cost-based weight (not market-value weight): we don't have live prices
    // in this component. The portfolio_weight field on Holding is null (computed
    // externally with live quotes). Cost-basis weight is directionally accurate
    // and matches the standard analytical attribution model.
    const totalCost = holdings.reduce(
      (sum, h) => sum + h.quantity * h.average_cost,
      0,
    );
    const holdingCost = holding.quantity * holding.average_cost;
    const w = totalCost > 0 ? holdingCost / totalCost : null;

    // Get portfolio period return from the equity curve.
    const ret = valueHistory ? periodReturn(valueHistory) : null;

    if (w == null || ret == null) return { contributionBps: null, weight: w };

    // contribution_bps = weight × period_return × 10000
    // Example: 5% weight × 2% return = 10 bps contribution.
    return { contributionBps: w * ret * 10000, weight: w };
  }, [holdingsResp, valueHistory, instrumentId]);

  // ── Fallback when computation isn't possible ──────────────────────────────
  if (contributionBps == null) {
    return (
      <div className="flex items-center gap-2 px-3 py-1">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Contrib
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">—</span>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const bpsSign = contributionBps >= 0 ? "+" : "";
  const bpsStr = `${bpsSign}${contributionBps.toFixed(1)} bps`;

  const weightPct =
    weight != null
      ? `${(weight * 100).toFixed(1)}%`
      : "—";

  return (
    <div className="flex items-center gap-2 px-3 py-1">
      {/* Section label */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        Contrib
      </span>

      {/* Basis-point contribution — coloured by sign */}
      <span
        className={cn(
          "font-mono text-[11px] tabular-nums",
          // Positive contribution = green, negative = red, zero = muted.
          // WHY threshold of 0 (not ±0.05): any positive contribution is a win;
          // hiding tiny positives behind a "muted" zone would be misleading.
          contributionBps > 0
            ? "text-positive"
            : contributionBps < 0
              ? "text-negative"
              : "text-muted-foreground",
        )}
      >
        {bpsStr}
      </span>

      {/* Portfolio weight — supplementary context in muted color */}
      <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
        {weightPct}
      </span>
    </div>
  );
}
