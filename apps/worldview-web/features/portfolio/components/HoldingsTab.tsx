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
 *   1. ExposureCurrencyStrip      h-[22px]  INV%/CASH$/LEV×/β-ADJ/CCY
 *   2. ConcentrationSectorTeaseStrip h-[22px] HHI badge + top-3 sectors
 *   3. PerformanceChartPanel      h-[120px] collapsible equity-curve + SPY overlay
 *   4. SectorAllocationBar        h-[22px]  stacked bar + top-3 sector labels
 *   5. HoldingsTableChrome        h-[22px]  position count + Ctrl+F filter shortcut
 *   6. SemanticHoldingsTable      flex-1    AG Grid, 12-column + SPARK
 *   7. BottomStripCluster         h-24      placeholder for W4 (ContributorsStrip + RecentActivityStrip)
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

import { useState, useCallback, useMemo } from "react";
import { Skeleton } from "@/components/ui/skeleton";
// ── PRD-0108 W3 layout strips ─────────────────────────────────────────────────
import { ExposureCurrencyStrip } from "@/components/portfolio/ExposureCurrencyStrip";
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
} from "@/types/api";
import type {
  PortfolioKPI,
  PortfolioAllocations,
  HoldingOverviewMap,
} from "@/features/portfolio/lib/kpi";

interface HoldingsTabProps {
  activePortfolioId: string | null;
  holdingsLoading: boolean;
  holdingsResp: HoldingsResponse | undefined;
  enrichedHoldings: Holding[];
  holdingsQuotes: BatchQuoteResponse["quotes"];
  holdingOverviews: HoldingOverviewMap | undefined;
  kpi: PortfolioKPI;
  bySector: PortfolioAllocations["bySector"];
  byType: PortfolioAllocations["byType"];
  /** F-P-003: equity-curve period state hoisted to the page. */
  equityPeriod: PeriodLabel;
  setEquityPeriod: (period: PeriodLabel) => void;
}

export function HoldingsTab({
  activePortfolioId,
  holdingsLoading,
  holdingsResp,
  enrichedHoldings,
  holdingsQuotes,
  holdingOverviews,
  kpi,
  bySector,
  byType,
  equityPeriod,
  // setEquityPeriod was used by PortfolioAnalyticsSection (now in Analytics tab).
  // Retained in the interface so page.tsx props don't change; prefixed _  to
  // suppress the unused-variable lint warning.
  setEquityPeriod: _setEquityPeriod,
}: HoldingsTabProps) {
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

  // ── Wave G: Holding detail slide-over state ────────────────────────────────
  // WHY null (not undefined): null is the explicit "no holding selected" signal.
  const [selectedHolding, setSelectedHolding] = useState<Holding | null>(null);
  const handleCloseSlideOver = useCallback(() => setSelectedHolding(null), []);

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

      {/* ══ 1. ExposureCurrencyStrip (h-[22px]) ══════════════════════════════════
          WHY first: exposure is the most forward-looking risk signal.
          Bloomberg PORT shows "% Invested / Cash / Leverage" in the topmost row
          so the PM knows their deployment ratio before scanning individual positions.
          betaAdjExposure is computed above from holdings × beta (default 1.0).
          Null when no holdings — the cell shows "—" rather than a wrong value. */}
      <ExposureCurrencyStrip
        portfolioId={activePortfolioId}
        betaAdjExposure={betaAdjExposure}
      />

      {/* ══ 2. ConcentrationSectorTeaseStrip (h-[22px]) ═══════════════════════
          WHY second: after knowing deployment ratio, concentration risk is the
          next most actionable signal. HHI badge + top-3 sectors in one row.
          bySector comes from usePortfolioData (no extra fetch needed here). */}
      <ConcentrationSectorTeaseStrip
        portfolioId={activePortfolioId}
        bySector={bySector}
      />

      {/* ══ 3. PerformanceChartPanel (h-[120px] expanded, h-[28px] collapsed) ══
          WHY third: trend context belongs above the table, not below. The PM
          needs to see if the portfolio is up/down today vs SPY before analysing
          individual positions. Collapsible to 28px so power users can maximise
          table rows.
          WHY guard on activePortfolioId: the panel fires a useQuery that requires
          a valid portfolioId. With null, the query is disabled but the DOM still
          mounts — the guard prevents a wasted paint. */}
      {activePortfolioId && (
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
          replaces the 240px SectorAllocationPanel on this above-fold surface. */}
      <SectorAllocationBar bySector={bySector} />

      {/* ══ 5. HoldingsTableChrome (h-[22px]) ════════════════════════════════
          WHY fifth: the chrome row anchors the table header. It shows position
          count (quick sanity check) and the Ctrl+F filter shortcut.
          WHY filter state here (not in SemanticHoldingsTable): HoldingsTableChrome
          needs to fire onFilterFocus when Ctrl+F is pressed; the table needs to
          receive the filterText to drive AG Grid quickFilter. Hosting both in
          the same parent avoids prop-drilling through SemanticHoldingsTable's
          public interface (which is data-driven, not filter-driven). */}
      <HoldingsTableChrome
        positionCount={enrichedHoldings.length}
        onFilterFocus={handleFilterFocus}
        filterText={filterText}
        onFilterChange={setFilterText}
        filterVisible={filterVisible}
        onFilterVisibleChange={setFilterVisible}
      />

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
          series={holdingsSeries}
        />
      </div>

      {/* ══ 7. BottomStripCluster (h-24) — wired in W4-T405 ════════════════════
          WHY guard on activePortfolioId: BottomStripCluster requires a non-null
          string portfolioId (RecentActivityStrip uses it for its transaction query).
          When no portfolio is selected the cluster is simply absent — the slot
          collapses to zero height, which is fine because the table above (flex-1)
          absorbs the space. topMovers derives contributors/detractors client-side
          from enrichedHoldings + holdingsQuotes (computed above by useTopMovers). */}
      {activePortfolioId && (
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
          above-fold space when holdings are loaded. */}
      {enrichedHoldings.length > 0 && (
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
              className={`text-[10px] font-mono px-1.5 py-0.5 rounded-[2px] border transition-colors ${
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

      {/* HoldingDetailSlideOver: position:absolute, z-40, anchored to this div. */}
      {activePortfolioId && (
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
