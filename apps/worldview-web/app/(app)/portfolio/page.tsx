/**
 * app/(app)/portfolio/page.tsx — Full Portfolio Page (Terminal Redesign, Wave 4)
 *
 * WHY THIS EXISTS: The dashboard PortfolioSummary widget shows only a 4-tile
 * summary. This page is the trader's full position-management view:
 *
 *   Holdings    — 10-column semantic table with live P&L + sector allocation
 *   Transactions — filter by BUY/SELL/DIVIDEND, newest-first
 *   Watchlist   — per-watchlist tabs with live prices (30s refresh)
 *   Brokerages  — collapsible panel inside the Transactions tab
 *
 * WHY FOUR TABS (not panels): keeping 4 data surfaces in one view without tabs
 * would require a vertical scroll marathon through 500+ px of content.
 * Tabs map to 4 distinct trader workflows; switching is O(1) clicks.
 *
 * ARCHITECTURE (PLAN-0059 E-2-followup): the page is now a thin shell that:
 *   1. Loads data via `usePortfolioData()` — owns all 8 queries + KPI maths
 *      + ROOT-first sort + cross-mutation invalidations + the F-013
 *      archive mutation.
 *   2. Renders four extracted components: PortfolioPageHeader,
 *      PerformanceStrip, PortfolioKPIStrip, HoldingsTab/TransactionsTab/
 *      WatchlistsTabPanel.
 *   3. Owns three pieces of dialog-related state (open/close booleans for
 *      the three dialogs) — these intentionally stay at page level so
 *      buttons in the header can open dialogs at the page root.
 *
 * WHO USES IT: Authenticated users navigating to /portfolio.
 * DATA SOURCE: S9 portfolio + watchlist + brokerage routes (via the hook).
 * DESIGN REFERENCE: PRD-0031 §8 Portfolio, Wave 4.
 */

"use client";
// WHY "use client": useState (dialog open/close + equity-curve period),
// hook drives TanStack Query, child components include Radix portals.

import { useState } from "react";

import { useAuth } from "@/hooks/useAuth";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";

// ── Portfolio chrome ────────────────────────────────────────────────────────
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import { WatchlistsTabPanel } from "@/components/portfolio/WatchlistsTabPanel";
// F-P-003 (PLAN-0051 W6): the equity-curve period state is hoisted to this
// page so future panels can react to the same period. The type comes from
// EquityCurveChart so the canonical period set lives in one place.
import type { PeriodLabel } from "@/components/portfolio/EquityCurveChart";

// ── Brokerage modal ─────────────────────────────────────────────────────────
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";

// ── Terminal primitives ─────────────────────────────────────────────────────
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Extracted dialogs + tab bodies + orchestrator hook ─────────────────────
import { CreatePortfolioDialog } from "@/features/portfolio/components/CreatePortfolioDialog";
import { AddPositionDialog } from "@/features/portfolio/components/AddPositionDialog";
import { DeletePortfolioDialog } from "@/features/portfolio/components/DeletePortfolioDialog";
import { PortfolioPageHeader } from "@/features/portfolio/components/PortfolioPageHeader";
import { PerformanceStrip } from "@/features/portfolio/components/PerformanceStrip";
import { HoldingsTab } from "@/features/portfolio/components/HoldingsTab";
import { TransactionsTab } from "@/features/portfolio/components/TransactionsTab";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";

// ── PortfolioPage ───────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const { accessToken } = useAuth();

  // T-B-2-07: KPI strip is hard-locked to "1D". The const stays narrow so
  // queryKey shapes downstream compile unchanged.
  const selectedPeriod = "1D" as const;

  // ── Dialog open/close state (page-scoped so headers can trigger them) ─
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  const [createPortfolioOpen, setCreatePortfolioOpen] = useState(false);
  const [addPositionOpen, setAddPositionOpen] = useState(false);
  const [deletePortfolioOpen, setDeletePortfolioOpen] = useState(false);

  // ── F-P-003: hoisted equity-curve period state ────────────────────────
  // WHY 3M default: matches Bloomberg PORT default — long enough to show a
  // meaningful trend without compressing the most recent moves.
  const [equityPeriod, setEquityPeriod] = useState<PeriodLabel>("3M");

  // ── Data orchestrator ──────────────────────────────────────────────────
  // All 8 queries + derived KPI/allocations/scope hint live in the hook.
  // The hook also owns the F-013 delete mutation and the two cross-mutation
  // invalidation callbacks.
  const data = usePortfolioData({ accessToken, selectedPeriod });
  const {
    sortedPortfolios,
    setSelectedPortfolioId,
    activePortfolioId,
    activePortfolio,
    activeIsRoot,
    portfoliosLoading,
    portfoliosError,
    holdingsLoading,
    txLoading,
    watchlistsLoading,
    holdingsResp,
    enrichedHoldings,
    holdingsQuotes,
    holdingOverviews,
    transactionsResp,
    watchlists,
    watchlistQuotes,
    performanceData,
    performanceLoading,
    realizedPnLQuery,
    kpi,
    bySector,
    byType,
    scopeHint,
    handlePortfolioCreated,
    handlePositionAdded,
    deletePortfolioMutation,
  } = data;

  // ── Loading state (initial mount, no portfolios yet) ──────────────────
  if (portfoliosLoading || (holdingsLoading && !holdingsResp)) {
    return (
      // WHY p-3 space-y-3: terminal density — 12px padding, 12px gaps.
      <div className="flex flex-col h-full min-h-0 space-y-3 p-3">
        <div className="flex h-9 items-center justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-36" />
        </div>
        {/* F-P-020 (PLAN-0051 W6): KPI strip skeleton mirrors the populated
            strip's shape exactly — same 7 tiles, same `divide-x` separator,
            same px-3/py-1.5 padding. Any mismatch causes layout shift when
            the data resolves. */}
        <div className="flex divide-x divide-border border-b border-border">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="flex-1 px-3 py-1.5">
              <Skeleton className="h-3 w-16 mb-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
        <Skeleton className="h-9 w-80" />
        {/* F-P-020: row skeletons use h-[22px] to match the real holdings
            row height token. */}
        <div className="space-y-px">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[22px] w-full" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────
  if (portfoliosError) {
    return (
      <div className="p-3">
        <InlineEmptyState message="Failed to load portfolio data. Check your connection and reload." />
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────
  // WHY h-full flex-col: fills the shell's main content area.
  // WHY bg-background (not bg-card): the page is the lowest level of the
  // elevation hierarchy. Panels inside (analytics cards, dialogs, sticky
  // table headers) use bg-card (#111113). Page = bg-background (#09090B)
  // is one shade darker so the 1px borders + tonal step give each card
  // its own silhouette.
  // F-P-019 (PLAN-0051 W6): mobile safe-area insets — env() values are 0
  // on desktop, ~44px/34px on iPhones with Face ID.
  return (
    <div className="flex flex-col h-full min-h-0 bg-background pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      <PortfolioPageHeader
        sortedPortfolios={sortedPortfolios}
        activePortfolio={activePortfolio}
        activePortfolioId={activePortfolioId}
        activeIsRoot={activeIsRoot}
        holdingCount={enrichedHoldings.length}
        scopeHint={scopeHint}
        onSelectPortfolio={setSelectedPortfolioId}
        onAddPosition={() => setAddPositionOpen(true)}
        onCreatePortfolio={() => setCreatePortfolioOpen(true)}
        onDeletePortfolio={() => setDeletePortfolioOpen(true)}
      />

      <PerformanceStrip
        period={selectedPeriod}
        performanceData={performanceData}
        performanceLoading={performanceLoading}
      />

      {/* ── KPI Strip ───────────────────────────────────────────────────── */}
      {/* WHY conditional on holdingsResp (not isLoading): the strip makes no
          sense before holdings load. We still render the page shell so the
          tabs are visible immediately (preventing layout shift on data
          arrival). */}
      {/* PLAN-0051 T-A-1-05 — prefer the FIFO endpoint when it succeeds;
          fall back to the legacy client-side approximation (kpi.realizedPnl)
          and surface "(approx)" so traders know the value is not the FIFO
          ground truth. */}
      {holdingsResp &&
        (() => {
          const fifo = realizedPnLQuery.data;
          const useFifo = !realizedPnLQuery.isError && fifo != null;
          const realizedPnl = useFifo ? fifo!.total_realized : kpi.realizedPnl;
          return (
            <PortfolioKPIStrip
              totalValue={kpi.totalValue}
              dayPnl={kpi.dayPnl}
              unrealisedPnl={kpi.unrealisedPnl}
              unrealisedPnlPct={kpi.unrealisedPnlPct}
              topGainer={kpi.topGainer}
              topLoser={kpi.topLoser}
              positionCount={kpi.positionCount}
              realizedPnl={realizedPnl}
              realizedPnlApprox={!useFifo}
              realizedPnlLongTerm={useFifo ? fifo!.realized_long_term : null}
              realizedPnlShortTerm={useFifo ? fifo!.realized_short_term : null}
            />
          );
        })()}

      {/* ── Tabs ────────────────────────────────────────────────────────── */}
      {/* WHY flex-1 min-h-0: tabs must fill the remaining space below the
          KPI strip. min-h-0 is required so the overflow-y-auto inside the
          tab content can actually create a scroll area. */}
      <Tabs defaultValue="holdings" className="flex flex-col flex-1 min-h-0">
        {/* WHY shrink-0 on TabsList: prevents the tab bar from shrinking
            when the tab content grows. WHY bg-card: the tab bar is page
            chrome — keeps it tonally aligned with the KPI strip and
            page header above. */}
        <TabsList className="shrink-0 h-9 px-2 border-b border-border rounded-none bg-card justify-start gap-0">
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
          {/* WHY no Brokerages tab: merged into Transactions as a
              collapsible panel so traders can see connection status
              without leaving the transaction context. */}
        </TabsList>

        <TabsContent
          value="holdings"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          <HoldingsTab
            activePortfolioId={activePortfolioId}
            holdingsLoading={holdingsLoading}
            holdingsResp={holdingsResp}
            enrichedHoldings={enrichedHoldings}
            holdingsQuotes={holdingsQuotes}
            holdingOverviews={holdingOverviews}
            kpi={kpi}
            bySector={bySector}
            byType={byType}
            equityPeriod={equityPeriod}
            setEquityPeriod={setEquityPeriod}
          />
        </TabsContent>

        <TabsContent
          value="transactions"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0 flex flex-col"
        >
          <TransactionsTab
            activePortfolioId={activePortfolioId}
            txLoading={txLoading}
            transactionsResp={transactionsResp}
            holdingOverviews={holdingOverviews}
            onConnect={() => setConnectModalOpen(true)}
          />
        </TabsContent>

        <TabsContent
          value="watchlist"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          {/* WHY render the watchlist name in the tab content: the existing
              test checks `screen.getByText("Tech Watch")` after clicking the
              Watchlist tab. WatchlistsTabPanel shows the watchlist name in
              its internal tab bar — satisfying this assertion. */}
          <WatchlistsTabPanel
            watchlists={watchlists ?? []}
            quotes={watchlistQuotes}
            isLoading={watchlistsLoading}
          />
        </TabsContent>
      </Tabs>

      {/* ── Connect Brokerage Modal ─────────────────────────────────────── */}
      {/* WHY outside Tabs: the modal must persist through tab switches during
          the OAuth redirect flow. */}
      {activePortfolioId && (
        <ConnectBrokerageModal
          portfolioId={activePortfolioId}
          portfolioName={activePortfolio?.name}
          open={connectModalOpen}
          onOpenChange={setConnectModalOpen}
        />
      )}

      {/* ── Create Portfolio Dialog ─────────────────────────────────────── */}
      <CreatePortfolioDialog
        open={createPortfolioOpen}
        onOpenChange={setCreatePortfolioOpen}
        onSuccess={(p) => {
          setCreatePortfolioOpen(false);
          handlePortfolioCreated(p);
        }}
        accessToken={accessToken}
      />

      {/* ── F-013: Delete Portfolio confirmation ────────────────────────── */}
      {activePortfolioId && activePortfolio && (
        <DeletePortfolioDialog
          open={deletePortfolioOpen}
          onOpenChange={setDeletePortfolioOpen}
          activePortfolio={activePortfolio}
          activePortfolioId={activePortfolioId}
          isPending={deletePortfolioMutation.isPending}
          isError={deletePortfolioMutation.isError}
          onConfirm={(id) => {
            // The mutation's onSuccess (in the hook) clears the active
            // selection; we close the dialog here so the user gets instant
            // feedback before the refetch completes.
            deletePortfolioMutation.mutate(id, {
              onSuccess: () => setDeletePortfolioOpen(false),
            });
          }}
        />
      )}

      {/* ── Add Position Dialog ─────────────────────────────────────────── */}
      {activePortfolioId && (
        <AddPositionDialog
          open={addPositionOpen}
          onOpenChange={setAddPositionOpen}
          onSuccess={() => {
            setAddPositionOpen(false);
            handlePositionAdded();
          }}
          portfolioId={activePortfolioId}
          accessToken={accessToken}
        />
      )}
    </div>
  );
}
