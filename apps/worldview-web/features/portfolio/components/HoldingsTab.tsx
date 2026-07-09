/**
 * features/portfolio/components/HoldingsTab.tsx — Holdings tab body (PRD-0108 W3 redesign).
 *
 * REDESIGNED in PLAN-0108 Wave 3 (T-3-05): "Anchored table" layout.
 *
 * WHY THIS LAYOUT: PRD-0108 §3 mandates a density-first approach where every px
 * above the table fold delivers actionable signal. The previous layout mixed legacy
 * strips (CashRow, ConcentrationStrip, ExposureStrip, DayPnLDistribution) with new
 * W2 strips, creating visual duplication and consuming ~300px of above-fold space.
 * This layout rationalises to exactly 7 strip rows + table + bottom placeholder.
 *
 * LAYOUT (top → bottom):
 *
 *   ─ PortfolioPageHeader  h-9   (rendered at page.tsx level — NOT here)
 *   ─ PortfolioKPIStrip    h-7   (rendered at page.tsx level — NOT here)
 *   1. Overview panel band        h-[128px] 3-col: MarketExposurePanel |
 *      (2026-06-10 sprint W2)               SectorExposurePanel |
 *                                           PerformancePeriodsPanel
 *      — supersedes ExposureCurrencyStrip (file preserved, call site moved)
 *   2. ConcentrationSectorTeaseStrip h-[22px] HHI badge + top-3 sectors
 *   3. PerformanceChartPanel      h-[120px] collapsible equity-curve + SPY overlay
 *   4. SectorAllocationBar        h-[22px]  stacked bar + top-3 sector labels
 *   5. HoldingsTableChrome        h-[22px]  position count + Ctrl+F filter shortcut
 *   6. SemanticHoldingsTable      flex-1    AG Grid, 14-column + SPARK
 *   7. BottomStripCluster         h-[124px] contributors | detractors | recent activity
 *
 * REMOVED vs the PLAN-0088 Wave E layout (component files preserved):
 *   - CashRow              → data already in KPIStrip
 *   - ConcentrationStrip   → superseded by ConcentrationSectorTeaseStrip
 *   - ExposureStrip        → superseded by ExposureCurrencyStrip
 *   - DayPnLDistribution   → low signal for single-day view; moved to Analytics
 *   - HoldingLotsPanel     → FIFO drilldown moved to Analytics tab
 *   - PositionBarHeat      → removed from Holdings; Analytics tab retains it
 *   - RealizedPnLSparkline → moved to Analytics tab
 *   - DividendYTDStrip     → moved to Analytics tab
 *   - SectorAllocationPanel → full panel superseded by SectorAllocationBar strip
 *   - ContributorsStrip    → W4 bottom cluster (placeholder until W4-T4-01)
 *   - RecentActivityStrip  → W4 bottom cluster
 *   - RecentActivityFeed   → W4 bottom cluster
 *   - PortfolioAnalyticsSection → lives in Analytics tab (not Holdings)
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — TabsContent[value="holdings"]
 * DATA SOURCE: enrichedHoldings + holdingsQuotes + holdingOverviews from usePortfolioData
 * DESIGN REFERENCE: PRD-0108 §3, T-3-05
 */

"use client";
// WHY "use client": uses multiple React hooks (useState, useCallback, useMemo)
// and child components are client components requiring React context.

import { useState, useCallback, useMemo, useRef } from "react";
// R2 sprint: X icon for the dismissible sector-filter chip.
import { X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
// R2 sprint: pure, unit-tested sector matching for the donut-driven filter.
import { filterHoldingsBySector } from "@/features/portfolio/lib/sector-filter";
// ── 2026-06-10 sprint Wave 2: specialized overview panels ─────────────────────
// MarketExposurePanel supersedes the single-line ExposureCurrencyStrip (the
// component file is preserved; only this call site moved to the richer panel).
import { MarketExposurePanel } from "@/components/portfolio/MarketExposurePanel";
import { SectorExposurePanel } from "@/components/portfolio/SectorExposurePanel";
import { PerformancePeriodsPanel } from "@/components/portfolio/PerformancePeriodsPanel";
// ── PRD-0108 W3 layout strips ─────────────────────────────────────────────────
import { ConcentrationSectorTeaseStrip } from "@/components/portfolio/ConcentrationSectorTeaseStrip";
import { PerformanceChartPanel } from "@/components/portfolio/PerformanceChartPanel";
import type { PerfPeriod } from "@/components/portfolio/PerformanceChartPanel";
import { SectorAllocationBar } from "@/components/portfolio/SectorAllocationBar";
import { HoldingsTableChrome } from "@/components/portfolio/HoldingsTableChrome";
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
// ── PRD-0108 W3 SPARK column data hook ────────────────────────────────────────
import { useHoldingsSeries } from "@/features/portfolio/hooks/useHoldingsSeries";
// ── PRD-0108 W4 bottom strip cluster ──────────────────────────────────────────
import { BottomStripCluster } from "@/components/portfolio/BottomStripCluster";
// ── PRD-0114 W4: empty states + brokerage sync badges ─────────────────────────
// WHY ManualPortfolioEmptyState: MANUAL portfolios with 0 holdings need a
// context-aware call-to-action (not the brokerage CTA that would mislead them).
import { ManualPortfolioEmptyState } from "@/components/portfolio/ManualPortfolioEmptyState";
// WHY BrokerageEmptyState variant="awaiting-sync": BROKERAGE portfolios with 0
// holdings have a connection but haven't received their first sync yet — copy
// should reassure, not prompt them to connect (they already connected).
import { BrokerageEmptyState } from "@/components/portfolio/BrokerageEmptyState";
// WHY LastSyncedBadge: surfaces brokerage_last_synced_at from the holdings
// response so BROKERAGE users can see when their data is fresh without leaving
// the tab. Previously this field was returned by S9 but never rendered (G-4).
import { LastSyncedBadge } from "@/components/portfolio/LastSyncedBadge";
// WHY SyncErrorBadge: unresolved sync errors are only visible in the brokerage
// settings modal today. The badge brings the count into the holdings toolbar
// and provides a one-click scroll to the BrokerageStatusBanner (G-7).
import { SyncErrorBadge } from "@/components/portfolio/SyncErrorBadge";
// WHY BrokerageStatusBanner: already used in the brokerage settings page —
// imported here to show the per-portfolio error detail directly inside the
// Holdings tab, anchored below the sync-status strip.
import { BrokerageStatusBanner } from "@/components/portfolio/BrokerageStatusBanner";
import { useTopMovers } from "@/features/portfolio/hooks/useTopMovers";
// ── Wave G: Holding detail slide-over (preserved from PLAN-0088) ──────────────
// WHY keep slide-over: the ticker-pill row + slide-over is orthogonal to the
// strip layout change. It enriches the SemanticHoldingsTable experience and
// has no layout impact on the above-fold strips.
import { HoldingDetailSlideOver } from "@/components/portfolio/detail/HoldingDetailSlideOver";
import type { PeriodLabel } from "@/components/portfolio/EquityCurveChart";
import type {
  Holding,
  HoldingsResponse,
  BatchQuoteResponse,
  SectorBreakdownSegment,
} from "@/types/api";
import type {
  PortfolioKPI,
  PortfolioAllocations,
  HoldingOverviewMap,
} from "@/features/portfolio/lib/kpi";

interface HoldingsTabProps {
  /**
   * PLAN-0122 W-A: portfolio detail level. Optional with default "advanced" so
   * every existing caller/test renders unchanged (byte-identical to today). This
   * wave threads it only — no branching yet. W-B wraps each power-strip in
   * `mode === "advanced" && (…)` so Simple shows a clean holdings-first view.
   */
  mode?: "simple" | "advanced";
  activePortfolioId: string | null;
  holdingsLoading: boolean;
  holdingsResp: HoldingsResponse | undefined;
  enrichedHoldings: Holding[];
  holdingsQuotes: BatchQuoteResponse["quotes"];
  holdingOverviews: HoldingOverviewMap | undefined;
  /**
   * R1 sprint: asset-class lookup keyed by instrument_id (derived from the
   * transactions response in usePortfolioData). Threaded through to
   * SemanticHoldingsTable to feed the ASSET column badge. Optional so older
   * call sites / tests render unchanged (column degrades to "—").
   */
  assetClasses?: Record<string, string | null>;
  kpi: PortfolioKPI;
  bySector: PortfolioAllocations["bySector"];
  byType: PortfolioAllocations["byType"];
  /** F-P-003: equity-curve period state hoisted to the page. */
  equityPeriod: PeriodLabel;
  setEquityPeriod: (period: PeriodLabel) => void;
  /**
   * R2 sprint: active sector filter from the allocation donut (page-level
   * nuqs ?sector= state). When set, the holdings table shows only rows in
   * that sector and a dismissible chip appears above the table chrome.
   * Optional so older call sites/tests render unchanged (no filter).
   */
  sectorFilter?: string | null;
  /** R2 sprint: clears the sector filter (chip × / keyboard). */
  onClearSectorFilter?: () => void;
  /**
   * 2026-06-10 sprint gap #2: raw sector-breakdown segments (with
   * instrument_ids) from usePortfolioData. Feeds the SectorExposurePanel
   * rows and the exact-ID sector filter. Optional — older call sites/tests
   * degrade to alias filtering + the panel's loading state.
   */
  sectorSegments?: SectorBreakdownSegment[];
  /** sector label → instrument_ids (exact-ID filter join, sprint gap #2). */
  sectorIdMap?: Record<string, string[]>;
  /**
   * PRD-0114 W4 (FR-5, FR-7): portfolio kind from the active portfolio object.
   * Used to select the correct empty state (manual vs. brokerage) and to
   * conditionally render the brokerage sync-status strip.
   * WHY lowercase: PortfolioKind StrEnum serialises as "manual"/"brokerage"/"root".
   * Optional — older call sites (tests, page.tsx pre-W4) render without kind-aware UI.
   */
  portfolioKind?: "manual" | "brokerage" | "root" | null;
  /**
   * PRD-0114 W4 (FR-8): callback from the page to open the AddPositionDialog.
   * The ManualPortfolioEmptyState CTA calls this so the dialog open state stays
   * in page.tsx (single source of truth, avoids prop drilling).
   * Optional — undefined when portfolioKind === "root" (read-only root portfolio).
   */
  onOpenAddPosition?: () => void;
  /**
   * PRD-0114 W5 (FE-003): auth token forwarded to SemanticHoldingsTable →
   * ClosePositionDialog for the authenticated POST /api/v1/transactions call.
   * Optional — undefined when the feature is not yet wired at the call site
   * (older tests degrade gracefully; the context menu item is gated on
   * portfolioId being defined anyway).
   */
  accessToken?: string | null;
  /**
   * PRD-0114 W5 (FE-003): called by ClosePositionDialog.onSuccess so the
   * holdings table refetches after a position is closed. Delegates to
   * handlePositionAdded() in usePortfolioData (same invalidation as Add).
   * Optional — undefined falls back to a no-op in SemanticHoldingsTable.
   */
  onHoldingsRefetch?: () => void;
}

export function HoldingsTab({
  // PLAN-0122 W-A: default "advanced" preserves today's full layout for every
  // existing caller. `mode` is threaded to SemanticHoldingsTable (reserved for
  // W-D/W-E); no strip is gated in this wave.
  mode = "advanced",
  activePortfolioId,
  holdingsLoading,
  holdingsResp,
  enrichedHoldings,
  holdingsQuotes,
  holdingOverviews,
  assetClasses,
  kpi,
  bySector,
  // byType was consumed by the legacy allocation panel (now in Analytics).
  // Kept in the interface so page.tsx props don't change; `_` prefix
  // suppresses the unused-variable lint error (same pattern as
  // _setEquityPeriod below).
  byType: _byType,
  equityPeriod,
  // setEquityPeriod was used by PortfolioAnalyticsSection (now in Analytics tab).
  // Retained in the interface so page.tsx props don't change; prefixed _  to
  // suppress the unused-variable lint warning.
  setEquityPeriod: _setEquityPeriod,
  sectorFilter = null,
  onClearSectorFilter,
  sectorSegments,
  sectorIdMap,
  portfolioKind = null,
  onOpenAddPosition,
  accessToken,
  onHoldingsRefetch,
}: HoldingsTabProps) {
  // ── PLAN-0122 W-B: mode gate ────────────────────────────────────────────────
  // WHY one boolean read once: every power-user strip below wraps in
  // `isAdvanced && (…)`. Simple renders ONLY the holdings-first essentials
  // (table chrome + Core-column table + brokerage sync status); it hides the
  // analytics strips (overview band, concentration, perf chart, sector bar,
  // bottom cluster, detail-pill row, sector-filter chip). This is a RENDERING
  // GATE — the Advanced arm is byte-identical to today (W-A anti-fork snapshot).
  // WHY brokerage strips STAY in Simple: a casual user who linked a brokerage
  // still needs to see "last synced / N errors" — that is status, not analytics.
  const isAdvanced = mode === "advanced";

  // ── PerformanceChartPanel state ────────────────────────────────────────────
  // WHY local state (not URL): collapse toggle is ephemeral UI preference.
  // Deep-links to /portfolio don't encode chart open/closed state.
  // Default: expanded (spec §4.1 "default on").
  const [perfChartCollapsed, setPerfChartCollapsed] = useState(false);

  // WHY separate from equityPeriod: PerformanceChartPanel and the full
  // EquityCurveChart in AnalyticsTab may be on different zoom levels simultaneously.
  const [perfPeriod, setPerfPeriod] = useState<PerfPeriod>("3M");

  // ── HoldingsTableChrome filter state ──────────────────────────────────────
  // WHY local state: filter text is ephemeral — a deep-link to /portfolio should
  // always show the unfiltered table. URL-backed filter would confuse users who
  // share a link and expect to see the full holdings list.
  const [filterText, setFilterText] = useState("");
  const [filterVisible, setFilterVisible] = useState(false);
  // onFilterFocus is passed to HoldingsTableChrome so pressing Ctrl+F from
  // anywhere in the Holdings tab focuses the filter input inside the chrome row.
  // WHY useCallback: stable reference prevents unnecessary child re-renders.
  const handleFilterFocus = useCallback(() => {
    setFilterVisible(true);
  }, []);

  // ── β-ADJ exposure computation ─────────────────────────────────────────────
  // WHY computed here (not fetched): S1 /exposure does not return a beta-adjusted
  // figure today. The parent has all the data needed: position values and (when
  // available) instrument betas via holdingOverviews.
  //
  // FORMULA: betaAdjExposure = Σ(position_market_value × beta_i) / total_value
  //   where beta_i defaults to 1.0 if the holding overview has no beta value.
  //
  // WHY default beta=1.0: a missing beta should not be treated as "no exposure" (0×)
  // or "ultra-high risk" (arbitrary×). 1.0 is the market-neutral default — it means
  // "assume this position tracks the market exactly, no amplification/dampening".
  // The cell shows "—" when total_value is zero (no holdings), rather than Infinity.
  const betaAdjExposure = useMemo((): number | null => {
    if (kpi.totalValue <= 0) return null;
    // No holdings → pass null to show "—" in the β-ADJ cell.
    if (enrichedHoldings.length === 0) return null;

    let betaWeightedSum = 0;
    for (const holding of enrichedHoldings) {
      // market value for this position = quantity × current_price
      // WHY current_price (not average_cost): exposure is a forward-looking
      // risk measure — we care about what the position is worth NOW, not what
      // we paid. Using average_cost would understate exposure on unrealised gains.
      const quote = holdingsQuotes[holding.instrument_id];
      const currentPrice = quote?.price ?? holding.current_price ?? holding.average_cost;
      const positionValue = holding.quantity * currentPrice;

      // Beta comes from holdingOverviews (instrument fundamentals, EODHD Technicals).
      // When absent, default to 1.0 (market-neutral assumption — see WHY above).
      const overview = holdingOverviews?.[holding.instrument_id];
      // Overview type has no beta field today; cast to any for forward compat.
      // WHY any cast: the OverviewMap type does not include beta yet — it will be
      // added in a follow-up wave when EODHD Technicals data is persisted. For now
      // the default of 1.0 correctly handles the absent-beta case.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const beta: number = (overview as any)?.beta ?? 1.0;
      betaWeightedSum += positionValue * beta;
    }
    return betaWeightedSum / kpi.totalValue;
  }, [enrichedHoldings, holdingsQuotes, holdingOverviews, kpi.totalValue]);

  // ── useHoldingsSeries — batch sparkline data for SPARK column ─────────────
  // Extract instrument IDs from enrichedHoldings for the batch fetch.
  // WHY memoised: avoids creating a new array reference on every render,
  // which would bust the useQuery key and cause unnecessary re-fetches.
  const instrumentIds = useMemo(
    () => enrichedHoldings.map((h) => h.instrument_id),
    [enrichedHoldings],
  );

  // Fetch 14-day close-price sparklines for all holdings in one round-trip.
  // WHY `!!holdingsResp` gate: the hook fires as soon as instrumentIds is non-empty.
  // Gating on holdingsResp ensures we only fire after the holdings API responded
  // so instrument IDs are stable (not the stale [] from the previous portfolio).
  // The hook additionally guards internally on instrumentIds.length > 0 and !!accessToken.
  // WHY holdingsSeries is now passed to SemanticHoldingsTable (W4-T401):
  // The hook was added in W3 to pre-warm the TanStack Query cache. Now that
  // SemanticHoldingsTable exposes a `series` prop (added in W4-T401), we wire
  // the data directly instead of discarding it with `void`. The series drives
  // the SPARK column's SparklineCellRenderer via the AG Grid context object.
  const { series: holdingsSeries } = useHoldingsSeries(instrumentIds, !!holdingsResp);

  // ── useTopMovers — top contributors and detractors for BottomStripCluster ──
  // WHY called here (not inside BottomStripCluster): BottomStripCluster is a
  // pure layout wrapper with no hooks. Deriving top movers in HoldingsTab keeps
  // all data-fetching/derivation in one place and avoids threading enrichedHoldings
  // + holdingsQuotes down through an additional component boundary.
  const topMovers = useTopMovers(enrichedHoldings, holdingsQuotes);

  // ── R2 sprint: sector map + donut-driven filtering ─────────────────────────
  // The instrument_id → sector map was previously built inline in the
  // SemanticHoldingsTable JSX; lifted to a useMemo because the filter below
  // needs the same map and rebuilding it twice per render is waste.
  const sectorsByInstrument = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(holdingOverviews ?? {}).map(([id, ov]) => [
          id,
          ov?.sector ?? null,
        ]),
      ) as Record<string, string | null>,
    [holdingOverviews],
  );

  // Rows actually shown in the table. filterHoldingsBySector returns the
  // SAME array reference when no filter is active, so the unfiltered path
  // keeps referential stability for AG Grid row identity.
  // 2026-06-10 sprint gap #2: sectorIdMap routes the filter through the
  // exact instrument-ID join when the breakdown segments published IDs;
  // ID-less rows keep the legacy alias fallback (see sector-filter.ts).
  const visibleHoldings = useMemo(
    () =>
      filterHoldingsBySector(
        enrichedHoldings,
        sectorsByInstrument,
        sectorFilter,
        sectorIdMap,
      ),
    [enrichedHoldings, sectorsByInstrument, sectorFilter, sectorIdMap],
  );

  // R2 sprint: when a sector filter is active the pinned TOTAL row must
  // describe the VISIBLE rows, not the whole book — otherwise the TOTAL
  // "value" column (whole portfolio) would contradict the rows above it
  // and the summed weights. Same live-price fallback chain the table's own
  // row enrichment uses (quote → stored current_price → average_cost), so
  // the filtered total equals the sum of the rendered VALUE cells exactly.
  const visibleTotalValue = useMemo(() => {
    if (!sectorFilter) return kpi.totalValue;
    return visibleHoldings.reduce((sum, h) => {
      const quote = holdingsQuotes[h.instrument_id];
      const livePrice = quote?.price ?? h.current_price ?? h.average_cost;
      return sum + livePrice * h.quantity;
    }, 0);
  }, [sectorFilter, visibleHoldings, holdingsQuotes, kpi.totalValue]);

  // ── Wave G: Holding detail slide-over state ────────────────────────────────
  // WHY null (not undefined): null is the explicit "no holding selected" signal.
  const [selectedHolding, setSelectedHolding] = useState<Holding | null>(null);
  const handleCloseSlideOver = useCallback(() => setSelectedHolding(null), []);

  // ── PRD-0114 W4: brokerage sync metadata ───────────────────────────────────
  // These fields come from the /holdings S9 response (added in W3). We coerce
  // undefined → null / 0 so downstream components receive clean types.
  const brokerageLastSyncedAt = holdingsResp?.brokerage_last_synced_at ?? null;
  const brokerageSyncErrorCount = holdingsResp?.brokerage_sync_error_count ?? 0;

  // WHY useRef on the BrokerageStatusBanner container: SyncErrorBadge's onClick
  // should scroll the user to the error detail panel without navigating away.
  // scrollIntoView on the ref node is the correct DOM API (no router dependency).
  const brokerageStatusBannerRef = useRef<HTMLDivElement>(null);
  const handleScrollToErrors = useCallback(() => {
    brokerageStatusBannerRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, []);

  // ── Loading skeleton ───────────────────────────────────────────────────────
  if (holdingsLoading && !holdingsResp) {
    // WHY h-[22px] rows: matches the SemanticHoldingsTable <tr> height token
    // exactly. When the data lands, skeletons fade out and real rows occupy
    // identical vertical space — no layout jump (F-P-020).
    return (
      <div className="space-y-px p-3">
        {/* Strip skeletons: 2 × h-[22px] for the top strips */}
        <Skeleton className="h-[22px] w-full" />
        <Skeleton className="h-[22px] w-full" />
        {/* PerformanceChartPanel skeleton */}
        <Skeleton className="h-[120px] w-full" />
        {/* SectorAllocationBar skeleton */}
        <Skeleton className="h-[22px] w-full" />
        {/* Chrome + 8 table row skeletons */}
        <Skeleton className="h-[22px] w-full" />
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-[22px] w-full" />
        ))}
      </div>
    );
  }

  return (
    // WHY flex flex-col h-full: fills the TabsContent area which is flex-1 min-h-0.
    // flex-col stacks the strips vertically; SemanticHoldingsTable (flex-1 min-h-0)
    // takes all remaining height so the table fills the viewport without overflow.
    // WHY relative: HoldingDetailSlideOver uses position:absolute anchored here.
    <div className="flex flex-col h-full bg-background relative">

      {/* ══ 1. Specialized overview band (2026-06-10 sprint Wave 2) ═══════════
          Three equal-width panels replace the single-line ExposureCurrencyStrip
          (user verdict: the overview "seems a bit empty" while exposure was an
          unreadable one-liner). Left → right mirrors the trader's question
          order: how am I deployed? → where is the money? → how am I doing?

            1. MarketExposurePanel    — invested/cash/buying-power, gross/net,
                                        leverage, β-adj (real /exposure endpoint)
            2. SectorExposurePanel    — per-sector weight bars + live day Δ$
                                        (server sector-breakdown + quotes join)
            3. PerformancePeriodsPanel— 1D/1W/1M/3M flow-adjusted TWR vs SPY
                                        (new /twr endpoint + SPY closes)

          WHY divide-x + border-b: same separator language as the bottom strip
          cluster — panels read as one band, not three floating cards.
          WHY xl:grid-cols-3 (stacked below xl): each panel needs ~420px to
          keep its value columns readable; squeezing three side-by-side under
          1280px would truncate every number.
          PLAN-0122 W-B (render matrix — "Overview panel band"): ADVANCED-only. */}
      {isAdvanced && activePortfolioId && (
        <div
          data-testid="overview-panel-band"
          className="grid shrink-0 grid-cols-1 xl:grid-cols-3 divide-y xl:divide-y-0 xl:divide-x divide-border border-b border-border"
        >
          <MarketExposurePanel
            portfolioId={activePortfolioId}
            betaAdjExposure={betaAdjExposure}
          />
          <SectorExposurePanel
            segments={sectorSegments}
            holdings={enrichedHoldings}
            quotes={holdingsQuotes}
          />
          <PerformancePeriodsPanel portfolioId={activePortfolioId} />
        </div>
      )}

      {/* ══ 2. ConcentrationSectorTeaseStrip (h-[22px]) ═══════════════════════
          WHY second: after knowing deployment ratio, concentration risk is the
          next most actionable signal. HHI badge + top-3 sectors in one row.
          bySector comes from usePortfolioData (no extra fetch needed here).
          PLAN-0122 W-B (render matrix — "Concentration strip"): ADVANCED-only. */}
      {isAdvanced && (
        <ConcentrationSectorTeaseStrip
          portfolioId={activePortfolioId}
          bySector={bySector}
        />
      )}

      {/* ══ 3. PerformanceChartPanel (h-[120px] expanded, h-[28px] collapsed) ══
          WHY third: trend context belongs above the table, not below. The PM
          needs to see if the portfolio is up/down today vs SPY before analysing
          individual positions. Collapsible to 28px so power users can maximise
          table rows.
          WHY guard on activePortfolioId: the panel fires a useQuery that requires
          a valid portfolioId. With null, the query is disabled but the DOM still
          mounts — the guard prevents a wasted paint.
          PLAN-0122 W-B (render matrix — "Performance chart"): ADVANCED-only. */}
      {isAdvanced && activePortfolioId && (
        <PerformanceChartPanel
          portfolioId={activePortfolioId}
          period={perfPeriod}
          onPeriodChange={setPerfPeriod}
          collapsed={perfChartCollapsed}
          onToggleCollapse={() => setPerfChartCollapsed((v) => !v)}
        />
      )}

      {/* ══ 4. SectorAllocationBar (h-[22px]) ════════════════════════════════
          WHY fourth: the sector bar is a "where is my money" at-a-glance summary.
          Positioned directly above the table so the PM can see the sector mix
          before scanning holdings. The single stacked bar with top-3 labels
          replaces the 240px SectorAllocationPanel on this above-fold surface.
          PLAN-0122 W-B (render matrix — "Sector allocation bar"): ADVANCED-only. */}
      {isAdvanced && <SectorAllocationBar bySector={bySector} />}

      {/* ══ 5. HoldingsTableChrome (h-[22px]) ════════════════════════════════
          WHY fifth: the chrome row anchors the table header. It shows position
          count (quick sanity check) and the Ctrl+F filter shortcut.
          WHY filter state here (not in SemanticHoldingsTable): HoldingsTableChrome
          needs to fire onFilterFocus when Ctrl+F is pressed; the table needs to
          receive the filterText to drive AG Grid quickFilter. Hosting both in
          the same parent avoids prop-drilling through SemanticHoldingsTable's
          public interface (which is data-driven, not filter-driven). */}
      {/* ══ R2 sprint: sector-filter chip strip (only when a filter is active) ══
          WHY its own 22px strip (not inside HoldingsTableChrome): the chrome
          row is a shared component used by older layouts; injecting filter
          chrome there would change its contract. A conditional strip keeps
          the unfiltered layout byte-identical. Dismiss via the × button or
          by re-clicking the donut slice (page-level toggle).
          PLAN-0122 W-B (render matrix — "Sector-filter chip row"): ADVANCED-only
          (the donut that sets the filter is itself hidden in Simple). */}
      {isAdvanced && sectorFilter && (
        <div
          data-testid="sector-filter-chip-row"
          className="flex h-[22px] shrink-0 items-center gap-2 border-b border-border bg-card px-3"
        >
          <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground shrink-0">
            Sector filter
          </span>
          <button
            type="button"
            data-testid="sector-filter-chip"
            onClick={() => onClearSectorFilter?.()}
            title={`Showing only ${sectorFilter} holdings — click to clear`}
            aria-label={`Clear ${sectorFilter} sector filter`}
            // R3 polish: focus-visible ring — the chip is the primary
            // keyboard path to clearing the filter.
            className="flex items-center gap-1 rounded-[2px] border border-primary bg-primary/10 px-1.5 py-0 font-mono text-[10px] text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            {sectorFilter}
            <X className="h-2.5 w-2.5" strokeWidth={1.5} />
          </button>
          {/* "n of m" — quantifies how much of the book is hidden so a
              filtered view can never be mistaken for the whole portfolio. */}
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {visibleHoldings.length} of {enrichedHoldings.length} positions
          </span>
        </div>
      )}

      <HoldingsTableChrome
        positionCount={visibleHoldings.length}
        onFilterFocus={handleFilterFocus}
        filterText={filterText}
        onFilterChange={setFilterText}
        filterVisible={filterVisible}
        onFilterVisibleChange={setFilterVisible}
      />

      {/* ══ PRD-0114 W4: brokerage sync-status strip ══════════════════════════
          WHY conditional on portfolioKind="brokerage": sync metadata fields only
          have meaningful values for BROKERAGE portfolios. Rendering them for
          MANUAL or ROOT portfolios would show "Never synced" which is misleading.
          WHY !holdingsLoading: avoids a flash of "Never synced" while the first
          response is in-flight (brokerage_last_synced_at is undefined until then).
          WHY h-[22px]: matches all other strip rows for density consistency. */}
      {portfolioKind === "brokerage" && !holdingsLoading && (
        <div
          data-testid="brokerage-sync-status-strip"
          className="flex h-[22px] shrink-0 items-center gap-3 border-b border-border bg-card px-3"
        >
          <LastSyncedBadge lastSyncedAt={brokerageLastSyncedAt} />
          <SyncErrorBadge
            errorCount={brokerageSyncErrorCount}
            onClickScrollToErrors={handleScrollToErrors}
          />
        </div>
      )}

      {/* ══ PRD-0114 W4: BrokerageStatusBanner (error detail) ════════════════
          WHY below the strip (not above): the banner is a detail panel that
          expands with error rows. Placing it above the table would push the
          table down and reduce the visible holding count. Below the chrome row
          keeps the table at maximum height in the error-free case (banner has
          no DOM presence when there are no errors).
          WHY activePortfolioId guard: BrokerageStatusBanner fires a useQuery
          internally and requires a valid portfolioId prop. */}
      {portfolioKind === "brokerage" && activePortfolioId && (
        <div ref={brokerageStatusBannerRef}>
          <BrokerageStatusBanner portfolioId={activePortfolioId} />
        </div>
      )}

      {/* ══ 6. SemanticHoldingsTable (flex-1 min-h-0) ════════════════════════
          WHY flex-1 min-h-0: takes all remaining vertical space so the AG Grid
          fills the viewport. min-h-0 is required for the overflow-y within
          AG Grid to create a scrollable area (otherwise the browser treats the
          flex child as having no size constraint and the table grows infinitely).
          WHY no p-2 wrapper: the outer padding was from the legacy layout. With
          the anchored-table design, the table is edge-to-edge (matching all
          other strips above). The 2px gap came from the old card border; the
          new design has no card — the table IS the surface. */}
      <div className="flex-1 min-h-0">
        {/* R2 sprint: a filter that matches nothing must NOT fall through to
            SemanticHoldingsTable's "No holdings yet — connect a brokerage"
            empty state (the user HAS holdings; the filter excluded them).
            Named state + the chip row above give the user the exit path. */}
        {/* ── Decision tree for the table slot ─────────────────────────────
            Priority order matters:
            1. Sector filter active + no matches → sector-specific message
               (user HAS holdings; the filter excluded them — different from
               the truly-empty case below).
            2. No holdings + MANUAL portfolio → ManualPortfolioEmptyState
               (explains transaction→holdings async path; offers the dialog CTA).
            3. No holdings + BROKERAGE portfolio → BrokerageEmptyState
               (reassures the user their connection is active, sync is pending).
            4. Holdings present (or kind unrecognised / root) → table.
        ─────────────────────────────────────────────────────────────────── */}
        {sectorFilter && visibleHoldings.length === 0 && enrichedHoldings.length > 0 ? (
          // Case 1: sector filter active + no matches.
          // R3 polish: this stays a LOCAL named state (not the shared
          // EmptyState primitive) because the copy interpolates the live
          // sector name — registry copy must be static (DS §15.12: "surfaces
          // needing interpolation keep a local string"). The layout mirrors
          // the primitive (centred column, title-ish line + action) and an
          // explicit "Clear filter" action button is added so the exit path
          // is one keyboard-reachable click, not just the chip row above.
          <div
            data-testid="sector-filter-no-match"
            role="status"
            className="flex h-full flex-col items-center justify-center gap-2"
          >
            <span className="font-mono text-[11px] text-muted-foreground">
              No holdings in &ldquo;{sectorFilter}&rdquo; — clear the sector
              filter above to see all positions.
            </span>
            {onClearSectorFilter && (
              <button
                type="button"
                data-testid="sector-filter-no-match-clear"
                onClick={onClearSectorFilter}
                aria-label="Clear sector filter"
                className="flex h-6 items-center gap-1 rounded-[2px] border border-primary/60 px-2 font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <X className="h-2.5 w-2.5" strokeWidth={1.5} />
                Clear filter
              </button>
            )}
          </div>
        ) : enrichedHoldings.length === 0 && portfolioKind === "manual" ? (
          // Case 2: MANUAL portfolio with no holdings yet.
          // WHY ManualPortfolioEmptyState (not a generic empty-state): MANUAL
          // portfolios are populated via transactions → consumer → holdings.
          // The empty state must explain this async path AND provide the CTA
          // to record the first transaction. A generic "No data" copy would
          // leave the user wondering what to do next.
          <ManualPortfolioEmptyState
            onOpenAddPosition={onOpenAddPosition ?? (() => {})}
          />
        ) : enrichedHoldings.length === 0 && portfolioKind === "brokerage" ? (
          // Case 3: BROKERAGE portfolio that hasn't received its first sync yet.
          // WHY "awaiting-sync" variant (not "no-connection"): the brokerage IS
          // connected (the portfolio was created via SnapTrade OAuth). The user
          // should not be prompted to connect again — they should be reassured.
          <BrokerageEmptyState variant="awaiting-sync" />
        ) : (
        // Case 4: holdings present (or portfolioKind is "root" / null).
        <SemanticHoldingsTable
          // PLAN-0122 W-A: thread the detail level (default "advanced"). Unused
          // by the table this wave; reserved for W-E (Core-only column group in
          // Simple) and W-D (row-action kebab entry points).
          mode={mode}
          // R2 sprint: visibleHoldings = enrichedHoldings when no sector
          // filter (same reference), or the sector subset when filtered.
          holdings={visibleHoldings}
          quotes={holdingsQuotes}
          // R2 sprint: map lifted to the sectorsByInstrument useMemo above
          // (shared with the filter) — content unchanged.
          sectors={sectorsByInstrument}
          // P-2 (design-QA 2026-06-16): per-row SECTOR was `—` for every holding
          // because `sectorsByInstrument` is null in this deployment, while the
          // SECTOR EXPOSURE panel derives sectors from /sector-breakdown segments.
          // Pass that same segment-derived map as an additive fallback so the
          // table SECTOR column matches the panel (SemanticHoldingsTable inverts
          // it to instrument_id→sector and uses it only when `sectors` is null).
          sectorIdMap={sectorIdMap}
          // R2 sprint: filtered total so the pinned TOTAL row + WEIGHT
          // column describe the visible rows (weights sum to 100% within
          // the filtered view). Equals kpi.totalValue when unfiltered.
          totalValue={visibleTotalValue}
          series={holdingsSeries}
          // R1 sprint: ASSET column data (was a hardcoded empty map inside
          // SemanticHoldingsTable, so every row showed "—").
          assetClasses={assetClasses}
          // PRD-0114 W5 (FE-003): Close Position context-menu wiring.
          // portfolioId gates the "Close Position" menu item — undefined for
          // the root (read-only) portfolio so the item is correctly absent.
          // portfolioKind is forwarded so the table can additionally gate on
          // kind !== "root" (belt-and-suspenders guard matching the table's
          // own internal check).
          // accessToken is forwarded to ClosePositionDialog for the auth header.
          // onHoldingsRefetch triggers query invalidation after a successful close
          // so the holdings table updates without a full page reload.
          portfolioId={activePortfolioId ?? undefined}
          portfolioKind={portfolioKind ?? undefined}
          accessToken={accessToken}
          onHoldingsRefetch={onHoldingsRefetch}
        />
        )}
      </div>

      {/* ══ 7. BottomStripCluster (h-24) — wired in W4-T405 ════════════════════
          WHY guard on activePortfolioId: BottomStripCluster requires a non-null
          string portfolioId (RecentActivityStrip uses it for its transaction query).
          When no portfolio is selected the cluster is simply absent — the slot
          collapses to zero height, which is fine because the table above (flex-1)
          absorbs the space. topMovers derives contributors/detractors client-side
          from enrichedHoldings + holdingsQuotes (computed above by useTopMovers).
          PLAN-0122 W-B (render matrix — "Bottom strip cluster"): ADVANCED-only. */}
      {isAdvanced && activePortfolioId && (
        <BottomStripCluster
          portfolioId={activePortfolioId}
          contributors={topMovers.contributors}
          detractors={topMovers.detractors}
        />
      )}

      {/* ══ Wave G: Ticker-pill row + HoldingDetailSlideOver ═════════════════
          WHY preserve from PLAN-0088: the slide-over is orthogonal to the strip
          layout. It adds detail-on-demand for any holding without navigating
          away. The pill row sits AFTER the bottom cluster so it doesn't consume
          above-fold space when holdings are loaded.
          PLAN-0122 W-B (render matrix — "Detail-pill row"): ADVANCED-only. */}
      {isAdvanced && enrichedHoldings.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 px-2 py-1 border-t border-border bg-card shrink-0">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono shrink-0">
            Detail:
          </span>
          {enrichedHoldings.map((h) => (
            <button
              key={h.instrument_id}
              type="button"
              onClick={() =>
                setSelectedHolding(
                  // Toggle: clicking the active holding closes the panel.
                  selectedHolding?.instrument_id === h.instrument_id ? null : h,
                )
              }
              // R3 polish: focus-visible ring appended so the detail pills
              // are keyboard-discoverable (hover-only affordance before).
              className={`text-[10px] font-mono px-1.5 py-0.5 rounded-[2px] border transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring ${
                selectedHolding?.instrument_id === h.instrument_id
                  ? "border-primary text-primary bg-primary/10"
                  : "border-border/60 text-muted-foreground hover:text-foreground hover:border-border"
              }`}
            >
              {h.ticker}
            </button>
          ))}
        </div>
      )}

      {/* HoldingDetailSlideOver: position:absolute, z-40, anchored to this div.
          PLAN-0122 W-B (render matrix — "HoldingDetailSlideOver"): ADVANCED-only
          (its trigger, the detail-pill row, is hidden in Simple). */}
      {isAdvanced && activePortfolioId && (
        <HoldingDetailSlideOver
          portfolioId={activePortfolioId}
          holding={selectedHolding}
          onClose={handleCloseSlideOver}
          period={equityPeriod}
          overview={
            selectedHolding
              ? holdingOverviews?.[selectedHolding.instrument_id]
              : null
          }
          currentPrice={
            selectedHolding
              ? (holdingsQuotes[selectedHolding.instrument_id]?.price ?? null)
              : null
          }
        />
      )}
    </div>
  );
}
