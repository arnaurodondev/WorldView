/**
 * components/instrument/financials/FinancialsTab.tsx — Financials tab orchestrator
 * (Wave-2 frontend rework: "dense, Bloomberg/Finviz-grade financials view").
 *
 * WHY THIS REWRITE: the previous tab was a flat stack of 8 blocks with three
 * structural problems that read as "sloppy":
 *   1. The income statement rendered TWICE (standalone IncomeStatementTable
 *      + a 2-column mini-table inside FinancialStatementsPanel);
 *   2. EarningsBarChart floated as an orphan SVG with no header band;
 *   3. Panel chrome drifted — 20/24/28px headers, 9px vs 10px labels.
 * The rework consolidates statements into ONE multi-period section, gives
 * every panel identical 24px accent-bar chrome (PanelHeader), and opens
 * with a key-ratio strip so the tab has a visual hierarchy.
 *
 * LAYOUT (full tab height):
 *   ┌────────────────────────────────────────────────────────────────────┐
 *   │ KeyRatioStrip — 12 headline ratios, one 38px band (full width)     │
 *   ├───────────────────────────────────────────────────┬────────────────┤
 *   │ DenseMetricsGrid — 6-col snapshot, accent headers │ AnalystSidebar │
 *   │ StatementsSection — Income/Balance/Cash Flow      │  (5 panels)    │
 *   │   multi-period tables, ANNUAL/QUARTERLY/TTM, YoY, │  240px wide    │
 *   │   trend sparklines (p chord cycles the mode)      │  scrolls       │
 *   │ EarningsBarChart — EPS actual vs estimate + chips │  independently │
 *   │ PeerComparisonTable — self + 8 peers (Wave-1 API) │                │
 *   │ InsiderTransactionsTable — 8 rows                 │                │
 *   │ InstitutionalHoldersTable — 10 rows               │                │
 *   │ FundHoldersTable — 10 rows                        │                │
 *   │ ↕ scrollable left column                          │                │
 *   └───────────────────────────────────────────────────┴────────────────┘
 *
 * WHY 240px sidebar (kept from W3 §9.3): narrowing from 280px gave the left
 * column the width the peer table's 7-col grid needs.
 *
 * WHY THE `p` CHORD MOVED OUT: it only ever toggled the statements period;
 * the handler + state now live in StatementsSection (co-located with their
 * single consumer), which deletes the periodType/onPeriodToggle prop pair
 * this orchestrator used to drill.
 *
 * WHO USES IT: InstrumentPageClient.tsx — wired into the "financials" tab.
 * DATA SOURCE: useFinancialsTabData (bundle-warmed) + useFinancialsSidebarData
 *   (holders) + per-panel self-fetching hooks (peers, statements, earnings).
 */

"use client";
// WHY "use client": data hooks (useQuery wrappers) require the browser runtime.

import { useQuery } from "@tanstack/react-query";

import { useFinancialsTabData } from "@/components/instrument/hooks/useFinancialsTabData";
import { useFinancialsSidebarData } from "@/components/instrument/hooks/useFinancialsSidebarData";
import { KeyRatioStrip } from "@/components/instrument/financials/KeyRatioStrip";
import { DenseMetricsGrid } from "@/components/instrument/financials/DenseMetricsGrid";
import { StatementsSection } from "@/components/instrument/financials/statements/StatementsSection";
import { EarningsBarChart } from "@/components/instrument/financials/EarningsBarChart";
import { PeerComparisonTable } from "@/components/instrument/financials/PeerComparisonTable";
import { InsiderTransactionsTable } from "@/components/instrument/financials/InsiderTransactionsTable";
import { InstitutionalHoldersTable } from "@/components/instrument/financials/InstitutionalHoldersTable";
import { FundHoldersTable } from "@/components/instrument/financials/FundHoldersTable";
import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { Instrument, Quote } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface FinancialsTabProps {
  // Post-F2: instrument_id and entity_id are the same UUID (Δ8).
  readonly instrumentId: string;
  // entityId for the AIBriefPanel (briefing endpoint key).
  readonly entityId: string;
  // instrument from page bundle — CompanySnapshotPanel needs sector/industry/HQ.
  readonly instrument: Instrument | null;
  // quote from page bundle — TargetPricePanel upside % + the peer table's
  // self row (LAST / DAY % now render real values, Wave-2).
  readonly quote: Quote | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FinancialsTab({ instrumentId, entityId, instrument, quote }: FinancialsTabProps) {
  // ── Data fetching ──────────────────────────────────────────────────────────
  // Bundle-warmed snapshot data (fundamentals / snapshot / technicals /
  // share stats) — one composite POST hydrates the per-widget cache keys.
  const { fundamentals, snapshot, technicals, shareStats } = useFinancialsTabData(instrumentId);

  // Ownership tables (insider / institutional / fund holders). NOTE: this
  // hook also fires the LEGACY n=5 peers query; the redesigned
  // PeerComparisonTable self-fetches the Wave-1 n=8 endpoint via usePeers
  // (the hook file lives in Quote-agent-owned hooks/ — read-only this wave,
  // so its peers leg is simply unused here; see usePeers.ts for the key
  // separation rationale).
  const { insiderData, institutionalData, fundHoldersData } =
    useFinancialsSidebarData(instrumentId);

  const token = useAccessToken();
  // Splits/dividends — feeds the EX-DIV / PAY DATE cells of the grid. 24h
  // staleness: corporate-action dates change on announcement cadence.
  const { data: splitsDivResp } = useQuery({
    queryKey: qk.instruments.splitsDividends(instrumentId),
    queryFn: () => createGateway(token).getSplitsDividends(instrumentId),
    staleTime: 24 * 60 * 60 * 1000,
    enabled: !!instrumentId,
  });

  // Unwrap the single-record EODHD section payloads the grid expects.
  const technicalsData = technicals?.records?.[0]?.data ?? null;
  const shareStatsData = shareStats?.records?.[0]?.data ?? null;
  const dividendsData = splitsDivResp?.records?.[0]?.data
    ? (splitsDivResp.records[0].data as {
        ExDividendDate?: string | null;
        DividendDate?: string | null;
      })
    : null;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Band 1: key ratio strip — full width, above both columns, so the
          headline ratios stay visible regardless of which column scrolls. ── */}
      <KeyRatioStrip fundamentals={fundamentals ?? null} snapshot={snapshot ?? null} />

      <div className="flex min-h-0 flex-1 flex-row overflow-hidden">
        {/* ── Left column — flex-1 takes remaining width after sidebar ──── */}
        <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          {/* Block 1: DenseMetricsGrid — 6-col reference snapshot (kept from
              W3; its internal accent section headers established the pattern
              the whole tab now follows). */}
          <DenseMetricsGrid
            fundamentals={fundamentals ?? null}
            snapshot={snapshot ?? null}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            technicals={technicalsData as any}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            shareStats={shareStatsData as any}
            dividends={dividendsData}
          />

          {/* Block 2: StatementsSection — Income / Balance / Cash Flow proper
              multi-period tables. Replaces the old IncomeStatementTable +
              FinancialStatementsPanel pair (income used to render twice). */}
          <StatementsSection instrumentId={instrumentId} />

          {/* Block 3: EarningsBarChart — now a named panel (header + legend)
              instead of an orphan SVG. */}
          <EarningsBarChart instrumentId={instrumentId} />

          {/* Block 4: PeerComparisonTable — self + 8 peers with live LAST /
              DAY % from the Wave-1 upgraded endpoint (self-fetching). */}
          <PeerComparisonTable
            fundamentals={fundamentals ?? null}
            quote={quote}
            instrumentId={instrumentId}
          />

          {/* Blocks 5-7: ownership tables — uniform PanelHeader chrome. */}
          <InsiderTransactionsTable
            insiderData={insiderData}
            ticker={instrument?.ticker ?? fundamentals?.ticker ?? ""}
          />
          <InstitutionalHoldersTable institutionalData={institutionalData} />
          <FundHoldersTable fundHoldersData={fundHoldersData} />
        </div>

        {/* ── Right column — fixed 240px sidebar, scrolls independently ── */}
        <div className="w-[240px] shrink-0">
          <AnalystSidebar
            instrument={instrument ?? null}
            fundamentals={fundamentals ?? null}
            currentPrice={quote?.price ?? null}
            entityId={entityId || instrumentId}
            instrumentId={instrumentId}
          />
        </div>
      </div>
    </div>
  );
}
