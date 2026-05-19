/**
 * components/instrument/financials/FinancialsTab.tsx — Tab orchestrator (T-C-03)
 *
 * WHY THIS EXISTS: PRD-0088 / PLAN-0090 introduces a new "Financials" tab on the
 * instrument detail page. This component is the top-level layout owner: it
 * assembles the four building blocks delivered in earlier sub-tasks into the
 * 2-column Finviz/Bloomberg-grade view described in §6.8 of the spec.
 *
 * LAYOUT (full tab height):
 *   ┌──────────────────────────────────────────────┬────────────────┐
 *   │ FlatMetricsGrid (T-C-01)                     │ AnalystSidebar │
 *   │ ────────────────────────────────────────     │  (T-C-03)      │
 *   │ IncomeStatementTable (T-C-02)                │                │
 *   │ EarningsBarChart    (T-C-02)                 │   280px wide   │
 *   │ ↕ scrollable                                 │   sticky       │
 *   └──────────────────────────────────────────────┴────────────────┘
 *
 * WHY `flex flex-row h-full overflow-hidden`: PLAN-0090 specifies a fixed
 * full-height tab with the LEFT column scrolling independently and the RIGHT
 * sidebar staying pinned (analysts compare metrics scrolled deep in the income
 * statement against the consensus target — the target should never disappear).
 *
 * WHY useFinancialsTabData (single hook, not 3 hooks): T-A-03 consolidates the
 * three required fetches (key metrics, income statement, analyst consensus)
 * into one hook so the tab renders coherent data — no row-level shimmer with
 * the metrics resolved but the income statement still loading. The hook also
 * dedupes the underlying TanStack Query keys with sibling components.
 *
 * WHO USES IT: InstrumentPageClient.tsx — wired into the "financials" tab.
 * DATA SOURCE: useFinancialsTabData(instrumentId) → S9 /v1/fundamentals/* +
 *              /v1/income-statement/* (see hook for exact wiring).
 */

"use client";
// WHY "use client": the hook uses useQuery (TanStack Query) which requires the
// browser runtime. Marking the orchestrator client-side avoids forcing every
// presentational child to opt-in individually.

import { useFinancialsTabData } from "@/components/instrument/hooks/useFinancialsTabData";
import { FlatMetricsGrid } from "@/components/instrument/financials/FlatMetricsGrid";
import { IncomeStatementTable } from "@/components/instrument/financials/IncomeStatementTable";
import { EarningsBarChart } from "@/components/instrument/financials/EarningsBarChart";
import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface FinancialsTabProps {
  // The S9-side instrument_id. WHY instrument_id (not entity_id): the
  // fundamentals + income-statement endpoints are keyed on instrument_id;
  // entity_id is the canonical KG identifier but doesn't address market-data.
  // The page-bundle in InstrumentPageClient supplies both — we receive the
  // instrument_id here.
  readonly instrumentId: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FinancialsTab({ instrumentId }: FinancialsTabProps) {
  // Single coordinated fetch — see T-A-03 for the underlying query keys.
  const { metrics, incomeStatement, earnings, analyst, updatedAt, isLoading } =
    useFinancialsTabData(instrumentId);

  return (
    // WHY h-full overflow-hidden on the root: locks the tab height so the LEFT
    // column owns scrolling. Without overflow-hidden the page would scroll the
    // whole tab and the sidebar would scroll out of view.
    <div className="flex h-full flex-row overflow-hidden">
      {/* ── Left column — flex-1 lets it consume all remaining width.
          WHY `min-w-0`: flex children with overflow-y-auto inside need an
          explicit min-width or they refuse to shrink and force the parent to
          grow (causing horizontal overflow). */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {/* Block 1: flat key-metrics grid. Always at the top — gives analysts
            the snapshot they need before drilling into multi-year history. */}
        <FlatMetricsGrid metrics={metrics} isLoading={isLoading} />

        {/* Block 2: full income-statement table.
            WHY below the grid (not beside it): the table is wide (5+ columns
            of YoY history). Stacking gives every column the room it needs. */}
        <IncomeStatementTable
          rows={incomeStatement}
          isLoading={isLoading}
        />

        {/* Block 3: quarterly earnings bar chart — fits below the table because
            it shares the temporal axis (quarters) and reads naturally as a
            visual companion. */}
        <EarningsBarChart earnings={earnings} isLoading={isLoading} />
      </div>

      {/* ── Right column — fixed 280px sidebar.
          WHY w-[280px] shrink-0: locked width per spec; shrink-0 prevents the
          flex parent from shrinking the sidebar when the left column has
          unusually long content. */}
      <div className="w-[280px] shrink-0">
        <AnalystSidebar
          strongBuy={analyst.strongBuy}
          buy={analyst.buy}
          hold={analyst.hold}
          sell={analyst.sell}
          strongSell={analyst.strongSell}
          targetPrice={analyst.targetPrice}
          updatedAt={updatedAt}
        />
      </div>
    </div>
  );
}
