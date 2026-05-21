/**
 * app/(app)/portfolio/page.tsx — Portfolio Overview Page (PRD-0089 W2 redesign).
 *
 * WHY THIS CHANGED (W2): the 4-tab layout is replaced by a single dense overview
 * that fits above the fold at 1440px. Heavy-lift analytics panels are relocated
 * to /portfolio/analytics; transaction history moves to /portfolio/transactions.
 * This follows Bloomberg PORT's one-page-per-portfolio pattern — traders scan
 * holdings + KPIs + contributors in one view without switching tabs.
 *
 * COMPONENT STACK (top → bottom):
 *   1. PortfolioPageHeader         — name, scope hint, action buttons
 *   2. BrokerageStatusBanner       — last sync time + error flag (gated: broker only)
 *   3. PortfolioKPIStrip           — 8 tiles: total / day / unrealised / realized / cash / buying-pwr / gainer / loser
 *   4. ExposureCurrencyStrip       — invested / cash / leverage / beta-adj (22px)
 *   5. ConcentrationSectorTeaseStrip — HHI + top-3 sectors (22px)
 *   6. PerformanceChartPanel       — 120px collapsible line chart + SPY overlay
 *   7. SectorAllocationBar         — 22px stacked sector bar
 *   8. HoldingsTableChrome         — 22px filter / count chrome
 *   9. SemanticHoldingsTable       — 14-col AG Grid (rowHeight=20, context.holdingsSeries)
 *  10. ContributorsStrip           — top-4 contributors + detractors (96px)
 *  11. RecentActivityStrip         — last-8 transactions (transactions only, no sync events)
 *
 * EMPTY STATE: BrokerageEmptyState replaces all content when holdings=0 AND !loading (V18).
 *
 * HOTKEYS (page-scoped):
 *   b/B → /dashboard   t/T → /portfolio/transactions   a/A → /portfolio/analytics
 *   w/W → /watchlists   r/R → invalidate all portfolio queries
 *   c/C → toggle chart collapsed   1–5 → period chips   0 → "All"
 *
 * WHO USES IT: authenticated users navigating to /portfolio.
 * DATA SOURCE: S9 portfolio routes (via usePortfolioData orchestrator).
 * DESIGN REFERENCE: PRD-0089 W2 §4.19, V-overview wireframe.
 */

"use client";
// WHY "use client": useState for local UI state (dialogs, chart collapsed, filter),
// hotkey useEffect (document.addEventListener), nuqs URL state (period param),
// TanStack Query client (useQueryClient for manual invalidation).

import { useState, useEffect, useCallback } from "react";
import { useQueryState, parseAsStringLiteral } from "nuqs";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { qk } from "@/lib/query/keys";

// ── Portfolio chrome components ─────────────────────────────────────────────
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import { ExposureCurrencyStrip } from "@/components/portfolio/ExposureCurrencyStrip";
import { ConcentrationSectorTeaseStrip } from "@/components/portfolio/ConcentrationSectorTeaseStrip";
import { PerformanceChartPanel } from "@/components/portfolio/PerformanceChartPanel";
import type { PerfPeriod } from "@/components/portfolio/PerformanceChartPanel";
import { SectorAllocationBar } from "@/components/portfolio/SectorAllocationBar";
import { HoldingsTableChrome } from "@/components/portfolio/HoldingsTableChrome";
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { ContributorsStrip } from "@/components/portfolio/ContributorsStrip";
import { RecentActivityStrip } from "@/components/portfolio/RecentActivityStrip";
import { BrokerageEmptyState } from "@/components/portfolio/BrokerageEmptyState";
import { BrokerageStatusBanner } from "@/components/portfolio/BrokerageStatusBanner";
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Data hooks ─────────────────────────────────────────────────────────────
import { PortfolioPageHeader } from "@/features/portfolio/components/PortfolioPageHeader";
import { usePortfolioData } from "@/features/portfolio/hooks/usePortfolioData";
import { usePortfolioBundle } from "@/features/portfolio/hooks/usePortfolioBundle";
import { useTopMovers } from "@/features/portfolio/hooks/useTopMovers";
import { useHoldingsSeries } from "@/features/portfolio/hooks/useHoldingsSeries";

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
  { ssr: false, loading: () => null },
);

const AddPositionDialog = dynamic(
  () => import("@/features/portfolio/components/AddPositionDialog").then((m) => ({ default: m.AddPositionDialog })),
  { ssr: false, loading: () => null },
);

const DeletePortfolioDialog = dynamic(
  () => import("@/features/portfolio/components/DeletePortfolioDialog").then((m) => ({ default: m.DeletePortfolioDialog })),
  { ssr: false, loading: () => null },
);

// ── PortfolioPage ───────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const { accessToken } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();

  // T-B-2-07: KPI strip is hard-locked to "1D". The const stays narrow so
  // queryKey shapes downstream compile unchanged.
  const selectedPeriod = "1D" as const;

  // ── Dialog open/close state (page-scoped so headers can trigger them) ──
  const [connectModalOpen, setConnectModalOpen] = useState(false);
  const [createPortfolioOpen, setCreatePortfolioOpen] = useState(false);
  const [addPositionOpen, setAddPositionOpen] = useState(false);
  const [deletePortfolioOpen, setDeletePortfolioOpen] = useState(false);

  // ── W2: chart collapse state + filter state ────────────────────────────
  const [chartCollapsed, setChartCollapsed] = useState(false);
  const [filterText, setFilterText] = useState("");
  const [filterVisible, setFilterVisible] = useState(false);

  // ── W2: performance period URL-backed state ───────────────────────────
  // WHY URL state for period: deep-links encode which period the user is on.
  // WHY clearOnDefault: keeps the URL clean when on the default period.
  const [period, setPeriod] = useQueryState(
    "period",
    parseAsStringLiteral(["1W", "1M", "3M", "6M", "1Y", "All"] as const satisfies readonly PerfPeriod[])
      .withDefault("3M")
      .withOptions({ clearOnDefault: true }),
  );

  // ── Data orchestrator ──────────────────────────────────────────────────
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
    holdingsResp,
    enrichedHoldings,
    holdingsQuotes,
    holdingOverviews,
    realizedPnLQuery,
    kpi,
    bySector,
    scopeHint,
    handlePortfolioCreated,
    handlePositionAdded,
    deletePortfolioMutation,
  } = data;

  // PLAN-0070 C-1: fire the bundle endpoint to warm the cache in one round-trip.
  usePortfolioBundle({ portfolioId: activePortfolioId, accessToken });

  // ── W2: batch-fetch 14d daily OHLCV series for SPARK column ───────────
  const { holdingsSeries } = useHoldingsSeries(holdingsResp?.holdings ?? []);

  // ── W2: derive contributors / detractors from enriched holdings ────────
  const { contributors, detractors } = useTopMovers(enrichedHoldings);

  // ── W2: page-scope hotkeys ─────────────────────────────────────────────
  // WHY document-level listener (not a library): zero dependency, ~10 lines,
  // matches the terminal aesthetic of keyboard-first navigation.
  // WHY guard for input/textarea: a PM filtering the grid should not trigger
  // navigation hotkeys when typing in the filter box.
  const handleSetPeriod = useCallback(
    (p: PerfPeriod) => { void setPeriod(p); },
    [setPeriod],
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      // Navigation hotkeys
      if (e.key === "b" || e.key === "B") { router.push("/dashboard"); return; }
      if (e.key === "t" || e.key === "T") { router.push("/portfolio/transactions"); return; }
      if (e.key === "a" || e.key === "A") { router.push("/portfolio/analytics"); return; }
      if (e.key === "w" || e.key === "W") { router.push("/watchlists"); return; }
      // Data hotkeys
      if (e.key === "r" || e.key === "R") {
        void queryClient.invalidateQueries({ queryKey: qk.portfolios.all });
        return;
      }
      // Chart collapse toggle
      if (e.key === "c" || e.key === "C") { setChartCollapsed((p) => !p); return; }
      // Period chips
      if (e.key === "1") { handleSetPeriod("1W"); return; }
      if (e.key === "2") { handleSetPeriod("1M"); return; }
      if (e.key === "3") { handleSetPeriod("3M"); return; }
      if (e.key === "4") { handleSetPeriod("6M"); return; }
      if (e.key === "5") { handleSetPeriod("1Y"); return; }
      if (e.key === "0") { handleSetPeriod("All"); return; }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [router, queryClient, handleSetPeriod]);

  // ── Loading state (initial mount, no portfolios yet) ──────────────────
  if (portfoliosLoading || (holdingsLoading && !holdingsResp)) {
    return (
      // WHY p-3 space-y-3: terminal density — 12px padding, 12px gaps.
      <div className="flex flex-col h-full min-h-0 space-y-3 p-3">
        <div className="flex h-[36px] items-center justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-36" />
        </div>
        {/* WHY 8 tiles: matches the updated W2 KPI strip (8 tiles not 7). */}
        <div className="flex divide-x divide-border border-b border-border">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex-1 px-3 py-1.5">
              <Skeleton className="h-3 w-16 mb-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
        <Skeleton className="h-[36px] w-80" />
        {/* F-P-020: row skeletons use h-[20px] to match the W2 rowHeight=20 token. */}
        <div className="space-y-px">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[20px] w-full" />
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

  // ── V18 empty state: no holdings AND not loading ───────────────────────
  // WHY show BrokerageEmptyState only after loading completes: avoids a flash
  // of the CTA during the first render before holdings resolve.
  const showEmptyState = !holdingsLoading && enrichedHoldings.length === 0;

  // ── FIFO realized P&L dispatch ─────────────────────────────────────────
  // PLAN-0051 T-A-1-05: prefer the FIFO endpoint; fall back to client-side
  // approximation. WHY here: matches the original page logic.
  const fifo = realizedPnLQuery.data;
  const useFifo = !realizedPnLQuery.isError && fifo != null;
  const realizedPnl = useFifo ? fifo!.total_realized : kpi.realizedPnl;

  return (
    // WHY h-full flex-col: fills the shell's main content area.
    // WHY bg-background: page is the lowest elevation — panels inside use bg-card.
    // WHY overflow-y-auto: the stacked component list may exceed viewport height.
    <div className="flex flex-col h-full min-h-0 overflow-y-auto bg-background pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">

      {/* 1. Page header */}
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

      {/* 2. Brokerage status banner (C-34: sync events move off RecentActivityStrip) */}
      <BrokerageStatusBanner portfolioId={activePortfolioId} />

      {/* ── Empty state replaces all data surfaces when holdings=0 ─────── */}
      {showEmptyState ? (
        <BrokerageEmptyState />
      ) : (
        <>
          {/* 3. KPI Strip — 8 tiles */}
          {holdingsResp && (
            <PortfolioKPIStrip
              portfolioId={activePortfolioId}
              totalValue={kpi.totalValue}
              dayPnl={kpi.dayPnl}
              unrealisedPnl={kpi.unrealisedPnl}
              unrealisedPnlPct={kpi.unrealisedPnlPct}
              topGainer={kpi.topGainer}
              topLoser={kpi.topLoser}
              realizedPnl={realizedPnl}
              realizedPnlApprox={!useFifo}
              realizedPnlLongTerm={useFifo ? fifo!.realized_long_term : null}
              realizedPnlShortTerm={useFifo ? fifo!.realized_short_term : null}
            />
          )}

          {/* 4. Exposure currency strip */}
          <ExposureCurrencyStrip portfolioId={activePortfolioId} />

          {/* 5. Concentration + sector tease strip */}
          <ConcentrationSectorTeaseStrip
            portfolioId={activePortfolioId}
            bySector={bySector}
          />

          {/* 6. Performance chart (collapsible, C hotkey, period chips) */}
          <PerformanceChartPanel
            period={period}
            onPeriodChange={(p) => { void setPeriod(p); }}
            collapsed={chartCollapsed}
            onToggleCollapse={() => setChartCollapsed((c) => !c)}
          />

          {/* 7. Sector allocation bar */}
          <SectorAllocationBar bySector={bySector} />

          {/* 8. Holdings table chrome (filter input + position count) */}
          <HoldingsTableChrome
            positionCount={enrichedHoldings.length}
            onFilterFocus={() => setFilterVisible(true)}
            filterText={filterText}
            onFilterChange={setFilterText}
            filterVisible={filterVisible}
            onFilterVisibleChange={setFilterVisible}
          />

          {/* 9. Holdings table — 14-col AG Grid, rowHeight=20, sparkline context */}
          {/* WHY context.holdingsSeries: SparklineCellRenderer reads sparkline data
              from AG Grid context so it doesn't need to re-fetch per row. The context
              object is stable (new reference only when holdingsSeries changes). */}
          <SemanticHoldingsTable
            holdings={enrichedHoldings}
            quotes={holdingsQuotes}
            sectors={Object.fromEntries(
              Object.entries(holdingOverviews ?? {}).map(([id, ov]) => [
                id,
                ov?.sector ?? null,
              ]),
            )}
            totalValue={kpi.totalValue}
          />

          {/* 10. Contributors + detractors strip */}
          <ContributorsStrip
            contributors={contributors}
            detractors={detractors}
            isLoading={holdingsLoading}
          />

          {/* 11. Recent activity strip (transactions only, C-34) */}
          <RecentActivityStrip portfolioId={activePortfolioId} />
        </>
      )}

      {/* ── Connect Brokerage Modal ─────────────────────────────────────── */}
      {/* WHY outside conditional: modal must persist through empty-state changes
          and be accessible from BrokerageEmptyState's CTA. */}
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
