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

import { useQuery } from "@tanstack/react-query";
import { useQueryState } from "nuqs";
// WHY useQueryState (nuqs): the selected holding is stored in the URL query
// string (?holding=AAPL). This means:
//   1. The panel state survives a browser refresh — the trader's context is
//      preserved if they copy the URL or reopen a tab.
//   2. The Back button naturally closes the panel (removes ?holding=).
//   3. No extra useState — the URL IS the state.
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
// PRD-0089 SA-B: HoldingDetailPanel slide-over
import { HoldingDetailPanel } from "@/features/portfolio/components/HoldingDetailPanel";
// PLAN-0088 Wave E E-1 strips ────────────────────────────────────────────
import { CashRow } from "@/components/portfolio/CashRow";
import { ConcentrationStrip } from "@/components/portfolio/ConcentrationStrip";
import { ExposureStrip } from "@/components/portfolio/ExposureStrip";
import { DayPnLDistribution } from "@/components/portfolio/DayPnLDistribution";
import { DividendYTDStrip } from "@/components/portfolio/DividendYTDStrip";
import { RealizedPnLSparkline } from "@/components/portfolio/RealizedPnLSparkline";
import { PositionBarHeat } from "@/components/portfolio/PositionBarHeat";
import { HoldingLotsPanel } from "@/components/portfolio/HoldingLotsPanel";
// Surviving components ────────────────────────────────────────────────────
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { SectorAllocationPanel } from "@/components/portfolio/SectorAllocationPanel";
import { RecentActivityFeed } from "@/components/portfolio/RecentActivityFeed";
import { PortfolioAnalyticsSection } from "@/components/portfolio/PortfolioAnalyticsSection";
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
  setEquityPeriod,
}: HoldingsTabProps) {
  const { accessToken } = useAuth();

  // ── PRD-0089 SA-B: URL state for the selected holding ticker ─────────────
  // WHY useQueryState("holding"): stores the selected ticker in the URL so
  // the panel survives a browser refresh and the Back button closes it.
  // Default is null (panel hidden). When the user clicks a holdings row we
  // call setSelectedHolding(row.ticker); a second click or Escape → null.
  const [selectedHolding, setSelectedHolding] = useQueryState("holding");

  /**
   * findHoldingByTicker — look up the enriched Holding by ticker string.
   *
   * WHY a helper (not inline): used in two places (the <HoldingDetailPanel>
   * prop and a future "is this row active?" highlight check). A helper keeps
   * the JSX readable.
   *
   * Returns null when the ticker isn't found (e.g., after holdings reload).
   */
  function findHoldingByTicker(ticker: string) {
    return enrichedHoldings.find((h) => h.ticker === ticker) ?? null;
  }

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
    <div className="bg-background min-h-full">
      {/* ── Top strip cluster (4 × h-7 = 112 px total) ───────────────────────
          Each row is a self-fetching component bound to activePortfolioId.
          The cluster gives the trader a "right-now snapshot" at the top
          of the page before they engage with the table. */}
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
          // PRD-0089 SA-B: when a row is clicked, open the HoldingDetailPanel
          // by storing the ticker in the URL query state (?holding=AAPL).
          // A second click on the same row closes the panel (toggle behaviour).
          onSelectHolding={(ticker) => {
            // Toggle: if this ticker is already selected, deselect it.
            if (selectedHolding === ticker) {
              void setSelectedHolding(null);
            } else {
              void setSelectedHolding(ticker);
            }
          }}
        />
      </div>

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

      {/* ── PRD-0089 SA-B: HoldingDetailPanel slide-over ────────────────────
          Rendered unconditionally so TanStack Query inside the panel keeps
          its cache warm even when the panel is "hidden" (translate-x-full).
          The panel self-hides when `holding === null` via CSS transform, NOT
          by unmounting — this avoids cache invalidation on every open/close.
          WHY activePortfolioId guard: the panel queries by portfolioId; if no
          portfolio is active (shouldn't happen in normal flow) we don't render
          it to avoid a query with an empty portfolioId string. */}
      {activePortfolioId && (
        <HoldingDetailPanel
          portfolioId={activePortfolioId}
          holding={
            selectedHolding
              ? findHoldingByTicker(selectedHolding)
              : null
          }
          onClose={() => void setSelectedHolding(null)}
          period={equityPeriod}
        />
      )}
    </div>
  );
}
