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
  // T-A-03 actual return shape: { fundamentals, snapshot, incomeStatement,
  // earningsHistory, technicals, shareStats, isLoading }. The hook composes
  // the six sub-resources behind a single isLoading gate so the tab renders
  // coherently. IncomeStatementTable and EarningsBarChart are self-fetching
  // (they call into the same query keys), so we don't need to thread their
  // data through — TanStack dedupes on the shared keys.
  const { fundamentals, snapshot, technicals, shareStats } =
    useFinancialsTabData(instrumentId);

  // WHY extract from FundamentalsSectionResponse: useFinancialsTabData's
  // `technicals` and `shareStats` come back as section envelopes; FlatMetricsGrid
  // expects the typed inner data shapes. Pull `records[0].data` defensively —
  // an empty section is rendered as null, MetricCell handles the "—" placeholder.
  const technicalsData = technicals?.records?.[0]?.data ?? null;
  const shareStatsData = shareStats?.records?.[0]?.data ?? null;
  // Splits/dividends are inside fundamentals.splits_dividends per the
  // /v1/fundamentals/{id} response — keep as null for now; FlatMetricsGrid
  // gracefully renders "—" in dividend-date cells when null.
  const dividendsData = null;

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
        <FlatMetricsGrid
          instrumentId={instrumentId}
          fundamentals={fundamentals ?? null}
          snapshot={snapshot ?? null}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- envelope→typed cast (see WHY note above)
          technicals={technicalsData as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- envelope→typed cast (see WHY note above)
          shareStats={shareStatsData as any}
          dividends={dividendsData}
        />

        {/* Block 2: full income-statement table. WHY self-fetch (no props): the
            child component reads /v1/income-statement/{id} via its own useQuery;
            staleTime=24h means it joins the in-flight request fired by the
            useFinancialsTabData hook with no extra round-trip. */}
        <IncomeStatementTable instrumentId={instrumentId} />

        {/* Block 3: annual earnings bar chart — self-fetching for the same
            reason as IncomeStatementTable. */}
        <EarningsBarChart instrumentId={instrumentId} />
      </div>

      {/* ── Right column — fixed 280px sidebar.
          WHY w-[280px] shrink-0: locked width per spec; shrink-0 prevents the
          flex parent from shrinking the sidebar when the left column has
          unusually long content. */}
      <div className="w-[280px] shrink-0">
        <AnalystSidebar
          // WHY pull from fundamentals (not snapshot): analyst counts live on
          // Fundamentals (analyst_*_count fields). targetPrice → analyst_target_price.
          strongBuy={fundamentals?.analyst_strong_buy_count ?? null}
          buy={fundamentals?.analyst_buy_count ?? null}
          hold={fundamentals?.analyst_hold_count ?? null}
          sell={fundamentals?.analyst_sell_count ?? null}
          strongSell={fundamentals?.analyst_strong_sell_count ?? null}
          targetPrice={fundamentals?.analyst_target_price ?? null}
          updatedAt={fundamentals?.updated_at ?? null}
        />
      </div>
    </div>
  );
}
