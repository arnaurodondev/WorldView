/**
 * components/instrument/financials/FinancialsTab.tsx — Financials tab orchestrator (T-25)
 *
 * WHY THIS EXISTS: PLAN-0089 W3 redesign — replaces the old 2-section layout
 * (FlatMetricsGrid + IncomeStatementTable + AnalystSidebar) with a Bloomberg-
 * grade 7-section left column + 7-panel right sidebar. Density target ≥80
 * visible data cells above the fold at 1440×900.
 *
 * LAYOUT (full tab height):
 *   ┌─────────────────────────────────────────────┬──────────────┐
 *   │ DenseMetricsGrid (T-06) — 6-col, 40 cells   │ AnalystSidebar│
 *   │ IncomeStatementTable (T-10) — p/P chord      │  (T-24)       │
 *   │ EarningsBarChart    (T-11) — 64px, EPS chip  │  240px wide   │
 *   │ PeerComparisonTable (T-12) — 5 peers + self  │  sticky       │
 *   │ InsiderTransactionsTable (T-13) — 8 rows     │               │
 *   │ InstitutionalHoldersTable (T-14) — 10 rows  │               │
 *   │ FundHoldersTable (T-15) — 10 rows            │               │
 *   │ ↕ scrollable left column                    │               │
 *   └─────────────────────────────────────────────┴──────────────┘
 *
 * WHY 240px sidebar (was 280px): per §9.3 of the design spec. Narrowing gives
 * the left column 40px more — enough for PeerComparisonTable 6-col grid.
 *
 * WHY `p`/`P` chord for period toggle (Δ12): `q` is owned by InstrumentTabs
 * for "Quote tab" navigation. `p` = period, no collision in the chord registry.
 *
 * WHO USES IT: InstrumentPageClient.tsx — wired into the "financials" tab.
 * DATA SOURCE: useFinancialsTabData + useFinancialsSidebarData hooks.
 */

"use client";
// WHY "use client": multiple hooks require the browser runtime (useQuery,
// useState for period toggle, useEffect for hotkey registration).

import { useState, useEffect, useCallback } from "react";
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
import { AnalystSidebar } from "@/components/instrument/financials/AnalystSidebar";
import { createGateway } from "@/lib/gateway";
import { useAccessToken } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import type { Instrument, Quote } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface FinancialsTabProps {
  // Post-F2: instrument_id and entity_id are the same UUID — Δ8 removes the
  // old warning comment that explained the historical split.
  readonly instrumentId: string;
  // entityId for the AIBriefPanel (briefing endpoint key).
  readonly entityId: string;
  // instrument from page bundle — CompanySnapshotPanel needs sector/industry/HQ.
  readonly instrument: Instrument | null;
  // quote from page bundle — TargetPricePanel uses current price for upside %.
  readonly quote: Quote | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FinancialsTab({ instrumentId, entityId, instrument, quote }: FinancialsTabProps) {
  // ── Period toggle (Δ12: p/P chord) ─────────────────────────────────────────
  // Controls whether IncomeStatementTable shows Annual or Quarterly data.
  // WHY local state (not URL param): the toggle is a transient UI preference.
  const [periodType, setPeriodType] = useState<"ANNUAL" | "QUARTERLY">("ANNUAL");

  // WHY useCallback on toggle: the handler is referenced in useEffect's
  // dependency array. A stable reference avoids re-registering every render.
  const togglePeriod = useCallback(() => {
    setPeriodType((prev) => (prev === "ANNUAL" ? "QUARTERLY" : "ANNUAL"));
  }, []);

  // Register `p`/`P` chord for period toggle while Financials tab is active.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const inInput =
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable;
      if (inInput) return;
      if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        togglePeriod();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [togglePeriod]);

  // ── Data fetching ─────────────────────────────────────────────────────────

  const { fundamentals, snapshot, technicals, shareStats } =
    useFinancialsTabData(instrumentId);

  const {
    insiderData,
    institutionalData,
    fundHoldersData,
    peersData,
    isLoading: sidebarLoading,
  } = useFinancialsSidebarData(instrumentId);

  const token = useAccessToken();
  const { data: splitsDivResp } = useQuery({
    queryKey: qk.instruments.splitsDividends(instrumentId),
    queryFn: () => createGateway(token).getSplitsDividends(instrumentId),
    staleTime: 24 * 60 * 60 * 1000,
    enabled: !!instrumentId,
  });

  const technicalsData = technicals?.records?.[0]?.data ?? null;
  const shareStatsData = shareStats?.records?.[0]?.data ?? null;
  const dividendsData = splitsDivResp?.records?.[0]?.data
    ? (splitsDivResp.records[0].data as {
        ExDividendDate?: string | null;
        DividendDate?: string | null;
      })
    : null;

  return (
    <div className="flex h-full flex-row overflow-hidden">
      {/* ── Left column — flex-1 takes remaining width after sidebar ──── */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        {/* Block 1: DenseMetricsGrid — 6-col, 40 cells, 18px rows */}
        <DenseMetricsGrid
          fundamentals={fundamentals ?? null}
          snapshot={snapshot ?? null}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          technicals={technicalsData as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          shareStats={shareStatsData as any}
          dividends={dividendsData}
        />

        {/* Block 2: IncomeStatementTable — Annual/Quarterly toggle via p chord */}
        <IncomeStatementTable
          instrumentId={instrumentId}
          periodType={periodType}
          onPeriodToggle={togglePeriod}
        />

        {/* Block 3: EarningsBarChart — 64px height, EPS surprise chip */}
        <EarningsBarChart instrumentId={instrumentId} />

        {/* Block 4: PeerComparisonTable — 5 peers + self */}
        <PeerComparisonTable
          fundamentals={fundamentals ?? null}
          peersData={peersData}
          isLoading={sidebarLoading && !peersData}
        />

        {/* Block 5: InsiderTransactionsTable */}
        <InsiderTransactionsTable
          insiderData={insiderData}
          ticker={instrument?.ticker ?? fundamentals?.ticker ?? ""}
        />

        {/* Block 6: InstitutionalHoldersTable */}
        <InstitutionalHoldersTable institutionalData={institutionalData} />

        {/* Block 7: FundHoldersTable */}
        <FundHoldersTable fundHoldersData={fundHoldersData} />
      </div>

      {/* ── Right column — fixed 240px sidebar ─────────────────────────── */}
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
  );
}
