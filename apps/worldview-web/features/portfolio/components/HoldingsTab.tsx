/**
 * features/portfolio/components/HoldingsTab.tsx — Holdings tab body.
 *
 * WHY THIS EXISTS (PLAN-0059 E-2 follow-up): the Holdings tab carried the
 * heaviest data surface in the portfolio page (~250 LOC inline) — Cash card,
 * Realized P&L chart, semantic holdings table, sector allocation panel,
 * recent activity feed, dividend timeline, analytics section. Lifting all
 * of it into a stateless component lets the page focus on tab routing.
 *
 * BEHAVIOR PARITY: every conditional rendering rule, every layout class,
 * the F-205 sectors-projection inline shape, and the F-P-020 skeleton
 * dimensions are preserved verbatim.
 *
 * WHO USES IT: only the portfolio page.
 * DESIGN REFERENCE: PRD-0031 §8 Portfolio, Holdings tab.
 */

"use client";
// WHY "use client": children components are client components; this wrapper
// inherits the directive so it can pass props through without extra boundary.

import { Skeleton } from "@/components/ui/skeleton";
import { CashManagementCard } from "@/components/portfolio/CashManagementCard";
import { RealizedPnLChart } from "@/components/portfolio/RealizedPnLChart";
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { SectorAllocationPanel } from "@/components/portfolio/SectorAllocationPanel";
import { RecentActivityFeed } from "@/components/portfolio/RecentActivityFeed";
import { DividendIncomeTimeline } from "@/components/portfolio/DividendIncomeTimeline";
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

  // WHY bg-background (not min-h-full): min-height: 100% does NOT resolve
  // reliably when the parent is an overflow-y:auto scroll container whose
  // height is flex-derived (no explicit pixel height). The browser sees the
  // scroll container's "content height" as the reference — not its visual
  // height — so the child stays short and exposes the terminal-dark (#09090b)
  // page background below the data. Painting bg-background on the wrapper
  // covers that gap without fighting CSS height resolution semantics.
  return (
    <div className="p-2 bg-background">
      {/* PLAN-0053 T-B-2-04: Cash management card just below the KPI strip —
          at-a-glance dry-powder + cash drag awareness. */}
      <CashManagementCard portfolioId={activePortfolioId} />

      {/* PLAN-0053 T-D-4-03: Realized P&L chart with period toggle and
          per-instrument breakdown. WHY above the holdings table: realised
          P&L is a "look-back" cashflow signal — the user's digest order is
          "what did I close?" → "what's open now?". */}
      <div className="mt-2">
        <RealizedPnLChart portfolioId={activePortfolioId} />
      </div>

      {/* WHY enrichedHoldings: raw holdings have empty ticker/name (S1
          doesn't store them). enrichedHoldings merges ticker/name/entity_id
          from company overviews so the TICKER and NAME columns render
          correctly. */}
      {/* F-205 fix (PLAN-0048 QA iter-1): the SECTOR column was rendering
          "—" for every holding because we never passed `sectors`. The data
          is already loaded for the allocation panel below — we just project
          it into the instrument_id → sector shape SemanticHoldingsTable
          expects. WHY inline (not useMemo): the projection is O(n) over a
          small array (≤50 holdings) and runs only when overviews resolve;
          memoising adds complexity without measurable benefit at this
          size. */}
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

      {/* Sector allocation — populated once holdingOverviews resolves (the
          query lives in usePortfolioData). Before that, bySector/byType are
          empty and SectorAllocationPanel returns null. WHY no explicit
          loading state here: the panel hides itself gracefully — no
          jarring layout shift; it appears once overviews resolve (~300ms
          after holdings). */}
      <SectorAllocationPanel bySector={bySector} byType={byType} />

      {/* PLAN-0053 T-B-2-05: Recent activity feed — transactions +
          broker-sync events merged by timestamp. WHY here (not the
          Transactions tab): Holdings is the "morning glance" surface;
          users want to see what happened on their account without
          leaving this view. */}
      <div className="mt-3">
        <RecentActivityFeed portfolioId={activePortfolioId} />
      </div>

      {/* PLAN-0053 T-B-2-06: Dividend income YTD timeline with per-ticker
          breakdown. WHY at the bottom: dividend cashflow is a "deeper
          dive" answer — once positions and recent activity have been
          scanned, users may want to know "how is my income running this
          year?". */}
      <div className="mt-3">
        <DividendIncomeTimeline portfolioId={activePortfolioId} />
      </div>

      {/* PLAN-0046 Wave 5 / T-46-5-07: analytics section. WHY conditional
          on activePortfolioId: the analytics queries need a real id to
          fan out to S9. Without one we'd render three loading states
          forever. */}
      {activePortfolioId && (
        // F-P-003: thread the hoisted period state down so the chart
        // toggles update page-level state. Other panels can subscribe to
        // ``equityPeriod`` to mirror the user's choice.
        <PortfolioAnalyticsSection
          portfolioId={activePortfolioId}
          period={equityPeriod}
          onPeriodChange={setEquityPeriod}
        />
      )}
    </div>
  );
}
