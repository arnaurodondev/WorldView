/**
 * components/instrument/financials/statements/StatementsSection.tsx
 * Financial statements block — Income / Balance Sheet / Cash Flow proper
 * compact tables with an ANNUAL / QUARTERLY / TTM toggle.
 * (Wave-2 Financials redesign, scope items 1 + 2.)
 *
 * REPLACES (and why):
 *   - IncomeStatementTable — the old tab rendered the income statement TWICE
 *     (a standalone multi-period P&L panel AND a 2-column mini-table inside
 *     FinancialStatementsPanel). One statements section, one income table.
 *   - FinancialStatementsPanel + StatementMiniTable — the "mini" 2-column
 *     view is upgraded to real multi-period tables (up to 5 FYs / 8
 *     quarters as columns, shared per-table unit, sparklines). The Round-2
 *     window semantics (strict TTM sums, MRQ balance snapshots, honest
 *     "4Q TO" captions) are preserved in statementData.ts.
 *
 * MODES (segmented control + `p` chord):
 *   ANNUAL    — up to 5 fiscal years (default: filed FY figures are the
 *               canonical reference).
 *   QUARTERLY — last 8 quarters (earnings-momentum view; the old standalone
 *               income table's quarterly mode, now for all 3 statements).
 *   TTM       — trailing-twelve-months vs prior TTM (the freshness view
 *               valuation work actually uses: P/E = price / TTM earnings).
 *
 * WHY THE `p` CHORD LIVES HERE (moved out of FinancialsTab): the chord's
 * only effect is this section's mode — co-locating handler and state kills
 * the prop-drilled periodType/onPeriodToggle pair. `p` cycles
 * ANNUAL → QUARTERLY → TTM → ANNUAL (it used to flip a 2-state toggle;
 * cycling is the natural 3-state generalisation). `q` stays owned by
 * InstrumentTabs for Quote-tab navigation.
 *
 * DATA SOURCE: useStatementRecords — financials-bundle leg first (zero
 * extra round-trips), Wave-1 dedicated endpoints as the fallback when the
 * bundle cannot answer. See that hook for the honesty fix this enables.
 *
 * WHO USES IT: FinancialsTab (left column, directly under DenseMetricsGrid).
 */

"use client";
// WHY "use client": useState (mode) + useEffect (chord) + the records hook.

import { useEffect, useMemo, useState } from "react";
import { FileSpreadsheet } from "lucide-react";

import { EmptyState } from "@/components/primitives/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { PanelHeader } from "../PanelHeader";
import { StatementTable } from "./StatementTable";
import { buildStatementTable, type StatementMode } from "./statementData";
import { useStatementRecords } from "./useStatementRecords";

// ── Props ────────────────────────────────────────────────────────────────────

export interface StatementsSectionProps {
  /** S3 instrument_id — keys the records fetch. Empty string disables it. */
  readonly instrumentId: string;
}

// Chord cycle order — matches the visual left-to-right trigger order so the
// keyboard path and the pointer path traverse the modes identically.
const MODE_CYCLE: readonly StatementMode[] = ["ANNUAL", "QUARTERLY", "TTM"];

// ── Component ────────────────────────────────────────────────────────────────

export function StatementsSection({ instrumentId }: StatementsSectionProps) {
  // Local state (not URL): a transient UI preference, same rationale as the
  // old FinancialsTab toggle this replaces.
  const [mode, setMode] = useState<StatementMode>("ANNUAL");

  // `p` chord — cycle modes while the Financials tab is mounted. Skipped
  // when focus sits in an input/textarea/contentEditable (typing "p" in the
  // chat box must not flip the statements).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const inInput =
        target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
      if (inInput) return;
      if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        setMode((prev) => MODE_CYCLE[(MODE_CYCLE.indexOf(prev) + 1) % MODE_CYCLE.length]);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const { records, isLoading, isError, refetch } = useStatementRecords(instrumentId);

  // Memoised derivation: the AAPL all-sections leg carries ~470 statement
  // records; each buildStatementTable call filters + sorts + window-sums
  // that array. The views only change when the records identity or the mode
  // changes — not on every parent re-render (FinancialsTab re-renders on
  // each of its query updates).
  const { income, balance, cashFlow } = useMemo(
    () => ({
      income: buildStatementTable(records ?? undefined, "income_statement", mode),
      balance: buildStatementTable(records ?? undefined, "balance_sheet", mode),
      cashFlow: buildStatementTable(records ?? undefined, "cash_flow", mode),
    }),
    [records, mode],
  );
  const hasAny = !!(income || balance || cashFlow);

  // ── Loading: cold first fetch only (warm cache paints instantly). Shape-
  // matched skeleton per DESIGN_SYSTEM §6.2 — three stacked table blocks
  // (caption bar + 6 row bars each) mirroring the eventual layout. ──
  if (isLoading) {
    return (
      <div
        role="status"
        aria-label="Loading financial statements"
        data-testid="statements-skeleton"
        className="space-y-3 border-t border-border px-2 py-2"
      >
        {[0, 1, 2].map((table) => (
          <div key={table} aria-hidden className="space-y-1.5">
            <Skeleton className="h-5 w-2/5 rounded-[2px]" />
            {[0, 1, 2, 3, 4, 5].map((row) => (
              <Skeleton key={row} className="h-4 w-full rounded-[1px]" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="border-t border-border/40">
      {/* Section header: caption + 3-mode segmented control. WHY controlled
          Tabs: one mode drives all three tables in lock-step. h-5 triggers
          keep the control inside the 24px header band. */}
      <PanelHeader label="FINANCIAL STATEMENTS" meta="p cycles period">
        <Tabs value={mode} onValueChange={(v) => setMode(v as StatementMode)}>
          <TabsList className="h-5 p-0.5">
            {MODE_CYCLE.map((m) => (
              <TabsTrigger
                key={m}
                value={m}
                className="h-4 px-2 font-mono text-[9px] uppercase tracking-wider"
              >
                {m === "QUARTERLY" ? "Quarterly" : m === "ANNUAL" ? "Annual" : "TTM"}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </PanelHeader>

      {/* ── Error: bundle AND dedicated endpoints all failed. Distinct from
          the empty state — a failed FETCH must never claim the instrument
          "has no statements" (Round-4 honesty rule, kept). ── */}
      {isError ? (
        <div
          data-testid="statements-fetch-error"
          className="flex flex-col items-center justify-center gap-1 px-3 py-4 text-center"
        >
          <p className="text-[12px] text-foreground">Couldn&apos;t load financial statements</p>
          <p className="text-[11px] text-muted-foreground">
            Both the financials bundle and the statement endpoints failed — the rest of the tab is
            unaffected.
          </p>
          <button
            type="button"
            onClick={refetch}
            className="mt-1 rounded-[2px] font-mono text-[9px] uppercase tracking-wider text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            Retry
          </button>
        </div>
      ) : !hasAny ? (
        // Honest now: with the Wave-1 fallback probing the dedicated
        // endpoints, reaching this branch genuinely means "no records".
        <EmptyState
          condition="empty-no-data"
          copyKey="instrument.no-financial-statements"
          icon={FileSpreadsheet}
        />
      ) : (
        // WHY stacked (not the old 3-up grid): proper multi-period tables are
        // wide (up to 8 period columns + YoY + trend); side-by-side they'd
        // crush below readability at any realistic width. Vertical stacking
        // with the shared 22px rhythm reads like one filing.
        <div className="space-y-1 pb-2">
          {income && <StatementTable title="INCOME STATEMENT" view={income} />}
          {balance && <StatementTable title="BALANCE SHEET" view={balance} />}
          {cashFlow && <StatementTable title="CASH FLOW" view={cashFlow} />}
        </div>
      )}
    </div>
  );
}
