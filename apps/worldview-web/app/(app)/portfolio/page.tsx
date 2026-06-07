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
 * PLAN-0059-G Wave G-2: The three portfolio dialogs (Create, AddPosition, Delete)
 * are lazy-loaded via next/dynamic. Dialogs are only rendered after a button click
 * — loading their JS (react-hook-form, zod, Radix Dialog portal) eagerly on page
 * load wastes parse budget. Lazy-loading saves ~60–80KB from the initial bundle.
 * These dialogs use Radix Dialog which opens a DOM portal — ssr:false is correct.
 */

"use client";
// WHY "use client": useState (dialog open/close + equity-curve period),
// hook drives TanStack Query, child components include Radix portals,
// and nuqs URL state hooks are browser-only.

import { useState, useTransition } from "react";
// PLAN-0059 C-6: useQueryState backs the active-tab + equity-period in the
// URL so deep-links round-trip ("share my Holdings view at 1Y period").
// `parseAsStringLiteral` constrains the value to the allowed set; an
// unknown URL value falls back to the default instead of crashing.
import { useQueryState, parseAsStringLiteral } from "nuqs";
import dynamic from "next/dynamic";

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

// ── Lazy-loaded portfolio dialogs ───────────────────────────────────────────
// WHY next/dynamic for dialogs: the three dialogs each pull in react-hook-form,
// zod, and the Radix Dialog portal. None of these are needed on initial page load
// — they only mount when the user clicks a header button. Deferring their load
// saves ~60–80KB of JS parse cost from the /portfolio initial bundle.
// WHY ssr:false: Radix Dialog renders a portal (document.body append) which
// requires a browser DOM. SSR would produce a hydration mismatch.
// WHY null loading: dialog components are controlled (open=false by default).
// The <Dialog open={false}> renders nothing visible — a loading Skeleton would
// never appear to the user because `open` stays false until the button is clicked,
// by which time the bundle will have loaded (dialogs are tiny, <30KB each).
const CreatePortfolioDialog = dynamic(
  () => import("@/features/portfolio/components/CreatePortfolioDialog").then((m) => ({ default: m.CreatePortfolioDialog })),
  {
    ssr: false, // Radix Dialog portal requires browser DOM
    loading: () => null, // dialog starts closed; skeleton is never visible
  },
);

const AddPositionDialog = dynamic(
  () => import("@/features/portfolio/components/AddPositionDialog").then((m) => ({ default: m.AddPositionDialog })),
  {
    ssr: false, // Radix Dialog portal requires browser DOM
    loading: () => null, // dialog starts closed; skeleton is never visible
  },
);

const DeletePortfolioDialog = dynamic(
  () => import("@/features/portfolio/components/DeletePortfolioDialog").then((m) => ({ default: m.DeletePortfolioDialog })),
  {
    ssr: false, // Radix Dialog portal requires browser DOM
    loading: () => null, // dialog starts closed; skeleton is never visible
  },
);

// ── Static imports (needed immediately on paint) ───────────────────────────
import { PortfolioPageHeader } from "@/features/portfolio/components/PortfolioPageHeader";
import { PerformanceStrip } from "@/features/portfolio/components/PerformanceStrip";
import { HoldingsTab } from "@/features/portfolio/components/HoldingsTab";
import { TransactionsTab } from "@/features/portfolio/components/TransactionsTab";
// Wave G: AnalyticsTab is the new third tab (Holdings | Transactions | Analytics).
// WHY static import (not dynamic): AnalyticsTab mounts charts from recharts which
// is already in the bundle. The lazy-load savings would be minimal and would cause
// a visible blank flash when the user first clicks Analytics.
import { AnalyticsTab } from "@/features/portfolio/components/AnalyticsTab";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";
// PLAN-0070 C-1: fire the bundle endpoint to warm the cache in one round-trip.
import { usePortfolioBundle } from "@/features/portfolio/hooks/usePortfolioBundle";

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
  // C-6: backed by URL `?period=` so deep-links round-trip. `clearOnDefault`
  // keeps the URL clean when the user is on the default — no `?period=3M`
  // noise on first visit.
  const [equityPeriod, setEquityPeriod] = useQueryState(
    "period",
    parseAsStringLiteral([
      "1W",
      "1M",
      "3M",
      "6M",
      "1Y",
      "All",
    ] as const satisfies readonly PeriodLabel[])
      .withDefault("3M")
      .withOptions({ clearOnDefault: true }),
  );

  // ── C-6: URL-backed active tab ──────────────────────────────────────────
  // WHY URL state for the tab: traders share specific views ("look at the
  // transaction history for AAPL") and expect back/forward to navigate
  // between tabs. WHY clearOnDefault: omitting `?tab=holdings` from the URL
  // when Holdings is active keeps the canonical /portfolio link short.
  // Wave G: "analytics" added as a third tab. The Watchlist tab moves here
  // as the fourth; the tab bar now shows Holdings | Transactions | Analytics | Watchlist.
  // WHY add to the literal union (not a separate state): nuqs parseAsStringLiteral
  // validates the value at the URL boundary — unknown ?tab= values fall back to
  // "holdings" automatically, so old bookmarks with ?tab=watchlist still work.
  const [activeTab, setActiveTab] = useQueryState(
    "tab",
    parseAsStringLiteral(["holdings", "transactions", "analytics", "watchlist"] as const)
      .withDefault("holdings")
      .withOptions({ clearOnDefault: true }),
  );

  // PLAN-0059 G-3: tab switches mount/unmount whole panel trees (Holdings
  // alone renders ~7 child surfaces — equity-curve chart, holdings table,
  // sector treemap, recent activity, dividend timeline, analytics section).
  // Wrapping setActiveTab in useTransition lets React render the new tab in
  // a low-priority pass — the trigger button keeps responding to clicks /
  // keyboard during the heavy mount, instead of feeling momentarily frozen.
  // `isPending` is exposed so the active trigger can show a subtle pending
  // affordance if/when designs ever ask for one.
  const [, startTabTransition] = useTransition();

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

  // PLAN-0070 C-1: fire the bundle endpoint for the active portfolio.
  // WHY here (not inside usePortfolioData): the bundle is an optimisation layer —
  // individual queries still own their own cache entries. Calling the hook here
  // fires GET /v1/portfolio/{id}/bundle once activePortfolioId is known,
  // collapsing 4 downstream requests into 1 round-trip on cold start.
  // The hook is a no-op when portfolioId or accessToken are null.
  usePortfolioBundle({ portfolioId: activePortfolioId, accessToken });

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
              portfolioId={activePortfolioId}
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
      <Tabs
        value={activeTab}
        onValueChange={(v) => {
          // G-3: defer the heavy tab-body render so the trigger row stays
          // interactive while React mounts the new TabsContent tree.
          // Inside startTransition the cast keeps TS strict-mode happy.
          startTabTransition(() => {
            void setActiveTab(v as "holdings" | "transactions" | "analytics" | "watchlist");
          });
        }}
        className="flex flex-col flex-1 min-h-0"
      >
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
          {/* Wave G: Analytics tab — TWR vs benchmark, drawdown chart, risk metrics,
              period returns, and contribution-to-return attribution. Added between
              Transactions and Watchlist per design spec §4.3. */}
          <TabsTrigger
            value="analytics"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Analytics
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
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0 bg-background"
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
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0 flex flex-col bg-background"
        >
          <TransactionsTab
            activePortfolioId={activePortfolioId}
            txLoading={txLoading}
            transactionsResp={transactionsResp}
            holdingOverviews={holdingOverviews}
            onConnect={() => setConnectModalOpen(true)}
          />
        </TabsContent>

        {/* Wave G Analytics tab */}
        <TabsContent
          value="analytics"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0 bg-background"
        >
          {/* WHY guard on activePortfolioId: AnalyticsTab fires useQuery calls
              that require a valid portfolioId. Rendering with null would cause
              the queries to fire enabled=false but the component still mounts
              its full DOM tree, including chart containers, which wastes paint. */}
          {activePortfolioId ? (
            <AnalyticsTab portfolioId={activePortfolioId} />
          ) : (
            <div className="p-3 text-[11px] text-muted-foreground font-mono">
              Select a portfolio to view analytics.
            </div>
          )}
        </TabsContent>

        <TabsContent
          value="watchlist"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0 bg-background"
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
