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
// WHY "use client": uses useQuery (TanStack Query) for data fetching,
// useAuth to get the access token, useState for component-level state.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { TrendingUp, TrendingDown } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";
import { QUOTE_REFETCH_MS } from "@/hooks/usePortfolioMetrics";

// WHY local Period type: avoids importing a global enum just for three values
// — the dashboard only ever toggles 1D/1W/1M and Bloomberg's panel-header
// period selectors stick to short labels. Keep it inline + tightly typed.
type Period = "1D" | "1W" | "1M";

// ── Component ─────────────────────────────────────────────────────────────────

export function PortfolioSummary() {
  const { accessToken } = useAuth();

  // WHY local period state (C-3): the dashboard widget owns its own period
  // selector — independent from the heatmap and movers selectors so users can
  // compare different timeframes side by side (e.g., daily P&L while reviewing
  // monthly sector heatmap). Defaults to 1D — the most common morning routine.
  const [period, setPeriod] = useState<Period>("1D");

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
    // F-QA-01 fix: align staleTime with hooks/usePortfolioMetrics. The prior
    // `staleTime: 0` defeated the hook's deduplication goal — every mount of
    // this widget triggered a fetch even when the layout's hook had cached
    // a fresh quote. Both consumers now share QUOTE_REFETCH_MS (15s) so the
    // first observer's cache is reused until it ages out, and the
    // refetchInterval below keeps it fresh in the background.
    refetchInterval: QUOTE_REFETCH_MS,
    staleTime: QUOTE_REFETCH_MS,
  });

  // ── Query 4: company overview enrichment for ticker/name (BUG-3 fix) ──────
  // WHY this exists: holdings from S1 have ticker:null/name:null for holdings
  // imported via brokerage that haven't been enriched yet. Without this query,
  // the dashboard fell back to `h.instrument_id.slice(0, 8)` and rendered raw
  // UUID prefixes like "019dbf56" as the holding name. The full portfolio page
  // already does this; mirror it here so the dashboard widget matches.
  // WHY 5min staleTime: ticker/name/sector are effectively immutable per
  // instrument — refetching them aggressively burns S9 quota for no signal.
  const { data: holdingOverviews } = useQuery({
    queryKey: ["dashboard-holdings-overviews", instrumentIds],
    queryFn: async () => {
      const gw = createGateway(accessToken);
      const results = await Promise.all(
        instrumentIds.map((id) =>
          gw.getCompanyOverview(id).catch(() => null),
        ),
      );
      return Object.fromEntries(
        instrumentIds.map((id, i) => [
          id,
          {
            ticker: results[i]?.instrument?.ticker ?? null,
            name: results[i]?.instrument?.name ?? null,
          },
        ]),
      ) as Record<string, { ticker: string | null; name: string | null }>;
    },
    enabled: instrumentIds.length > 0 && !!accessToken,
    staleTime: 300_000,
  });

  // ── Query 5: portfolio performance for the selected period (C-3) ─────────
  // WHY this query: the headline P&L number used to show ONLY mark-to-market
  // unrealised P&L from cost basis. That answers "how am I doing overall?"
  // but not "how did the portfolio move today/this week/this month?" — which
  // is what the period selector promises. getPortfolioPerformance returns a
  // weighted return computed from OHLCV bars per holding.
  const { data: performance } = useQuery({
    queryKey: ["dashboard-portfolio-performance", firstPortfolio?.portfolio_id, period],
    queryFn: () =>
      createGateway(accessToken).getPortfolioPerformance(
        firstPortfolio!.portfolio_id,
        period,
      ),
    enabled: !!accessToken && !!firstPortfolio,
    // WHY 60s staleTime + 60s refetch: performance is a derived calculation
    // — it doesn't need to refresh as aggressively as the live quotes query.
    staleTime: 60_000,
    refetchInterval: 60_000,
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
    // WHY price>0 guard (B-2): a closed/delisted instrument can return price:0
    // from the batch quote endpoint — treat that as "no live price" rather than
    // collapsing the holding's value to 0 and skewing totals/pnl downward.
    const livePrice =
      quote?.price && quote.price > 0
        ? quote.price
        : h.current_price ?? h.average_cost;
    totalValue += livePrice * h.quantity;
    totalCost += h.average_cost * h.quantity;
  }
  const totalUnrealisedPnl = totalValue - totalCost;
  const totalUnrealisedPnlPct = totalCost > 0 ? (totalUnrealisedPnl / totalCost) * 100 : 0;

  // WHY prefer period return when available (C-3): the headline number tracks
  // the user's selected period. We still fall back to mark-to-market unrealised
  // P&L when the period query is in flight so the widget never goes blank.
  // performance.return_pct is in % (e.g., 1.23 = 1.23%). return_abs is in $.
  const headlinePnl =
    performance?.return_abs != null ? performance.return_abs : totalUnrealisedPnl;
  const headlinePnlPct =
    performance?.return_pct != null ? performance.return_pct : totalUnrealisedPnlPct;
  const isPnlPositive = headlinePnl >= 0;

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
      {/* ── Section header §0.9 pattern ──────────────────────────────────── */}
      {/* WHY period buttons restored (C-3): the previous code disabled them
          because no period-based S9 endpoint existed; getPortfolioPerformance
          (S9 GET /v1/portfolios/{id}/performance?period=) lands the gap.
          The buttons match the gap-px / px-1.5 / text-[9px] convention from
          PreMarketMoversWidget so the dashboard period UIs stay visually
          aligned across panels. */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          PORTFOLIO
        </span>
        <div className="flex gap-px">
          {(["1D", "1W", "1M"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              aria-pressed={period === p}
              className={cn(
                "px-1.5 text-[9px] font-mono uppercase transition-colors",
                period === p
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Inner content — padded to match other widgets */}
      <div className="flex-1 overflow-auto px-2 py-1">

      {/* Portfolio name sub-header */}
      {/* WHY show portfolio name here: the section header shows "PORTFOLIO" (generic);
          this line shows the ACTUAL portfolio name (e.g. "Tech Growth") so the trader
          knows which portfolio they're looking at without navigating to the portfolio page. */}
      <div className="mb-2">
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {firstPortfolio.name}
        </span>
      </div>

      {/* Total value + P&L — single flex row (PLAN-0048 Wave C-2)
          WHY one row instead of stacked rows:
          User audit (2026-04-28) found that at narrow widget widths the value
          and P&L could collide visually because each line wrapped independently.
          Putting both in one flex row with whitespace-nowrap on each child
          guarantees they never wrap into each other and the layout remains
          predictable across all viewport widths. */}
      <div className="mb-3">
        {/* WHY items-baseline: aligns the bottom of the large value digits
            with the bottom of the smaller P&L digits — typographically
            cleaner than items-center which would float the small text mid-cap.
            WHY gap-2: visual breathing room between value and P&L without
            either feeling detached. */}
        <div className="flex items-baseline gap-2">
          {/* Total value — large, prominent
              WHY flex-1: claim all leftover horizontal space so the P&L
              chunk hugs the right edge.
              WHY whitespace-nowrap + tabular-nums: locks the value onto a
              single line with column-aligned digits.
              WHY min-w-0: required so flex shrinking can kick in if the
              widget container ever narrows below the value's intrinsic width.
              WHY text-xl (was text-2xl): 24px is too large for a dashboard
              widget. text-xl (20px) keeps the value prominent without
              dominating the small panel. */}
          <p className="min-w-0 flex-1 whitespace-nowrap font-mono text-xl font-semibold tabular-nums text-foreground">
            {/* WHY "~" prefix: standard financial convention for "approximately".
                Shown when one or more prices are delayed, stale, or unavailable.
                Bloomberg uses this same convention on delayed portfolios.
                WHY inline (not on its own line): the approximation symbol must
                stay glued to the value so the user never reads the value
                without the qualifier. */}
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

          {/* P&L cluster — right-aligned, never wraps.
              WHY shrink-0 + whitespace-nowrap: the P&L is the secondary metric
              but must remain fully readable; we'd rather the value (above)
              shrink/truncate than have the P&L break across lines.
              WHY text-sm (14px): smaller than the value (20px) to establish
              hierarchy — the user's eye lands on total value first, P&L
              second. */}
          <div
            className={`flex shrink-0 items-center gap-1 whitespace-nowrap text-sm ${priceChangeClass(headlinePnlPct)}`}
          >
            {isPnlPositive ? (
              <TrendingUp className="h-3 w-3 shrink-0" />
            ) : (
              <TrendingDown className="h-3 w-3 shrink-0" />
            )}
            <span className="font-mono tabular-nums">
              {/* WHY "~" on P&L too: stale prices propagate into derived P&L too. */}
              {isApproximate && <span className="text-muted-foreground">~</span>}
              {formatPrice(Math.abs(headlinePnl))}
              {" "}
              ({formatPercent(headlinePnlPct / 100)})
            </span>
            {/* WHY tiny period suffix: traders glance at the number first; this
                suffix tells them which period the % refers to without expanding
                the line height. font-mono + tabular-nums for digit-column
                alignment when "1D" / "1W" / "1M" swap. */}
            <span className="ml-0.5 font-mono text-[10px] uppercase tabular-nums text-muted-foreground">
              {period}
            </span>
          </div>
        </div>
        {/* WHY subtle note (not error): stale prices are common during pre-market/weekends.
            A jarring error state would concern the user unnecessarily. A small hint
            below the P&L is enough to inform without alarming. */}
        {isApproximate && (
          <p className="mt-1 text-[10px] text-muted-foreground">
            Some prices are delayed
          </p>
        )}
      </div>

      {/* Top 4 holdings table */}
      <div className="space-y-1">
        {topHoldings.map((h) => {
          const quote = quotes[h.instrument_id];
          // WHY zero-price guard (B-2): batch quotes may return price:0 for closed
          // or delisted instruments (e.g., a fully-sold position). The previous
          // `?? fallback` chain treated 0 as a real price and produced -100% pnl.
          // Treat 0/missing as "no live price" and fall back to the snapshot value.
          const livePrice =
            quote?.price && quote.price > 0
              ? quote.price
              : h.current_price ?? h.average_cost;
          const holdingValue = livePrice * h.quantity;
          const pnlPct = h.average_cost > 0
            ? ((livePrice - h.average_cost) / h.average_cost) * 100
            : 0;
          // WHY enrichment (A-4): prefer the overview ticker/name over the raw
          // S1 holding fields (which are null for unenriched brokerage imports).
          const ov = holdingOverviews?.[h.instrument_id];
          const displayTicker = ov?.ticker || h.ticker || "—";
          const displayName = ov?.name || h.name || "Unknown holding";

          return (
            <div
              key={h.holding_id}
              className="flex h-[22px] items-center gap-1 rounded-[2px] px-1 hover:bg-muted/50"
            >
              {/* Ticker — monospace, fixed width for alignment */}
              <span className="w-[40px] shrink-0 font-mono text-[11px] font-medium tabular-nums text-foreground">
                {displayTicker}
              </span>
              {/* Name — truncated, muted. WHY no instrument_id slice fallback:
                  raw UUID prefixes (e.g. "019dbf56") looked like a bug to users. */}
              <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
                {displayName}
              </span>
              {/* Qty — compact shares count */}
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground/70">
                {h.quantity % 1 === 0
                  ? h.quantity.toLocaleString()
                  : h.quantity.toFixed(2)}×
              </span>
              {/* Price (C-3) — current per-share price. Distinct from Value:
                  traders need to see the live tick to compare against limit
                  orders / cost basis without doing mental division (Value/Qty). */}
              <span className="w-[48px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
                {livePrice > 0 ? formatPrice(livePrice) : "—"}
              </span>
              {/* Value — widened from w-[54px] to min-w-[80px] (F-203 fix,
                  PLAN-0048 QA iter-1). At 11px monospace the string
                  "$13,545.00" (10 chars × ~6.5px ≈ 65px) overflowed the
                  54px cell, visually fusing with the next column ("P&L %")
                  to read "$13,545.001.76%". 80px fits the worst-case
                  6-digit dollar value with room for the leading "$" and
                  the cents. min-w (instead of fixed w) lets the cell grow
                  if a holding ever crosses into the millions without
                  needing another patch. */}
              <span className="min-w-[80px] shrink-0 text-right font-mono text-[11px] tabular-nums text-foreground">
                {formatPrice(holdingValue)}
              </span>
              {/* P&L % */}
              <span className={`w-[40px] shrink-0 text-right font-mono text-[10px] tabular-nums ${priceChangeClass(pnlPct)}`}>
                {formatPercent(pnlPct / 100)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Link to full portfolio */}
      {holdings.length > 4 && (
        // T-B-2-06: truncate + px-2 prevents long counts (e.g., "+46 more")
        // from overflowing the widget on narrow viewports. The redundant
        // " → View all" suffix is dropped because the entire row is the
        // click target — duplicating affordance language adds noise.
        <Link
          href="/portfolio"
          className="mt-2 block truncate px-2 text-center text-xs text-muted-foreground hover:text-foreground"
        >
          +{holdings.length - 4} more
        </Link>
      )}

      {/* Close inner content wrapper (flex-1 overflow-auto px-2 py-1) */}
      </div>
    </div>
  );
}
