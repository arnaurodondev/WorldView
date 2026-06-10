/**
 * components/instrument/financials/statements/FinancialStatementsPanel.tsx
 * Financial statements block — Income / Balance Sheet / Cash Flow mini-tables
 * with an Annual / TTM toggle (Round-2 Enhancement, item 2).
 *
 * WHY THIS EXISTS: the Financials tab showed a multi-period income statement
 * (IncomeStatementTable) but NO balance sheet and NO cash flow — even though
 * S3 ingests both (verified live: 163 quarterly balance_sheet + 146 quarterly
 * cash_flow records for AAPL inside the all-sections fundamentals payload).
 * This panel surfaces all three statements as compact YoY tables.
 *
 * DATA SOURCE — ZERO new endpoints, ZERO extra round-trips:
 *   The financials-bundle composite (POST /v1/fundamentals/{id}/financials-
 *   bundle) already carries the RAW all-sections payload in its `fundamentals`
 *   leg ({security_id, records:[{section, period_type, period_end, data}]}).
 *   `useFinancialsBundle` is the existing owner of that fetch — calling it
 *   here DEDUPES against the call in useFinancialsTabData (same query key,
 *   same render tree), so this panel reads the same single HTTP response the
 *   tab already pays for. Tab-switching stays refetch-free (bundle staleTime
 *   10 min + refetchOnWindowFocus disabled).
 *
 * WHY Annual / TTM (not Annual / Quarterly): the scope asks for TTM, and TTM
 * is what valuation work actually uses (P/E = price / TTM EPS). The TTM rows
 * are sums of the last 4 REAL quarterly records (flows) or the MRQ snapshot
 * (balance sheet) — standard accounting derivation, never extrapolation. See
 * statementData.ts for the exact per-mode semantics and the strict
 * all-4-quarters-required rule.
 *
 * WHY shadcn Tabs for the toggle: the scope allows Tabs or ToggleGroup;
 * components/ui has no toggle-group primitive, and Tabs is already themed for
 * the Terminal Dark palette. A two-trigger TabsList is the segmented control.
 *
 * WHO USES IT: FinancialsTab (left column, after IncomeStatementTable).
 */

"use client";
// WHY "use client": useState (mode toggle) + the TanStack bundle hook.

import { useState } from "react";
import { FileSpreadsheet } from "lucide-react";

import { useFinancialsBundle } from "@/components/instrument/hooks/useFinancialsBundle";
import { EmptyState } from "@/components/instrument/shared/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { FundamentalsSectionResponse } from "@/types/api";

import { StatementMiniTable } from "./StatementMiniTable";
import { buildStatementView, type StatementMode } from "./statementData";

// ── Props ────────────────────────────────────────────────────────────────────

export interface FinancialStatementsPanelProps {
  /** S3 instrument_id — keys the (deduped) financials-bundle query. */
  readonly instrumentId: string;
}

// ── Component ────────────────────────────────────────────────────────────────

export function FinancialStatementsPanel({ instrumentId }: FinancialStatementsPanelProps) {
  // Annual default: filed FY figures are the canonical reference; TTM is the
  // freshness view an analyst opts into. Local state (not URL) — a transient
  // UI preference, same rationale as FinancialsTab's ANNUAL/QUARTERLY toggle.
  const [mode, setMode] = useState<StatementMode>("ANNUAL");

  // Deduped against useFinancialsTabData's identical call (same query key) —
  // no second HTTP request is issued by mounting this panel.
  const bundleQuery = useFinancialsBundle(instrumentId);

  // The bundle leg is typed `unknown` (generated types not re-rolled yet);
  // the runtime shape is the S3 all-sections FundamentalsResponse — same
  // contract the per-section endpoints use. Null leg = downstream failure.
  const sections = (bundleQuery.data?.fundamentals ?? null) as FundamentalsSectionResponse | null;
  const records = sections?.records;

  const income = buildStatementView(records, "income_statement", mode);
  const balance = buildStatementView(records, "balance_sheet", mode);
  const cashFlow = buildStatementView(records, "cash_flow", mode);
  const hasAny = !!(income || balance || cashFlow);

  // ── Loading: only on the bundle's cold first fetch (cache-warm renders skip
  // this entirely — tab switches paint instantly from the shared cache). ──
  if (bundleQuery.isLoading) {
    return <Skeleton className="mx-2 my-2 h-[180px] rounded-[2px]" data-testid="statements-skeleton" />;
  }

  return (
    <div className="border-t border-border/40">
      {/* ── Header row: caption + Annual/TTM toggle ─────────────────────── */}
      <div className="flex h-7 items-center justify-between px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          FINANCIAL STATEMENTS
        </span>

        {/* WHY controlled Tabs: the mode drives all three tables at once —
            a single source of truth here keeps them in lock-step. h-5
            triggers keep the control inside the 28px header band. */}
        <Tabs value={mode} onValueChange={(v) => setMode(v as StatementMode)}>
          <TabsList className="h-5 p-0.5">
            <TabsTrigger
              value="ANNUAL"
              className="h-4 px-2 text-[9px] font-mono uppercase tracking-wider"
            >
              Annual
            </TabsTrigger>
            <TabsTrigger
              value="TTM"
              className="h-4 px-2 text-[9px] font-mono uppercase tracking-wider"
            >
              TTM
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* ── Empty: section records absent (bundle leg failed OR instrument has
          no ingested statements, e.g. ETFs). Named state per Round-1 rule. ── */}
      {!hasAny ? (
        <EmptyState
          icon={FileSpreadsheet}
          headline="No financial statements"
          hint="Statement records have not been ingested for this instrument — ETFs and newly listed tickers have none until the fundamentals backfill runs."
          variant="inline"
          className="px-2 pb-2"
        />
      ) : (
        // WHY a responsive 3-up grid: at full width the three statements sit
        // side-by-side (one glance covers P&L + balance + cash); below ~1280px
        // they stack so the 4 numeric columns never crush below readability.
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 px-0 pb-2 xl:grid-cols-3">
          {income && <StatementMiniTable title="INCOME STATEMENT" view={income} />}
          {balance && <StatementMiniTable title="BALANCE SHEET" view={balance} />}
          {cashFlow && <StatementMiniTable title="CASH FLOW" view={cashFlow} />}
        </div>
      )}
    </div>
  );
}
