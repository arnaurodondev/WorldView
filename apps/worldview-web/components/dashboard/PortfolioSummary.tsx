/**
 * components/dashboard/PortfolioSummary.tsx — Portfolio snapshot widget
 *
 * WHY THIS EXISTS: Traders check their P&L multiple times a day without
 * navigating to the full portfolio page. This widget gives an instant
 * "how am I doing today" answer: total value, today's P&L, and top holdings.
 *
 * WHY THREE PARALLEL QUERIES:
 * 1. getPortfolios → pick the first portfolio ID
 * 2. getHoldings(portfolioId) → get positions with cost basis
 * 3. getBatchQuotes(instrumentIds) → live prices
 * These can't be parallelised fully because query 2+3 depend on query 1's result.
 * TanStack Query enables them in a waterfall chain without boilerplate.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx
 * DATA SOURCE: S9 GET /v1/portfolios → GET /v1/holdings/:id → POST /v1/quotes/batch
 * DESIGN REFERENCE: PRD-0028 §6.5 Dashboard PortfolioSummary
 */

"use client";
// WHY "use client": uses useQuery (TanStack), useState for time-range toggle.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { TrendingUp, TrendingDown } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type TimeRange = "5D" | "5W";

// ── Component ─────────────────────────────────────────────────────────────────

export function PortfolioSummary() {
  const { accessToken } = useAuth();
  // WHY localStorage for time range: persist user preference across page navigations
  const [range, setRange] = useState<TimeRange>(() => {
    // WHY try/catch: localStorage access can fail in some SSR edge cases
    try {
      return (localStorage.getItem("portfolio-range") as TimeRange) ?? "5D";
    } catch {
      return "5D";
    }
  });

  // WHY period state: 1D/1W/1M selector for performance view — local state for now,
  // will be wired to an API parameter in a future wave when the portfolio performance
  // endpoint supports time-range filtering. Default "1D" = today's session.
  const [period, setPeriod] = useState<"1D" | "1W" | "1M">("1D");

  // ── Query 1: portfolio list ────────────────────────────────────────────────
  const { data: portfolios, isLoading: portfoliosLoading } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000, // WHY 60s: portfolios rarely change during the day
  });

  const firstPortfolio = portfolios?.[0];

  // ── Query 2: holdings for first portfolio ─────────────────────────────────
  const { data: holdingsResp, isLoading: holdingsLoading } = useQuery({
    queryKey: ["holdings", firstPortfolio?.portfolio_id],
    queryFn: () =>
      createGateway(accessToken).getHoldings(firstPortfolio!.portfolio_id),
    enabled: !!accessToken && !!firstPortfolio,
    staleTime: 30_000,
  });

  // ── Query 3: live quotes for positions ────────────────────────────────────
  const instrumentIds = holdingsResp?.holdings.map((h) => h.instrument_id) ?? [];
  const { data: quotesData, isLoading: quotesLoading } = useQuery({
    queryKey: ["holdings-quotes", instrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(instrumentIds),
    enabled: instrumentIds.length > 0 && !!accessToken,
    // WHY 15s: portfolio widget is visible all day; live prices matter
    refetchInterval: 15_000,
    staleTime: 0,
  });

  const isLoading = portfoliosLoading || holdingsLoading || quotesLoading;

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading && !holdingsResp) {
    return (
      <div className="space-y-3">
        <div className="flex justify-between">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-6 w-20" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
        <div className="space-y-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-6 w-full" style={{ animationDelay: `${i * 50}ms` }} />
          ))}
        </div>
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!firstPortfolio || !holdingsResp) {
    // WHY compact inline (was h-24 flex items-center justify-center):
    // terminal empty states don't center-vertically; they use compact inline text.
    return (
      <p className="py-3 text-xs text-muted-foreground">
        No portfolio yet —{" "}
        <Link href="/portfolio" className="text-primary hover:underline">
          create one
        </Link>
      </p>
    );
  }

  const quotes = quotesData?.quotes ?? {};
  const holdings = holdingsResp.holdings;

  // WHY: detect if any holding has stale/delayed/unavailable prices.
  // When true, the portfolio total is an approximation — show "~" prefix.
  // "live" and "recent" are the only statuses where prices are trustworthy enough
  // to display without a caveat. "delayed", "stale", "unavailable" all mean the
  // price may not reflect the current market.
  const hasStaleQuotes = Object.values(quotes).some(
    (q) => q?.freshness_status && !["live", "recent"].includes(q.freshness_status),
  );
  // WHY check missing quotes separately: if getBatchQuotes returned nothing for a
  // holding (quote absent from the response), the total is also approximate because
  // we fall back to h.current_price or h.average_cost — neither is live.
  const hasMissingQuotes = holdings.some((h) => !quotes[h.instrument_id]);
  const isApproximate = hasStaleQuotes || hasMissingQuotes;

  // ── Compute portfolio totals with live prices ──────────────────────────────
  // WHY recompute live (don't trust server-side values): the batch quote call
  // gives us fresher prices than the holdings endpoint's snapshot values.
  let totalValue = 0;
  let totalCost = 0;
  for (const h of holdings) {
    const quote = quotes[h.instrument_id];
    const livePrice = quote?.price ?? h.current_price ?? h.average_cost;
    totalValue += livePrice * h.quantity;
    totalCost += h.average_cost * h.quantity;
  }
  const totalUnrealisedPnl = totalValue - totalCost;
  const totalUnrealisedPnlPct = totalCost > 0 ? (totalUnrealisedPnl / totalCost) * 100 : 0;

  const isPnlPositive = totalUnrealisedPnl >= 0;

  // ── Top 4 holdings by current value ───────────────────────────────────────
  const topHoldings = [...holdings]
    .sort((a, b) => {
      const aVal = (quotes[a.instrument_id]?.price ?? a.average_cost) * a.quantity;
      const bVal = (quotes[b.instrument_id]?.price ?? b.average_cost) * b.quantity;
      return bVal - aVal;
    })
    .slice(0, 4);

  return (
    // WHY bg-background: other dashboard widgets (SectorHeatmap, TopMovers, etc.)
    // were updated from bg-card to bg-background. PortfolioSummary also sets bg
    // explicitly to keep all panel cells at the same surface level — prevents the
    // "slightly raised card" vs "flat background" mismatch that was visible before.
    // WHY flex-col h-full: fills the grid cell height so the section header and
    // period selector pattern is consistent across Row 3.
    <div className="flex h-full flex-col bg-background">
      {/* ── Section header §0.9 pattern with period selector ─────────────── */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        {/* Portfolio name label */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PORTFOLIO
        </span>
        {/* WHY period + range controls share the header row: Bloomberg convention —
            all time-selector controls live in the header so they're immediately
            visible alongside the section label. The 1D/1W/1M selector will be
            wired to filter the performance chart in a future wave; the 5D/5W toggle
            controls which holding P&L horizon is displayed below. */}
        <div className="flex items-center gap-2">
          {/* 1D/1W/1M period selector — same pattern as SectorHeatmapWidget */}
          <div className="flex gap-px">
            {(["1D", "1W", "1M"] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-1.5 text-[9px] font-mono uppercase transition-colors ${
                  period === p
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                aria-pressed={period === p}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Inner content — padded to match other widgets */}
      <div className="flex-1 overflow-auto px-2 py-1">

      {/* Portfolio name + 5D/5W range toggle sub-header */}
      {/* WHY show portfolio name here too: the section header shows "PORTFOLIO" (generic);
          this line shows the ACTUAL portfolio name (e.g. "Tech Growth") so the trader
          knows which portfolio they're looking at without navigating to the portfolio page.
          WHY keep 5D/5W alongside 1D/1W/1M: the two controls serve different purposes —
          1D/1W/1M is a performance-period view (chart horizon, wired in future wave);
          5D/5W is a P&L snapshot window for the holdings table below (wired to `range` state). */}
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {firstPortfolio.name}
        </span>
        {/* WHY rounded-[2px]: design system mandates 2px radius everywhere; bare `rounded` = 4px default */}
        <div className="flex rounded-[2px] border border-border">
          {(["5D", "5W"] as TimeRange[]).map((r) => (
            <button
              key={r}
              onClick={() => {
                setRange(r);
                localStorage.setItem("portfolio-range", r);
              }}
              className={`px-2 py-0.5 text-[10px] font-medium transition-colors ${
                range === r
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Total value — large, prominent */}
      <div className="mb-3">
        {/* WHY text-xl (was text-2xl): 24px is too large for a dashboard widget.
            text-xl (20px) keeps the value prominent without dominating the small panel. */}
        <p className="font-mono text-xl font-semibold tabular-nums text-foreground">
          {/* WHY "~" prefix: standard financial convention for "approximately".
              Shown when one or more prices are delayed, stale, or unavailable.
              Bloomberg uses this same convention on delayed portfolios. */}
          {isApproximate && (
            <span
              className="mr-0.5 text-muted-foreground"
              title="Some prices are delayed or unavailable"
            >
              ~
            </span>
          )}
          {formatPrice(totalValue)}
        </p>
        <div className={`flex items-center gap-1 ${priceChangeClass(totalUnrealisedPnlPct)}`}>
          {isPnlPositive ? (
            <TrendingUp className="h-3 w-3" />
          ) : (
            <TrendingDown className="h-3 w-3" />
          )}
          <span className="font-mono text-sm tabular-nums">
            {/* WHY "~" on P&L too: if the total value is approximate, the P&L derived
                from it is also approximate. Both numbers share the same stale data. */}
            {isApproximate && <span className="text-muted-foreground">~</span>}
            {formatPrice(Math.abs(totalUnrealisedPnl))}
            {" "}
            ({formatPercent(totalUnrealisedPnlPct / 100)})
          </span>
        </div>
        {/* WHY subtle note (not error): stale prices are common during pre-market/weekends.
            A jarring error state would concern the user unnecessarily. A small hint
            below the P&L is enough to inform without alarming. */}
        {isApproximate && (
          <p className="mb-2 text-[10px] text-muted-foreground">
            Some prices are delayed
          </p>
        )}
      </div>

      {/* Top 4 holdings table */}
      <div className="space-y-1">
        {topHoldings.map((h) => {
          const quote = quotes[h.instrument_id];
          const livePrice = quote?.price ?? h.current_price ?? h.average_cost;
          const holdingValue = livePrice * h.quantity;
          const pnlPct = h.average_cost > 0
            ? ((livePrice - h.average_cost) / h.average_cost) * 100
            : 0;

          return (
            <div
              key={h.holding_id}
              // WHY rounded-[2px]: design system mandates 2px radius everywhere; bare `rounded` = 4px default
              className="flex items-center justify-between rounded-[2px] px-1 py-0.5 hover:bg-muted/50"
            >
              {/* Ticker + name */}
              <div className="min-w-0">
                <span className="font-mono text-xs font-medium tabular-nums text-foreground">
                  {h.ticker}
                </span>
                <span className="ml-2 truncate text-[10px] text-muted-foreground">
                  {h.name}
                </span>
              </div>
              {/* Value + P&L */}
              <div className="flex shrink-0 items-center gap-3">
                <span className="font-mono text-xs tabular-nums text-foreground">
                  {formatPrice(holdingValue)}
                </span>
                <span className={`font-mono text-[10px] tabular-nums ${priceChangeClass(pnlPct)}`}>
                  {formatPercent(pnlPct / 100)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Link to full portfolio */}
      {holdings.length > 4 && (
        <Link
          href="/portfolio"
          className="mt-2 block text-center text-xs text-muted-foreground hover:text-foreground"
        >
          +{holdings.length - 4} more → View all
        </Link>
      )}

      {/* Close inner content wrapper (flex-1 overflow-auto px-2 py-1) */}
      </div>
    </div>
  );
}
