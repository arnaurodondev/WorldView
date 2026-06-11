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
// R1 sprint: Link is used by the Analytics tab "FULL VIEW" affordance that
// wires the standalone /portfolio/analytics route into the portfolio nav.
import Link from "next/link";
// R1 sprint: Plus icon for the prominent empty-portfolio CTA.
// R3 polish: FolderPlus is the category icon for the no-portfolio EmptyState.
// R4 hardening: AlertTriangle categorises the page-level load-error state;
// RotateCw decorates its Retry action (the deferred R3 retry item).
import { Plus, FolderPlus, AlertTriangle, RotateCw } from "lucide-react";

import { useAuth } from "@/hooks/useAuth";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";

// ── Portfolio chrome ────────────────────────────────────────────────────────
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
// R2 sprint: interactive sector-allocation donut beside the KPI strip.
// Clicking a slice/legend row filters the holdings table to that sector.
import { SectorAllocationDonut } from "@/components/portfolio/SectorAllocationDonut";
import { WatchlistsTabPanel } from "@/components/portfolio/WatchlistsTabPanel";
// F-P-003 (PLAN-0051 W6): the equity-curve period state is hoisted to this
// page so future panels can react to the same period. The type comes from
// EquityCurveChart so the canonical period set lives in one place.
import type { PeriodLabel } from "@/components/portfolio/EquityCurveChart";

// ── Brokerage modal ─────────────────────────────────────────────────────────
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";

// ── Terminal primitives ─────────────────────────────────────────────────────
// R3 polish (DS §15.12): shared EmptyState primitive — the no-portfolio
// branch renders through it (copy: portfolio.no-portfolio in the registry).
// R4 hardening: the page-level error branch ALSO renders through it now
// (copy: portfolio.load-error) — the legacy InlineEmptyState import is gone
// with its last call site (it offered no retry path; users had to reload).
import { EmptyState } from "@/components/primitives/EmptyState";

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

  // ── R2 sprint: sector filter (donut → holdings table) ──────────────────
  // WHY URL state (nuqs, not useState): a filtered holdings view is a
  // shareable artifact ("look at my Tech exposure") and back/forward should
  // step through filter changes — exactly the rationale for ?tab= above.
  // null = no filter. The default string parser keeps any sector name
  // round-trippable without an enum (sector labels come from live data).
  const [sectorFilter, setSectorFilter] = useQueryState("sector");

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
    // R4 hardening: in-place retry for the page-level error state below.
    refetchPortfolios,
    holdingsLoading,
    txLoading,
    watchlistsLoading,
    holdingsResp,
    enrichedHoldings,
    holdingsQuotes,
    holdingOverviews,
    transactionsResp,
    setTxOffset,
    exposure,
    assetClassByInstrument,
    sectorSegments,
    sectorIdMap,
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
            strip's shape exactly — same `divide-x` separator, same
            px-3/py-1.5 padding. Any mismatch causes layout shift when
            the data resolves.
            R3 polish: tile count corrected 7 → 8 (PRD-0089 W2 §4.2 added
            CASH + BUYING PWR and removed # Positions — the skeleton had
            drifted one tile short of the real strip, so the 8th tile popped
            in on data arrival). The donut placeholder beside it mirrors the
            R2 header band (hidden below xl, exactly like the real donut). */}
        <div className="flex items-stretch">
          <div
            data-testid="kpi-strip-skeleton"
            className="flex min-w-0 flex-1 divide-x divide-border border-b border-border"
          >
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="flex-1 px-3 py-1.5">
                <Skeleton className="h-3 w-16 mb-1" />
                <Skeleton className="h-4 w-20" />
              </div>
            ))}
          </div>
          {/* Donut skeleton: circle + 3 legend lines — same shape the
              populated SectorAllocationDonut renders while its own query
              loads, so the whole header band paints consistently. */}
          <div
            data-testid="donut-skeleton"
            className="hidden xl:flex w-[400px] shrink-0 items-center gap-2 border-l border-b border-border px-2 py-1"
          >
            <Skeleton className="size-[56px] rounded-full shrink-0" />
            <div className="flex-1 space-y-1">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          </div>
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
  // R4 hardening (the deferred R3 item): the portfolio-list failure is now a
  // NAMED error state with an in-place Retry instead of the dead-end
  // InlineEmptyState that told the user to reload the whole app. The title
  // string stays "Failed to load portfolio data" — pinned by the e2e suite
  // (qa-exhaustive "Portfolio shows error state with retry option").
  // WHY refetchPortfolios (not router.refresh / location.reload): only the
  // portfolio-list query failed; refetching just that query preserves every
  // other warm cache entry and recovers in one round-trip.
  if (portfoliosError) {
    return (
      <div className="p-3" data-testid="portfolio-error-state">
        <EmptyState
          condition="error"
          copyKey="portfolio.load-error"
          icon={AlertTriangle}
          action={
            // Terminal-style bordered action, same affordance family as the
            // empty-portfolio "Create portfolio" CTA below — one visual
            // language for "the page needs exactly one action from you".
            <button
              type="button"
              data-testid="portfolio-error-retry"
              aria-label="Retry loading portfolio data"
              onClick={refetchPortfolios}
              className="mt-1 flex h-7 items-center gap-1.5 rounded-[2px] border border-primary/60 px-3 font-mono text-[11px] uppercase tracking-[0.06em] text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <RotateCw className="h-3 w-3" strokeWidth={1.5} />
              Retry
            </button>
          }
        />
      </div>
    );
  }

  // ── Empty-portfolio state (R1 sprint) ──────────────────────────────────
  // WHY a dedicated branch: with zero portfolios the previous code fell
  // through to the full tab layout — holdings showed "Connect a brokerage…"
  // which presumes a portfolio already exists, and the page read as broken.
  // A user with no portfolios needs exactly one action: create one. We show
  // a named state with a prominent CTA and mount only the CreatePortfolioDialog
  // (the other dialogs require an active portfolio).
  // WHY check `sortedPortfolios` resolved (not just length): undefined means
  // the query hasn't settled — that case is handled by the loading skeleton
  // above, never by this branch.
  if (sortedPortfolios && sortedPortfolios.length === 0) {
    return (
      <div
        className="flex h-full min-h-0 flex-col items-center justify-center gap-3 bg-background p-3"
        data-testid="empty-portfolio-state"
      >
        {/* Named heading — terminal-style ALL CAPS eyebrow above the shared
            EmptyState. R3 polish (DS §15.12): the title/body now resolve from
            lib/copy/empty-states.ts (portfolio.no-portfolio — title is the
            exact "Select or create a portfolio" string the tests pin) and the
            prominent CTA rides the primitive's `action` slot, so this state
            renders structurally identically to every other empty surface. */}
        <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Portfolio
        </span>
        <div className="max-w-md">
          <EmptyState
            condition="empty-cold-start"
            copyKey="portfolio.no-portfolio"
            icon={FolderPlus}
            action={
              // Prominent CTA — primary-bordered, larger than the header
              // buttons because it is the ONLY meaningful action here.
              // R3: focus-visible ring for keyboard parity with hover.
              <button
                aria-label="Create your first portfolio"
                onClick={() => setCreatePortfolioOpen(true)}
                className="mt-1 flex h-8 items-center gap-1.5 rounded-[2px] border border-primary bg-primary/10 px-4 font-mono text-[11px] uppercase tracking-[0.06em] text-primary transition-colors hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
                Create portfolio
              </button>
            }
          />
        </div>

        {/* The create dialog must be mounted inside this early-return branch —
            the main render path below is never reached while the portfolio
            list is empty. onSuccess routes through the same hook callback so
            the new portfolio is auto-selected once the list refetches. */}
        <CreatePortfolioDialog
          open={createPortfolioOpen}
          onOpenChange={setCreatePortfolioOpen}
          onSuccess={(p) => {
            setCreatePortfolioOpen(false);
            handlePortfolioCreated(p);
          }}
          accessToken={accessToken}
        />
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

      {/* ── R2 sprint: header band — performance + KPI strip beside the
          allocation donut. items-stretch equalizes heights so the donut's
          border-b lines up with the KPI strip's own bottom border. */}
      <div className="flex items-stretch">
        <div className="flex min-w-0 flex-1 flex-col">
          <PerformanceStrip
            period={selectedPeriod}
            performanceData={performanceData}
            performanceLoading={performanceLoading}
          />

          {/* ── KPI Strip ─────────────────────────────────────────────────── */}
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
                  // R1 sprint (BP-517-class fix): cash/buyingPower were never
                  // passed here, so the CASH and BUYING PWR tiles permanently
                  // rendered "—". The exposure snapshot now flows from
                  // usePortfolioData (GET /v1/portfolios/{id}/exposure).
                  // 2026-06-10 sprint gap #5: buying_power is now an explicit
                  // server field (v1: equals cash). Prefer it; fall back to
                  // cash for older S9 builds that omit it.
                  cash={exposure?.cash ?? null}
                  buyingPower={exposure?.buying_power ?? exposure?.cash ?? null}
                />
              );
            })()}
        </div>

        {/* R2 sprint: allocation donut — server-side sector breakdown
            (GET /v1/portfolios/{id}/sector-breakdown). Clicking a slice or
            legend row filters the holdings table; clicking again (or the
            chip in the Holdings tab) clears.
            WHY gated on holdingsResp: same rationale as the KPI strip — no
            allocation exists before holdings load, and gating keeps the
            header band collapsed to the PerformanceStrip height while
            loading (no layout jump).
            WHY hidden xl:flex: below 1280px the 8 KPI tiles already consume
            the full width; squeezing a 400px donut in would crush both. The
            sector filter remains clearable on small screens via the chip in
            the Holdings tab (which is always visible when a filter is set). */}
        {holdingsResp && (
          <SectorAllocationDonut
            portfolioId={activePortfolioId}
            selectedSector={sectorFilter}
            onSelectSector={(s) => void setSectorFilter(s)}
            className="hidden xl:flex w-[400px] shrink-0 border-l border-b border-border"
          />
        )}
      </div>

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
            // R1 sprint: asset-class lookup (derived from transactions in the
            // hook) feeds the holdings table ASSET column, which previously
            // rendered "—" for every row because the context map was empty.
            assetClasses={assetClassByInstrument}
            kpi={kpi}
            bySector={bySector}
            byType={byType}
            equityPeriod={equityPeriod}
            setEquityPeriod={setEquityPeriod}
            // R2 sprint: donut-driven sector filter. HoldingsTab filters the
            // table rows and renders the dismissible chip; clearing routes
            // back through the same URL state the donut writes.
            sectorFilter={sectorFilter}
            onClearSectorFilter={() => void setSectorFilter(null)}
            // 2026-06-10 sprint gap #2: raw sector segments (with
            // instrument_ids) for the SectorExposurePanel rows + the
            // exact-ID sector-filter join.
            sectorSegments={sectorSegments}
            sectorIdMap={sectorIdMap}
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
            // R1 sprint: empty-state CTA. Root portfolios are read-only on S1
            // (CANNOT_RECORD_TRANSACTION_ON_ROOT), so we only offer the
            // "add first transaction" affordance on concrete portfolios.
            onAddPosition={
              activeIsRoot ? undefined : () => setAddPositionOpen(true)
            }
            // R1 sprint: server-side pager. Offset changes flow back into the
            // usePortfolioData transactions query (key includes the offset).
            onTxOffsetChange={setTxOffset}
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
            <>
              {/* R1 sprint: wire the standalone /portfolio/analytics route
                  into the portfolio nav. The route existed but was reachable
                  only via the "A" hotkey — this visible affordance makes the
                  full-height analytics view discoverable with a mouse. */}
              <div className="flex h-[24px] shrink-0 items-center justify-end border-b border-border/60 bg-card px-3">
                <Link
                  href="/portfolio/analytics"
                  className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground transition-colors hover:text-primary"
                >
                  Full view ↗
                </Link>
              </div>
              <AnalyticsTab portfolioId={activePortfolioId} />
            </>
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
