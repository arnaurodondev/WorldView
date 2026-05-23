/**
 * components/instrument/financials/FinancialsTab.tsx — Tab orchestrator (T-25 W3 extension)
 *
 * WHY THIS EXISTS: PRD-0088 / PLAN-0090 introduces a new "Financials" tab on the
 * instrument detail page. This component is the top-level layout owner: it
 * assembles all building blocks into the 2-column Finviz/Bloomberg-grade view
 * described in §6.8 of the spec.
 *
 * LAYOUT (full tab height):
 *   ┌──────────────────────────────────────────────────────┬───────────┐
 *   │ DenseMetricsGrid (40 cells, 6-col)                   │ Analyst   │
 *   │ IncomeStatementTable (A/Q toggle via p chord)        │ Sidebar   │
 *   │ EarningsBarChart (64px)                              │  (7       │
 *   │ PeerComparisonTable (5 peers + self)                 │  panels,  │
 *   │ InsiderTransactionsTable (8 rows)                    │  240px    │
 *   │ InstitutionalHoldersTable (10 rows)                  │  sticky)  │
 *   │ FundHoldersTable (10 rows)                           │           │
 *   │ ↕ scrollable                                         │           │
 *   └──────────────────────────────────────────────────────┴───────────┘
 *
 * WHY `flex flex-row h-full overflow-hidden`: PLAN-0090 specifies a fixed
 * full-height tab with the LEFT column scrolling independently and the RIGHT
 * sidebar staying pinned.
 *
 * WHY useFinancialsSidebarData: T-04 loads 4 slow-changing resources (insider,
 * institutional, fund, peers) independently of the main tab data. The hook
 * fires 4 parallel queries; data is prop-drilled to the table components.
 *
 * WHO USES IT: InstrumentPageClient.tsx — wired into the "financials" tab.
 * DATA SOURCE: useFinancialsTabData + useFinancialsSidebarData + splits-dividends.
 */

"use client";
// WHY "use client": hooks (useQuery, useState, useEffect) require the browser runtime.

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useFinancialsTabData } from "@/components/instrument/hooks/useFinancialsTabData";
import { useFinancialsSidebarData } from "@/components/instrument/hooks/useFinancialsSidebarData";
import { DenseMetricsGrid } from "@/components/instrument/financials/DenseMetricsGrid";
import { IncomeStatementTable } from "@/components/instrument/financials/IncomeStatementTable";
import { EarningsBarChart } from "@/components/instrument/financials/EarningsBarChart";
import { PeerComparisonTable } from "@/components/instrument/financials/PeerComparisonTable";
import { InsiderTransactionsTable } from "@/components/instrument/financials/InsiderTransactionsTable";
import { InstitutionalHoldersTable } from "@/components/instrument/financials/InstitutionalHoldersTable";
import { FundHoldersTable } from "@/components/instrument/financials/FundHoldersTable";
import { FundamentalsTimeseriesChart } from "@/components/instrument/financials/FundamentalsTimeseriesChart";
import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";

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
  // ── Period toggle state (p chord) ─────────────────────────────────────────
  // WHY local state (not URL param): period choice is ephemeral — analysts
  // switch between annual/quarterly within a session but don't bookmark it.
  // Keeping it in local state avoids URL pollution and router navigation cost.
  const [periodType, setPeriodType] = useState<"ANNUAL" | "QUARTERLY">("ANNUAL");

  // WHY listen for wv:financials-period-toggle event: InstrumentTabs.tsx fires
  // this event when the user presses `p` while on the Financials tab. Custom
  // events let InstrumentTabs remain unaware of FinancialsTab internals — same
  // pattern as the `b`/`d` chords for brief/desc toggle in QuoteTab.
  useEffect(() => {
    const handler = () =>
      setPeriodType((prev) => (prev === "ANNUAL" ? "QUARTERLY" : "ANNUAL"));
    window.addEventListener("wv:financials-period-toggle", handler);
    return () => window.removeEventListener("wv:financials-period-toggle", handler);
  }, []);

  // ── Tab data ──────────────────────────────────────────────────────────────
  // T-A-03: six sub-resources bundled in one hook for coherent loading.
  const { fundamentals, snapshot, technicals, shareStats } =
    useFinancialsTabData(instrumentId);

  // T-04: 4 sidebar-specific slow-changing resources (24h stale).
  const { insiderData, institutionalData, fundHoldersData, peersData } =
    useFinancialsSidebarData(instrumentId);

  // WHY a dedicated splits-dividends fetch (not bundled in useFinancialsTabData):
  // splits-dividends is rarely-changing (filing-cadence) — 24h staleTime works.
  const gateway = useApiClient();
  const { data: splitsDivResp } = useQuery({
    queryKey: qk.instruments.splitsDividends(instrumentId),
    queryFn: () => gateway.getSplitsDividends(instrumentId),
    staleTime: 24 * 60 * 60 * 1000,
    enabled: !!instrumentId,
  });

  // WHY extract from FundamentalsSectionResponse: useFinancialsTabData's
  // `technicals` and `shareStats` come back as section envelopes; DenseMetricsGrid
  // expects the typed inner data shapes.
  const technicalsData = technicals?.records?.[0]?.data ?? null;
  const shareStatsData = shareStats?.records?.[0]?.data ?? null;
  const dividendsData = splitsDivResp?.records?.[0]?.data
    ? (splitsDivResp.records[0].data as {
        ExDividendDate?: string | null;
        DividendDate?: string | null;
      })
    : null;

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
        {/* Block 1: 40-cell 6-col DenseMetricsGrid. Always at the top —
            gives analysts the snapshot before drilling into multi-year history. */}
        <DenseMetricsGrid
          fundamentals={fundamentals ?? null}
          snapshot={snapshot ?? null}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- envelope→typed cast (see WHY note above)
          technicals={technicalsData as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any -- envelope→typed cast (see WHY note above)
          shareStats={shareStatsData as any}
          dividends={dividendsData}
        />

        {/* Block 2: income statement — annual (5 cols) or quarterly (8 cols),
            controlled by p chord firing wv:financials-period-toggle. */}
        <IncomeStatementTable
          instrumentId={instrumentId}
          periodType={periodType}
        />

        {/* Block 3: annual EPS beat/miss bar chart (64px, surprise chips). */}
        <EarningsBarChart instrumentId={instrumentId} />

        {/* Block 3b: 11-metric historical trend chart (PLAN-0092 Wave B).
            WHY after EarningsBarChart: EPS chart shows the bottom line; the
            timeseries chart shows how valuation multiples have moved alongside
            earnings — the natural next question an analyst asks. */}
        <FundamentalsTimeseriesChart instrumentId={instrumentId} />

        {/* Block 4: 5-peer + self comparison table.
            WHY pass peersData + fundamentals: PeerComparisonTable needs both
            to populate the self-row (ticker/name/mktcap/pe from fundamentals)
            and the peer rows (from peersData). */}
        <PeerComparisonTable
          peersData={peersData}
          instrumentId={instrumentId}
          fundamentals={fundamentals ?? null}
        />

        {/* Block 5: insider transactions — 8 most-recent Form 4 filings. */}
        <InsiderTransactionsTable
          insiderData={insiderData}
          ticker={fundamentals?.ticker ?? null}
        />

        {/* Block 6: top 10 institutional shareholders. */}
        <InstitutionalHoldersTable institutionalData={institutionalData} />

        {/* Block 7: top 10 mutual fund / ETF holders. */}
        <FundHoldersTable fundHoldersData={fundHoldersData} />
      </div>

      {/* ── Right column — fixed 240px sidebar (T-24: narrowed from 280px). */}
      <div className="w-[240px] shrink-0">
        <AnalystSidebar
          instrumentId={instrumentId}
          fundamentals={fundamentals ?? null}
          snapshot={snapshot ?? null}
        />
      </div>
    </div>
  );
}
