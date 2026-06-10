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

import { useMemo, useState } from "react";
import { FileSpreadsheet } from "lucide-react";

import { useFinancialsBundle } from "@/components/instrument/hooks/useFinancialsBundle";
// Round-3 consolidation (DS §15.12): shared primitive + registry copy key
// replace the local components/instrument/shared/EmptyState.tsx fork.
import { EmptyState } from "@/components/primitives/EmptyState";
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

  // Round-4 hardening (item 3b): memoise the three derivations. AAPL's
  // all-sections leg carries ~470 records; each buildStatementView call
  // filters + sorts + TTM-sums that array, so re-deriving on EVERY parent
  // re-render (FinancialsTab re-renders on each of its 6+ query updates)
  // was ~3 full passes per render for identical inputs. The views only
  // change when the records array identity or the Annual/TTM mode changes.
  const { income, balance, cashFlow } = useMemo(
    () => ({
      income: buildStatementView(records, "income_statement", mode),
      balance: buildStatementView(records, "balance_sheet", mode),
      cashFlow: buildStatementView(records, "cash_flow", mode),
    }),
    [records, mode],
  );
  const hasAny = !!(income || balance || cashFlow);

  // ── Loading: only on the bundle's cold first fetch (cache-warm renders skip
  // this entirely — tab switches paint instantly from the shared cache).
  // Round-3 item 4: shape-matched skeleton — a 3-up grid of ROW bars (caption
  // bar + 5 row bars per statement) mirroring the eventual mini-table layout,
  // instead of the previous single flat 180px rectangle. Same xl:grid-cols-3
  // breakpoint as the real grid → zero layout shift on load. ──
  if (bundleQuery.isLoading) {
    return (
      <div
        role="status"
        aria-label="Loading financial statements"
        data-testid="statements-skeleton"
        className="grid grid-cols-1 gap-x-4 gap-y-2 px-2 py-2 xl:grid-cols-3"
      >
        {[0, 1, 2].map((table) => (
          <div key={table} aria-hidden className="space-y-1.5">
            {/* Caption bar — matches the h-6 mini-table header band. */}
            <Skeleton className="h-5 w-2/5 rounded-[2px]" />
            {/* Row bars — 20px rhythm matching data-table-grid rows. */}
            {[0, 1, 2, 3, 4].map((row) => (
              <Skeleton key={row} className="h-4 w-full rounded-[1px]" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="border-t border-border/40">
      {/* ── Header row: caption + Annual/TTM toggle ───────────────────────
          Round-3 item 2: uniform accent-bar header (border-l-2 border-l-primary
          + bg-muted/20) — the Round-1 DenseMetricsGrid treatment applied to
          every Financials/Intelligence block header. */}
      <div className="flex h-7 items-center justify-between border-b border-border border-l-2 border-l-primary bg-muted/20 px-2">
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

      {/* ── Error: the WHOLE bundle request failed (Round-4 item 1b). Before
          this branch, a failed bundle fell into the "no financial statements"
          empty state below — telling the analyst the instrument HAS no
          statements when the truth was a failed fetch. Distinct named error +
          Retry keeps the two states honest. Note: a failed `fundamentals` LEG
          inside a successful bundle still degrades to the empty state — the
          composite endpoint nulls failed legs and we cannot distinguish
          "leg errored" from "no records" client-side. ── */}
      {bundleQuery.isError ? (
        <div
          data-testid="statements-fetch-error"
          className="flex flex-col items-center justify-center gap-1 px-3 py-4 text-center"
        >
          <p className="text-[12px] text-foreground">Couldn&apos;t load financial statements</p>
          <p className="text-[11px] text-muted-foreground">
            The financials bundle failed to load — the rest of the tab is unaffected.
          </p>
          <button
            type="button"
            onClick={() => void bundleQuery.refetch()}
            className="mt-1 font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring rounded-[2px]"
          >
            Retry
          </button>
        </div>
      ) : !hasAny ? (
        <EmptyState
          condition="empty-no-data"
          copyKey="instrument.no-financial-statements"
          icon={FileSpreadsheet}
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
