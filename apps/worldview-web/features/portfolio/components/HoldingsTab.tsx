/**
 * features/portfolio/components/HoldingsTab.tsx — Holdings tab body.
 *
 * REDESIGNED in PLAN-0088 Wave E (audit `docs/audits/2026-05-09-qa-holdings-
 * redesign.md`). The previous layout had 8 widgets stacked at ~1,400 px of
 * scroll; this one delivers 12 widgets at ~700 px by replacing 6 oversized
 * panels with single-row strips.
 *
 * LAYOUT (top → bottom):
 *
 *   1. CashRow              — h-7  cash · buying power · sweep
 *   2. ConcentrationStrip   — h-7  HHI · label · top-3 · #names
 *   3. ExposureStrip        — h-7  invested · cash · leverage · beta-adj
 *   4. DayPnLDistribution   — h-7  30-day Δ$ sparkline + avg/range
 *   ───────────────────────────── (top strip cluster — 4×28 = 112 px)
 *   5. SemanticHoldingsTable — h-auto, 12-column AG Grid (unchanged)
 *   6. HoldingLotsPanel     — collapsible FIFO open-lots drilldown (NEW)
 *   7. PositionBarHeat      — h-12 weight × pnl% mini-bars
 *   8. RealizedPnLSparkline — h-12 cumulative realised + ST/LT split
 *   9. DividendYTDStrip     — h-7  YTD · forward yield · next ex-date
 *  10. SectorAllocationPanel — kept (still useful as a sector mix overview)
 *  11. RecentActivityFeed   — kept ONLY when broker-connected (gated below)
 *  12. PortfolioAnalyticsSection — kept (equity-curve + risk metrics)
 *
 * REMOVED (vs previous layout):
 *   - CashManagementCard       (replaced by CashRow)
 *   - RealizedPnLChart         (replaced by RealizedPnLSparkline)
 *   - DividendIncomeTimeline   (replaced by DividendYTDStrip)
 *   - ExposureBreakdown panel  (replaced by ExposureStrip)
 *   - RecentActivityFeed always-on render (now gated on broker connection)
 *
 * Reason for each deletion lives in the audit; the short version is "every
 * one was either F/D-rated empty-state or 200+ px tall for a single number".
 */

"use client";
// WHY "use client": children components are client components; this wrapper
// inherits the directive so it can pass props through without extra boundary.

import { useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
// PLAN-0088 Wave E E-1 strips ────────────────────────────────────────────
import { CashRow } from "@/components/portfolio/CashRow";
import { ConcentrationStrip } from "@/components/portfolio/ConcentrationStrip";
import { ExposureStrip } from "@/components/portfolio/ExposureStrip";
import { DayPnLDistribution } from "@/components/portfolio/DayPnLDistribution";
import { DividendYTDStrip } from "@/components/portfolio/DividendYTDStrip";
import { RealizedPnLSparkline } from "@/components/portfolio/RealizedPnLSparkline";
import { PositionBarHeat } from "@/components/portfolio/PositionBarHeat";
import { HoldingLotsPanel } from "@/components/portfolio/HoldingLotsPanel";
// Wave G: Holding detail slide-over panel (right-anchored, 440px, non-modal).
import { HoldingDetailSlideOver } from "@/components/portfolio/detail/HoldingDetailSlideOver";
// Surviving components ────────────────────────────────────────────────────
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { SectorAllocationPanel } from "@/components/portfolio/SectorAllocationPanel";
import { RecentActivityFeed } from "@/components/portfolio/RecentActivityFeed";
import { PortfolioAnalyticsSection } from "@/components/portfolio/PortfolioAnalyticsSection";
import type { PeriodLabel } from "@/components/portfolio/EquityCurveChart";
// ── Wave F additions (PRD-0089 W2 overview redesign) ──────────────────────
// These components implement the compact header-strip layout described in the
// design spec: ExposureCurrencyStrip → ConcentrationSectorTeaseStrip →
// PerformanceChartPanel → SectorAllocationBar → Table → ContributorsStrip → RecentActivityStrip.
// WHY add here (not in page.tsx): the Holdings tab is the overview surface.
// page.tsx already handles the KPIStrip at page level; everything below it
// is scoped to the Holdings tab body.
import { ExposureCurrencyStrip } from "@/components/portfolio/ExposureCurrencyStrip";
import { ConcentrationSectorTeaseStrip } from "@/components/portfolio/ConcentrationSectorTeaseStrip";
import { PerformanceChartPanel } from "@/components/portfolio/PerformanceChartPanel";
import type { PerfPeriod } from "@/components/portfolio/PerformanceChartPanel";
import { SectorAllocationBar } from "@/components/portfolio/SectorAllocationBar";
import { ContributorsStrip } from "@/components/portfolio/ContributorsStrip";
import { RecentActivityStrip } from "@/components/portfolio/RecentActivityStrip";
import { useTopMovers } from "@/features/portfolio/hooks/useTopMovers";
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
  setEquityPeriod,
}: HoldingsTabProps) {
  const { accessToken } = useAuth();

  // ── Wave F: PerformanceChartPanel collapsed state ──────────────────────
  // WHY local state (not URL): the collapse toggle is ephemeral UI preference.
  // A deep-link to /portfolio doesn't need to encode whether the chart is open.
  // Design spec §7.1 hotkey "0" can toggle this; the hotkey would call the
  // setter directly. Default: expanded (matches spec §4.1 "default on").
  const [perfChartCollapsed, setPerfChartCollapsed] = useState(false);

  // ── Wave F: PerformanceChartPanel period state ─────────────────────────
  // WHY a separate period (not sharing equityPeriod from PortfolioAnalyticsSection):
  // the PerformanceChartPanel and the full EquityCurveChart may be on different
  // zoom levels simultaneously (PM might have the strip at 1M while the analytics
  // section shows YTD). Keeping them independent preserves both views.
  const [perfPeriod, setPerfPeriod] = useState<PerfPeriod>("3M");

  // ── Wave F: top movers derivation for ContributorsStrip ───────────────
  // useTopMovers computes contributors/detractors client-side from the
  // enriched holdings + live quotes already loaded by usePortfolioData.
  // No extra API call. See features/portfolio/hooks/useTopMovers.ts.
  const { contributors, detractors } = useTopMovers(enrichedHoldings, holdingsQuotes);

  // PLAN-0088 E-1: gate RecentActivityFeed on a broker connection. The
  // audit (§1 row 5) flagged it as empty-state for paper-traders. We do
  // a lightweight brokerage-connection probe here and only render the
  // feed when at least one connection exists. Cached for 60s.
  const { data: brokerageConnections } = useQuery({
    enabled: Boolean(activePortfolioId && accessToken),
    queryKey: ["brokerage-connections", activePortfolioId],
    queryFn: () =>
      createGateway(accessToken!).getBrokerageConnections(activePortfolioId!),
    staleTime: 60_000,
  });
  // WHY ?? false (not a truthy guard): the query returns undefined while
  // loading; we want the feed hidden during that initial frame to avoid
  // a flash-of-empty-feed for paper-traders.
  const hasBrokerage = Boolean(
    brokerageConnections && brokerageConnections.length > 0,
  );

  // ── Wave G: Holding detail slide-over state ────────────────────────────
  // WHY null (not undefined): null is the explicit "no holding selected" signal.
  // undefined would be ambiguous between "not set yet" and "deselected".
  const [selectedHolding, setSelectedHolding] = useState<Holding | null>(null);

  // Stable close handler — avoids re-rendering children on every HoldingsTab render.
  const handleCloseSlideOver = useCallback(() => {
    setSelectedHolding(null);
  }, []);

  if (holdingsLoading && !holdingsResp) {
    // WHY h-[22px] rows: matches the SemanticHoldingsTable <tr> height token
    // exactly. When the data lands, the skeletons fade out and the real rows
    // occupy identical vertical space — no jump (F-P-020).
    return (
      <div className="space-y-px p-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-[22px] w-full" />
        ))}
      </div>
    );
  }

  return (
    // WHY relative: HoldingDetailSlideOver is position:absolute anchored here.
    <div className="bg-background min-h-full relative">
      {/* ══ Wave F additions (PRD-0089 W2 redesign) — above-fold overview strips ══
          Order per design spec §4.2:
            ExposureCurrencyStrip → ConcentrationSectorTeaseStrip →
            PerformanceChartPanel → SectorAllocationBar → Holdings table →
            (below table) ContributorsStrip + RecentActivityStrip
          The existing legacy strips (CashRow, ConcentrationStrip, ExposureStrip,
          DayPnLDistribution) remain below the new ones for backwards-compat.
          When the W2 strips stabilise in production, the legacy strips will be
          removed in a separate cleanup wave. */}

      {/* ── ExposureCurrencyStrip (h-[22px]) ─────────────────────────────────
          Replaces the 120px ExposureStrip with a single compact row.
          currency prop is omitted here — Holding has no `currency` field today.
          A follow-up wave will derive currency breakdown from transaction data. */}
      <ExposureCurrencyStrip portfolioId={activePortfolioId} />

      {/* ── ConcentrationSectorTeaseStrip (h-[22px]) ─────────────────────────
          HHI badge + top-3 sector preview in one compact row. Replaces the
          separate ConcentrationStrip and sector-preview logic. */}
      <ConcentrationSectorTeaseStrip
        portfolioId={activePortfolioId}
        bySector={bySector}
      />

      {/* ── PerformanceChartPanel (h-[120px] when expanded, h-[28px] collapsed)
          Equity-curve strip with period selector and SPY overlay annotation.
          WHY collapsed state lives here (not at page level): only the Holdings
          tab shows this panel; other tabs (Transactions, Watchlist) don't need it.
          collapsed/onToggleCollapse manage the local hide/show of the chart body. */}
      {activePortfolioId && (
        <PerformanceChartPanel
          portfolioId={activePortfolioId}
          period={perfPeriod}
          onPeriodChange={setPerfPeriod}
          collapsed={perfChartCollapsed}
          onToggleCollapse={() => setPerfChartCollapsed((v) => !v)}
        />
      )}

      {/* ── SectorAllocationBar (h-[22px]) ───────────────────────────────────
          Single stacked horizontal bar with top-3 sector labels inline.
          Replaces the 240px SectorAllocationPanel on the overview surface.
          The full panel is kept below for the detailed view. */}
      <SectorAllocationBar bySector={bySector} />

      {/* ── Legacy top strip cluster (preserved for backwards compat) ────────
          These 4 strips still render so users don't lose data they relied on.
          They will be superseded by the W2 strips above in a follow-up wave.
          WHY keep them: the new strips are additive; removing legacy surfaces
          in the same wave as adding new ones risks hidden regressions. */}
      <CashRow portfolioId={activePortfolioId} />
      <ConcentrationStrip portfolioId={activePortfolioId} />
      <ExposureStrip portfolioId={activePortfolioId} />
      <DayPnLDistribution portfolioId={activePortfolioId} />

      {/* ── Holdings table — the primary surface ────────────────────────────
          Same 12-column AG Grid as before. Sectors are projected from the
          holdingOverviews map at render time so the SECTOR column renders
          correctly without a separate fetch. */}
      <div className="p-2">
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
      </div>

      {/* ── Wave G: Compact holding-selector row for the slide-over ─────────
          Renders a row of ticker pills beneath the table. Clicking a pill
          opens the 440px HoldingDetailSlideOver panel on the right.
          WHY a separate row (not onRowClick on the AG Grid): SemanticHoldings-
          Table's AG Grid already wires onCellClicked to navigate to the
          instrument detail page; intercepting that for the slide-over would
          either break the navigation or require adding an extra column.
          A pill row is visually distinct ("click here to open detail panel")
          and avoids changing the AG Grid contract. */}
      {enrichedHoldings.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 px-2 py-1 border-t border-border bg-card">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono shrink-0">
            Detail:
          </span>
          {enrichedHoldings.map((h) => (
            <button
              key={h.instrument_id}
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

      {/* ── Wave G: Holding detail slide-over panel ─────────────────────────
          Renders when selectedHolding is non-null. Position:absolute anchored
          to the closest position:relative ancestor (the main div above).
          z-40 sits above the table (default stacking) but below modals (z-50). */}
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

      {/* ── PLAN-0088 E-2: FIFO tax-lot drilldown ───────────────────────────
          Standalone panel (not an inline AG Grid expand row) because the
          table's onRowClicked already navigates to the instrument page —
          we don't want to take that interaction over. The user picks a
          ticker via the dropdown inside the panel.
          WHY no px-2 wrapper: HoldingLotsPanel renders edge-to-edge like
          PositionBarHeat and the other strip components below it. A px-2
          inset made the card visually narrower than every adjacent strip,
          breaking the horizontal rhythm. */}
      <HoldingLotsPanel
        portfolioId={activePortfolioId}
        holdings={enrichedHoldings}
        quotes={holdingsQuotes}
      />

      {/* ── PLAN-0088 E-4: position-bar heat strip ──────────────────────────
          Uses the props the parent already loaded — no extra fetch. Width =
          weight, height = pnl%, color = sign. One-glance winners/losers. */}
      <PositionBarHeat
        holdings={enrichedHoldings}
        quotes={holdingsQuotes}
        totalValue={kpi.totalValue}
      />

      {/* ── PLAN-0088 E-2: realised P&L sparkline (replaces 280 px chart) ──
          Single h-12 row: total + ST/LT split + cumulative inline sparkline. */}
      <RealizedPnLSparkline portfolioId={activePortfolioId} />

      {/* ── PLAN-0088 E-1: dividend YTD strip (replaces 470 px timeline) ───
          One h-7 row instead of a stacked monthly chart that was almost
          always empty for paper-traders. */}
      <DividendYTDStrip portfolioId={activePortfolioId} />

      {/* ── Sector mix — KEPT (audit B-rated, useful) ───────────────────────
          The bars-only mode is denser than the treemap; the panel itself
          handles the toggle. */}
      <SectorAllocationPanel bySector={bySector} byType={byType} />

      {/* ══ Wave F bottom strip cluster ══════════════════════════════════════
          Design spec §4.1 bottom layout: ContributorsStrip + RecentActivityStrip
          side-by-side (3-cell grid: Contributors | empty | RecentActivity).
          WHY grid (not flex): grid lets us define fixed proportions (col-span 5
          for movers, col-span 4 for activity) that are stable regardless of
          content height. The design spec shows a 3-column layout; we simplify
          to 2 columns since the middle cell in the spec is unused ("empty"). */}
      <div className="grid grid-cols-2 border-t border-border bg-card min-h-[96px]">
        {/* Top Contributors + Top Detractors — left half */}
        <div className="border-r border-border">
          <ContributorsStrip
            contributors={contributors}
            detractors={detractors}
            isLoading={holdingsLoading}
          />
        </div>

        {/* Recent Activity — right half */}
        <div>
          <RecentActivityStrip portfolioId={activePortfolioId} />
        </div>
      </div>

      {/* ── Recent activity feed — GATED on broker connection ───────────────
          Per audit §1 row 5: feed is empty for paper-traders so it should
          not render. For broker-connected users it's still the right
          "what happened on my account" surface. */}
      {hasBrokerage && (
        <div className="mt-3">
          <RecentActivityFeed portfolioId={activePortfolioId} />
        </div>
      )}

      {/* ── Equity curve + risk metrics ─────────────────────────────────────
          Existing analytics section — equity curve fix (F-H-1 from the
          audit) is tracked separately. */}
      {activePortfolioId && (
        <PortfolioAnalyticsSection
          portfolioId={activePortfolioId}
          period={equityPeriod}
          onPeriodChange={setEquityPeriod}
        />
      )}
    </div>
  );
}
