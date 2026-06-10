/**
 * components/instrument/financials/statements/StatementMiniTable.tsx
 * One compact statement table (Income / Balance Sheet / Cash Flow) with a
 * YoY delta column (Round-2 Enhancement, item 2).
 *
 * WHY A TABLE (not KPI cards): the scope mandates compact tables — analysts
 * compare line items vertically (Revenue → Gross Profit → Net Income margins
 * stack) which cards break apart. Rows are 20px (`data-table-grid` default),
 * matching IncomeStatementTable directly above this panel.
 *
 * WHY PRESENTATIONAL (data via props): the YoY/TTM derivation lives in
 * statementData.ts (pure, unit-tested) and the fetch/caching lives in
 * FinancialStatementsPanel. This component just renders a StatementView,
 * which makes the colour-coding + null-handling trivially testable.
 *
 * COLUMNS: ITEM | <current period> | <year-ago period> | YOY Δ
 *   - values: font-mono tabular-nums (ADR-F-15), compact currency ($394.3B)
 *   - YoY: signed percent, text-positive / text-negative; "—" when the base
 *     is missing or ≤0 (see statementData.yoy for the suppression rationale)
 *
 * WHO USES IT: FinancialStatementsPanel (×3 — one per statement).
 */

// WHY no "use client": pure render from props — no hooks, no browser APIs.

import { formatMarketCap, formatPercentDirect } from "@/lib/utils";
import type { StatementView } from "./statementData";

// ── Props ────────────────────────────────────────────────────────────────────

export interface StatementMiniTableProps {
  /** Section caption, e.g. "INCOME STATEMENT". Rendered uppercase mono. */
  readonly title: string;
  /** Derived view from buildStatementView. Null → caller should not render
   *  this table at all (panel-level empty state handles it). */
  readonly view: StatementView;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * fmtValue — compact currency for statement magnitudes ($394.3B, -$11.2B).
 * WHY formatMarketCap: statement lines share the magnitude-abbreviation needs
 * of market cap (B/T suffixes); reusing it keeps formats consistent with the
 * IncomeStatementTable cells directly above. Null → "—".
 */
function fmtValue(v: number | null): string {
  return formatMarketCap(v);
}

/**
 * deltaClass — colour token for the YoY cell.
 * WHY semantic tokens (text-positive / text-negative): raw palette classes are
 * banned (no-off-palette-colors rule) — these resolve through the Terminal
 * Dark CSS variables. Zero delta stays default (a 0.0% YoY is information,
 * not a direction).
 */
function deltaClass(yoyPct: number | null): string {
  if (yoyPct == null || yoyPct === 0) return "text-muted-foreground/60";
  return yoyPct > 0 ? "text-positive" : "text-negative";
}

// ── Component ────────────────────────────────────────────────────────────────

export function StatementMiniTable({ title, view }: StatementMiniTableProps) {
  return (
    <div data-table-grid className="min-w-0">
      {/* Section caption — same 10px uppercase mono convention as the
          IncomeStatementTable header so the statements block reads as one
          family of tables. */}
      <div className="flex h-6 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          {title}
        </span>
      </div>

      <table
        className="w-full text-[11px] font-mono"
        role="table"
        aria-label={title}
      >
        <thead>
          <tr>
            {/* Empty first header cell — the row labels column. */}
            <th scope="col" className="py-1 px-2 text-left text-[10px] font-normal" />
            <th
              scope="col"
              className="py-1 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal tabular-nums whitespace-nowrap"
            >
              {view.currentLabel}
            </th>
            <th
              scope="col"
              className="py-1 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal tabular-nums whitespace-nowrap"
            >
              {view.priorLabel}
            </th>
            <th
              scope="col"
              className="py-1 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal whitespace-nowrap"
            >
              YOY Δ
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {view.rows.map((row) => (
            <tr key={row.label} className="hover:bg-muted/20 transition-colors">
              {/* Line-item label — muted, uppercase, never wraps (compact). */}
              <td className="py-1 px-2 text-[10px] uppercase tracking-[0.06em] text-muted-foreground whitespace-nowrap">
                {row.label}
              </td>
              {/* Current period — dimmed when null so "—" reads as absence. */}
              <td
                className={`py-1 px-2 text-right tabular-nums whitespace-nowrap ${
                  row.current == null ? "text-muted-foreground/40" : "text-foreground"
                }`}
              >
                {fmtValue(row.current)}
              </td>
              {/* Year-ago period — slightly muted vs current: the eye should
                  land on the latest figure first. */}
              <td
                className={`py-1 px-2 text-right tabular-nums whitespace-nowrap ${
                  row.prior == null ? "text-muted-foreground/40" : "text-foreground/70"
                }`}
              >
                {fmtValue(row.prior)}
              </td>
              {/* YoY delta — signed percent, colour-coded by direction.
                  yoyPct is a decimal (0.12) so multiply for the *Direct
                  formatter which expects already-percent input. */}
              <td
                className={`py-1 px-2 text-right tabular-nums whitespace-nowrap ${deltaClass(row.yoyPct)}`}
              >
                {row.yoyPct == null ? "—" : formatPercentDirect(row.yoyPct * 100, 1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
