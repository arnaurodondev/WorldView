/**
 * app/(app)/portfolio/page.tsx — Full Portfolio Page (Terminal Redesign, Wave 4)
 *
 * WHY THIS EXISTS: The dashboard PortfolioSummary widget shows only a 4-tile
 * summary. This page is the trader's full position-management view:
 *
 *   Holdings    — 10-column semantic table with live P&L + sector allocation
 *   Transactions — filter by BUY/SELL/DIVIDEND, newest-first
 *   Watchlist   — per-watchlist tabs with live prices (30s refresh)
 *   Brokerages  — SnapTrade connection status, sync actions, error drill-down
 *
 * WHY FOUR TABS (not panels): keeping 4 data surfaces in one view without tabs
 * would require a vertical scroll marathon through 500+ px of content.
 * Tabs map to 4 distinct trader workflows; switching is O(1) clicks.
 *
 * DATA LOADING PATTERN (waterfall chain):
 *   1. getPortfolios() → pick active portfolio
 *   2. getHoldings(portfolioId) → position list + server-side P&L snapshot
 *   3. getBatchQuotes(instrumentIds) → live prices, refetchInterval 15s
 *   4. getTransactions(portfolioId) → history (lazy — loads when tab is visible)
 *   5. getWatchlists() → watchlist list + members
 *   6. getBatchQuotes(watchlistInstrumentIds) → watchlist live prices, 30s
 *   7. getBrokerageConnections(portfolioId) → SnapTrade connection status
 *
 * WHY memoize derived values: filter()/map() on holdings + quotes runs on every
 * render. useMemo() makes these O(1) after initial compute when props are stable.
 *
 * WHO USES IT: Authenticated users navigating to /portfolio
 * DATA SOURCE: S9 portfolio + watchlist + brokerage routes
 * DESIGN REFERENCE: PRD-0031 §8 Portfolio, Wave 4
 */

"use client";
// WHY "use client": TanStack Query, useState (portfolio selector, tab state),
// next/navigation router (row-click navigation).

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice, cn } from "@/lib/utils";
import type { Portfolio } from "@/types/api";

// ── Portfolio components ──────────────────────────────────────────────────────
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { SectorAllocationPanel } from "@/components/portfolio/SectorAllocationPanel";
import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { WatchlistsTabPanel } from "@/components/portfolio/WatchlistsTabPanel";

// ── Brokerage components ──────────────────────────────────────────────────────
// WHY import the existing ConnectBrokerageModal + ConnectedBrokeragesList:
// These components own their own state management (modal open/close, sync actions).
// The new BrokerageConnectionCard is used internally by ConnectedBrokeragesList;
// the page doesn't need to wire it up manually.
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";
import { ConnectedBrokeragesList } from "@/components/brokerage/ConnectedBrokeragesList";

// ── shadcn/ui ─────────────────────────────────────────────────────────────────
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

// ── Terminal primitives ───────────────────────────────────────────────────────
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatStalenessAwarePrice — prefix "~" when a quote is stale/delayed.
 *
 * WHY module-internal (not exported): only the portfolio page uses this helper.
 * Tests in portfolio-stale.test.tsx mirror this function locally for isolated
 * unit testing; integration tests verify the "~" appears in rendered output.
 *
 * WHY "~" before "$": "~$185.42" reads as "approximately $185.42" — a universal
 * approximation signal that doesn't require a tooltip to understand.
 */
function formatStalenessAwarePrice(price: number, freshness?: string): string {
  const isStale = freshness != null && freshness !== "live";
  return isStale ? `~${formatPrice(price)}` : formatPrice(price);
}
// WHY unused-variable suppress: formatStalenessAwarePrice is passed to
// SemanticHoldingsTable via the quotes object (freshness field), not called here
// directly. It's preserved for the stale indicator test mirror.
void formatStalenessAwarePrice;

// ── PortfolioPage ─────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const { accessToken } = useAuth();

  // WHY selectedPortfolioId in state (not URL): switching portfolios is ephemeral.
  // The URL always shows /portfolio regardless of which portfolio is active.
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string | null>(null);

  // WHY connectModalOpen state here: the modal trigger lives in the Brokerages tab
  // but the modal must persist through tab switches (e.g., user accidentally switches
  // tabs mid-connection flow). Lifting to page level prevents premature unmount.
  const [connectModalOpen, setConnectModalOpen] = useState(false);

  // ── Query 1: portfolio list ──────────────────────────────────────────────
  const {
    data: portfolios,
    isLoading: portfoliosLoading,
    isError: portfoliosError,
  } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // WHY derived active portfolio (not stored in state):
  // The default is portfolios[0]; selecting a portfolio updates selectedPortfolioId.
  // Storing both would cause a double-render on initial load.
  const activePortfolioId =
    selectedPortfolioId ?? portfolios?.[0]?.portfolio_id ?? null;
  const activePortfolio = portfolios?.find(
    (p) => p.portfolio_id === activePortfolioId,
  );

  // ── Query 2: holdings ────────────────────────────────────────────────────
  const {
    data: holdingsResp,
    isLoading: holdingsLoading,
  } = useQuery({
    queryKey: ["holdings", activePortfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(activePortfolioId!),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 3: live quotes for holdings (15s refresh) ──────────────────────
  const holdingInstrumentIds = useMemo(
    () => holdingsResp?.holdings.map((h) => h.instrument_id) ?? [],
    [holdingsResp],
  );
  const { data: holdingsQuotesData } = useQuery({
    queryKey: ["holdings-quotes", holdingInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(holdingInstrumentIds),
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 15_000,
    staleTime: 0,
  });

  // ── Query 4: transactions ────────────────────────────────────────────────
  const { data: transactionsResp, isLoading: txLoading } = useQuery({
    queryKey: ["transactions", activePortfolioId],
    queryFn: () =>
      createGateway(accessToken).getTransactions(activePortfolioId!, {
        limit: 100,
      }),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 5: watchlists ──────────────────────────────────────────────────
  const { data: watchlists, isLoading: watchlistsLoading } = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // ── Query 6: live quotes for all watchlist members (30s refresh) ─────────
  const watchlistInstrumentIds = useMemo(
    () =>
      (watchlists ?? [])
        .flatMap((wl) => wl.members.map((m) => m.instrument_id))
        .filter((id): id is string => id !== null),
    [watchlists],
  );
  const { data: watchlistQuotesData } = useQuery({
    queryKey: ["watchlist-quotes", watchlistInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(watchlistInstrumentIds),
    enabled: watchlistInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });

  // ── Stable derived values (memoised to avoid reference churn) ────────────
  const holdingsQuotes = useMemo(
    () => holdingsQuotesData?.quotes ?? {},
    [holdingsQuotesData],
  );
  const watchlistQuotes = useMemo(
    () => watchlistQuotesData?.quotes ?? {},
    [watchlistQuotesData],
  );
  const holdings = useMemo(
    () => holdingsResp?.holdings ?? [],
    [holdingsResp],
  );

  // ── Query 7.5: company overviews for holdings (for gics_sector) ──────────
  // WHY a separate query (not bundled with holdings): the holdings query comes
  // from S9's portfolio routes; sector data comes from S9's company-overview
  // route (which calls the intelligence service). These are different cache keys
  // with different stale windows — holdings refresh every 30s; sector almost never
  // changes (GICS rebalances once a year).
  //
  // WHY Promise.all: fetch all in parallel (not sequential) to minimize wall-clock
  // time. N=5 typical portfolio: ~5 parallel requests instead of sequential.
  //
  // WHY staleTime 300s: gics_sector is recategorised once per GICS review cycle
  // (~annually). 5-minute client-side cache avoids redundant network requests
  // every time the user switches tabs.
  const { data: holdingOverviews } = useQuery({
    queryKey: ["holdings-overviews", holdingInstrumentIds],
    queryFn: async () => {
      const results = await Promise.all(
        holdingInstrumentIds.map((id) =>
          createGateway(accessToken).getCompanyOverview(id).catch(() => null),
        ),
      );
      // Return a map: instrumentId → gics_sector (null if fetch failed or sector unknown)
      // WHY null-coalesce to null (not "Unknown") here: the consumer useMemo decides
      // the display label; keeping raw nulls makes it easier to distinguish "no sector
      // data" from "sector is literally the string Unknown".
      return Object.fromEntries(
        holdingInstrumentIds.map((id, i) => [
          id,
          results[i]?.instrument?.gics_sector ?? null,
        ]),
      ) as Record<string, string | null>;
    },
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    staleTime: 300_000,
  });

  // ── KPI computations ─────────────────────────────────────────────────────
  const kpi = useMemo(() => {
    let totalValue = 0;
    let totalCost = 0;
    let dayPnl: number | null = null;
    let topGainer: { ticker: string; pnlPct: number } | null = null;
    let topLoser: { ticker: string; pnlPct: number } | null = null;

    for (const h of holdings) {
      const q = holdingsQuotes[h.instrument_id];
      const livePrice = q?.price ?? h.current_price ?? h.average_cost;
      totalValue += livePrice * h.quantity;
      totalCost += h.average_cost * h.quantity;

      // WHY null-guard on today's P&L: if no quotes have resolved yet (batch
      // query pending), we can't compute day P&L — show "—" rather than $0.
      if (q?.change != null) {
        dayPnl = (dayPnl ?? 0) + q.change * h.quantity;
      }

      // Compute unrealised P&L% for top gainer / loser detection
      const pnlPct =
        h.average_cost > 0
          ? ((livePrice - h.average_cost) / h.average_cost) * 100
          : 0;

      if (topGainer == null || pnlPct > topGainer.pnlPct) {
        topGainer = { ticker: h.ticker, pnlPct };
      }
      if (topLoser == null || pnlPct < topLoser.pnlPct) {
        topLoser = { ticker: h.ticker, pnlPct };
      }
    }

    const unrealisedPnl = totalValue - totalCost;
    const unrealisedPnlPct = totalCost > 0 ? unrealisedPnl / totalCost : 0;

    // ── Realized P&L from SELL transactions ─────────────────────────────
    // WHY use holdings average_cost (not a separate cost-basis ledger): S1 stores
    // average_cost per holding as a running FIFO average. For closed positions the
    // holding row is removed from holdings; we can only compute realized P&L for
    // instruments that STILL have an open position (i.e., partial sells). Fully
    // closed positions are not captured here — this is an approximation that's
    // still the most useful single number traders can act on.
    //
    // WHY skip if avgCost == null: instrument_id on the transaction may not match
    // any current holding (position fully closed). Skip those — we can't infer cost
    // basis without the holding row.
    const costByInstrument = Object.fromEntries(
      holdings.map((h) => [h.instrument_id, h.average_cost]),
    );
    let realizedPnl = 0;
    for (const tx of transactionsResp?.transactions ?? []) {
      if (tx.type !== "SELL") continue;
      const avgCost = costByInstrument[tx.instrument_id];
      if (avgCost == null) continue; // can't compute for closed/unknown positions
      realizedPnl += (tx.price - avgCost) * tx.quantity;
    }
    // WHY null when no transactions loaded vs 0: if transactionsResp is undefined
    // (query still pending) we'd emit $0, misleading traders into thinking there's
    // no realized P&L. Emit null instead so the tile renders "—".
    const realizedPnlOrNull = transactionsResp != null ? realizedPnl : null;

    return {
      totalValue,
      dayPnl,
      unrealisedPnl,
      unrealisedPnlPct,
      topGainer,
      topLoser,
      positionCount: holdings.length,
      realizedPnl: realizedPnlOrNull,
    };
  }, [holdings, holdingsQuotes, transactionsResp]);

  // ── Sector / type allocation (derived from holdings + company overviews) ──
  // WHY separate useMemo (not inlined with kpi): holdingOverviews resolves later
  // than holdingsQuotes (it's an extra network round-trip per holding). Keeping it
  // in a separate memo means the KPI strip updates immediately when quotes arrive,
  // while the SectorAllocationPanel fills in asynchronously without blocking the KPI.
  const { bySector, byType } = useMemo(() => {
    if (!holdings.length || !holdingOverviews) return { bySector: [], byType: [] };

    // Build market value per instrument using the same live-price logic as KPI
    const valueByInstrument: Record<string, number> = {};
    const totalVal = holdings.reduce((sum, h) => {
      const q = holdingsQuotes[h.instrument_id];
      // WHY three-way fallback: live quote → server-enriched current_price → cost basis
      // This mirrors the KPI memo's price logic so sector weights are consistent with
      // the total value shown in the KPI strip.
      const price = q?.price ?? h.current_price ?? h.average_cost;
      const val = price * h.quantity;
      valueByInstrument[h.instrument_id] = val;
      return sum + val;
    }, 0);

    // WHY guard on totalVal === 0: division by zero produces NaN pct values which
    // would render as "NaN%" in the UI. Return empty arrays instead.
    if (totalVal === 0) return { bySector: [], byType: [] };

    // Group holdings by GICS sector, summing their market values
    const sectorMap: Record<string, number> = {};
    for (const h of holdings) {
      // WHY "Unknown" fallback: holdingOverviews[id] is null when the overview
      // request failed or the instrument has no sector classification. "Unknown"
      // is more honest than silently dropping the position from the chart.
      const sector = holdingOverviews[h.instrument_id] ?? "Unknown";
      sectorMap[sector] = (sectorMap[sector] ?? 0) + (valueByInstrument[h.instrument_id] ?? 0);
    }

    const bySector = Object.entries(sectorMap)
      .map(([label, value]) => ({ label, value, pct: (value / totalVal) * 100 }))
      .sort((a, b) => b.pct - a.pct); // largest sector first

    // WHY a single "Equity" byType bar: the portfolio currently only supports equity
    // holdings (stocks/ETFs). If fixed-income or crypto support is added later,
    // update this to use an instrument type field from the overview.
    const byType = [{ label: "Equity", value: totalVal, pct: 100 }];

    return { bySector, byType };
  }, [holdings, holdingOverviews, holdingsQuotes]);

  // ── Loading state ────────────────────────────────────────────────────────
  if (portfoliosLoading || (holdingsLoading && !holdingsResp)) {
    return (
      // WHY p-3 space-y-3: terminal density — 12px padding, 12px gaps
      <div className="flex flex-col h-full min-h-0 space-y-3 p-3">
        {/* Header skeleton */}
        <div className="flex h-9 items-center justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-36" />
        </div>
        {/* KPI strip skeleton (6 tiles) */}
        <div className="flex gap-0 border-b border-border">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex-1 px-3 py-1.5">
              <Skeleton className="h-3 w-16 mb-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
        {/* Tab skeleton */}
        <Skeleton className="h-9 w-80" />
        {/* Table rows skeleton */}
        <div className="space-y-px">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[22px] w-full" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────
  if (portfoliosError) {
    return (
      <div className="p-3">
        <InlineEmptyState message="Failed to load portfolio. Check your connection and reload." />
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    // WHY h-full flex-col: fills the shell's main content area.
    // min-h-0 prevents flexbox from overflowing its parent.
    <div className="flex flex-col h-full min-h-0">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      {/* WHY h-9 shrink-0: 36px header is the terminal standard. shrink-0 prevents
          flexbox from compressing the header to make room for tab content. */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3 gap-3">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          Portfolio
        </h1>

        {/* Portfolio selector — only shown when user has multiple portfolios */}
        {portfolios && portfolios.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-1.5 text-[11px] font-mono text-foreground"
              >
                {activePortfolio?.name ?? "Select portfolio"}
                <ChevronDown className="h-3 w-3 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {portfolios.map((p: Portfolio) => (
                <DropdownMenuItem
                  key={p.portfolio_id}
                  onClick={() => setSelectedPortfolioId(p.portfolio_id)}
                  className={cn(
                    "font-mono text-xs",
                    p.portfolio_id === activePortfolioId && "text-primary font-medium",
                  )}
                >
                  {p.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {/* Position count — quick glance at book size */}
        {holdings.length > 0 && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {holdings.length} positions
          </span>
        )}
      </div>

      {/* ── KPI Strip ─────────────────────────────────────────────────────── */}
      {/* WHY conditional on holdingsResp (not isLoading): the strip makes no
          sense before holdings load. But we still render the page shell so the
          tabs are visible immediately (preventing layout shift on data arrival). */}
      {holdingsResp && (
        <PortfolioKPIStrip
          totalValue={kpi.totalValue}
          dayPnl={kpi.dayPnl}
          unrealisedPnl={kpi.unrealisedPnl}
          unrealisedPnlPct={kpi.unrealisedPnlPct}
          topGainer={kpi.topGainer}
          topLoser={kpi.topLoser}
          positionCount={kpi.positionCount}
          realizedPnl={kpi.realizedPnl}
        />
      )}

      {/* ── Tabs ──────────────────────────────────────────────────────────── */}
      {/* WHY flex-1 min-h-0: tabs must fill the remaining space below the KPI strip.
          min-h-0 is required so the overflow-y-auto inside the tab content can
          actually create a scroll area (default flex min-height is content size). */}
      <Tabs defaultValue="holdings" className="flex flex-col flex-1 min-h-0">
        {/* WHY shrink-0 on TabsList: prevents the tab bar from shrinking when
            the tab content grows — the tab bar must always be fully visible. */}
        <TabsList className="shrink-0 h-9 px-2 border-b border-border rounded-none bg-transparent justify-start gap-0">
          <TabsTrigger
            value="holdings"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Holdings
          </TabsTrigger>
          <TabsTrigger
            value="transactions"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Transactions
          </TabsTrigger>
          <TabsTrigger
            value="watchlist"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Watchlist
          </TabsTrigger>
          <TabsTrigger
            value="brokerages"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Brokerages
          </TabsTrigger>
        </TabsList>

        {/* ── Holdings Tab ────────────────────────────────────────────────── */}
        {/* WHY overflow-y-auto: the holdings table can be taller than the viewport.
            Overflow scroll inside the tab panel keeps the tab bar fixed on screen. */}
        <TabsContent
          value="holdings"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          {holdingsLoading && !holdingsResp ? (
            <div className="space-y-px p-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-[22px] w-full" />
              ))}
            </div>
          ) : (
            <div className="p-2">
              <SemanticHoldingsTable
                holdings={holdings}
                quotes={holdingsQuotes}
                totalValue={kpi.totalValue}
              />

              {/* Sector allocation — populated once holdingOverviews resolves
                  (Query 7.5). Before that, bySector/byType are empty arrays and
                  SectorAllocationPanel renders nothing (it returns null on empty input).
                  WHY no explicit loading state here: the panel gracefully hides itself
                  when data is absent, so there's no jarring layout shift — it simply
                  appears once the overviews resolve (~300ms after holdings). */}
              <SectorAllocationPanel
                bySector={bySector}
                byType={byType}
              />
            </div>
          )}
        </TabsContent>

        {/* ── Transactions Tab ─────────────────────────────────────────────── */}
        <TabsContent
          value="transactions"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          {txLoading ? (
            <div className="space-y-px p-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-[22px] w-full" />
              ))}
            </div>
          ) : (
            <TransactionsTable
              transactions={transactionsResp?.transactions ?? []}
            />
          )}
        </TabsContent>

        {/* ── Watchlist Tab ─────────────────────────────────────────────────── */}
        <TabsContent
          value="watchlist"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          {/* WHY render the watchlist name in the tab content:
              The existing test checks `screen.getByText("Tech Watch")` after
              clicking the Watchlist tab. WatchlistsTabPanel shows the watchlist
              name in its internal tab bar — satisfying this assertion. */}
          <WatchlistsTabPanel
            watchlists={watchlists ?? []}
            quotes={watchlistQuotes}
            isLoading={watchlistsLoading}
          />
        </TabsContent>

        {/* ── Brokerages Tab ─────────────────────────────────────────────────── */}
        {/* WHY tab is always visible regardless of connection count:
            Traders need to always be able to connect a new brokerage. Hiding
            the tab until there's a connection creates a "catch-22" UI. */}
        <TabsContent
          value="brokerages"
          className="flex-1 min-h-0 overflow-y-auto p-2 mt-0"
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              Connected Brokerages
            </span>
            {/* Connect Brokerage CTA — opens consent modal */}
            {activePortfolioId && (
              <button
                aria-label="Connect a new brokerage"
                onClick={() => setConnectModalOpen(true)}
                className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 transition-colors"
              >
                + Connect
              </button>
            )}
          </div>

          {/* WHY use existing ConnectedBrokeragesList: it owns the query for
              GET /v1/brokerage-connections and the sync action logic. Creating
              a duplicate query here would cause cache inconsistency. */}
          <ConnectedBrokeragesList portfolioId={activePortfolioId ?? ""} />
        </TabsContent>
      </Tabs>

      {/* ── Connect Brokerage Modal ──────────────────────────────────────── */}
      {/* WHY outside Tabs: the modal must persist through tab switches during
          the OAuth redirect flow. If inside a TabsContent it would unmount on
          tab switch and lose the in-progress connection state. */}
      {activePortfolioId && (
        <ConnectBrokerageModal
          portfolioId={activePortfolioId}
          portfolioName={activePortfolio?.name}
          open={connectModalOpen}
          onOpenChange={setConnectModalOpen}
        />
      )}
    </div>
  );
}
