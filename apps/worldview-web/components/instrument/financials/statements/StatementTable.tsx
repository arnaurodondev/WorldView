/**
 * components/instrument/financials/statements/StatementTable.tsx
 * One proper compact statement table (Income / Balance Sheet / Cash Flow)
 * with multi-period columns, a YoY delta column and trend microcharts.
 * (Wave-2 Financials redesign, scope items 2 + 3.)
 *
 * REPLACES: StatementMiniTable (2 columns, per-cell "$394.3B" formatting)
 * AND the standalone IncomeStatementTable (which duplicated the income
 * statement directly above the mini-tables — one of the "orphan panel"
 * sloppiness sources this redesign kills).
 *
 * COLUMNS: ITEM | <period 1 … period N> | YOY Δ | TREND
 *   - period values: right-aligned mono tabular-nums, scaled by the table's
 *     SHARED unit (header shows e.g. "USD B" once — 10-K convention "in
 *     millions, except…") instead of repeating the magnitude suffix in
 *     every cell;
 *   - YoY Δ: signed percent, text-positive / text-negative; "—" when the
 *     base is missing or ≤0 (see statementData.yoy for the suppression
 *     rationale);
 *   - TREND: 48×14 quarterly sparkline (F1 Sparkline primitive — owns the
 *     trend-colour logic) on flagged rows (Revenue, Net Income, OCF, FCF).
 *
 * WHY overflow-x-auto: quarterly mode renders 8 period columns; at narrow
 * widths a real statement table scrolls horizontally rather than crushing
 * the numbers (scope item 2 — "scrollable horizontally if needed").
 *
 * WHY PRESENTATIONAL (data via props): the period/TTM derivation lives in
 * statementData.ts (pure, unit-tested) and the fetch/fallback logic in
 * useStatementRecords — this component just renders a StatementTableView,
 * keeping the colour-coding + null-handling trivially testable.
 *
 * WHO USES IT: StatementsSection (×3 — one per statement).
 */

// WHY no "use client": pure render from props — no hooks, no browser APIs.

import { Sparkline } from "@/components/primitives/Sparkline";
import { formatPercentDirect } from "@/lib/utils";
import type { StatementTableView } from "./statementData";

// ── Props ────────────────────────────────────────────────────────────────────

export interface StatementTableProps {
  /** Sub-caption, e.g. "INCOME STATEMENT". Rendered uppercase mono. */
  readonly title: string;
  /** Derived view from buildStatementTable. Null views are skipped by the
   *  caller (section-level empty state handles the all-empty case). */
  readonly view: StatementTableView;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * fmtScaled — raw value → shared-unit string ("394.3", "-11.2", "1,204.0").
 * One decimal everywhere: statement magnitudes don't need more, and a fixed
 * decimal count keeps the tabular-nums columns perfectly aligned.
 */
function fmtScaled(v: number | null, divisor: number): string {
  if (v == null) return "—";
  return (v / divisor).toLocaleString("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

/**
 * deltaClass — colour token for the YoY cell. Semantic tokens only
 * (text-positive / text-negative resolve through the Terminal Dark CSS
 * vars — raw palette classes are banned). Zero delta stays neutral: a
 * 0.0% YoY is information, not a direction.
 */
function deltaClass(yoyPct: number | null): string {
  if (yoyPct == null || yoyPct === 0) return "text-muted-foreground/60";
  return yoyPct > 0 ? "text-positive" : "text-negative";
}

// ── Component ────────────────────────────────────────────────────────────────

export function StatementTable({ title, view }: StatementTableProps) {
  return (
    <div data-table-grid className="min-w-0">
      {/* Sub-caption band — title left, SHARED unit right. h-6 keeps the
          24px rhythm of the section's panel chrome. WHY the unit lives here
          (scope item 2): one labelled unit per table; cells then render bare
          scaled numbers, which scan like a real filed statement. */}
      <div className="flex h-6 items-center justify-between border-b border-border/60 px-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          {title}
        </span>
        <span
          data-testid={`statement-unit-${title.toLowerCase().replace(/\s+/g, "-")}`}
          className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground/60"
        >
          {view.unit.label}
        </span>
      </div>

      {/* Horizontal-scroll shell: 8 quarterly columns won't fit every width;
          a real statement table scrolls sideways instead of wrapping. */}
      <div className="overflow-x-auto">
        <table className="w-full font-mono text-[11px]" role="table" aria-label={title}>
          <thead>
            <tr className="h-[22px]">
              {/* Row-label column header — empty by convention (the table's
                  aria-label + sub-caption already name the statement). */}
              <th scope="col" className="min-w-[104px] px-2 text-left text-[10px] font-normal" />
              {view.columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className="whitespace-nowrap px-2 text-right text-[10px] font-normal uppercase tracking-[0.08em] tabular-nums text-muted-foreground"
                >
                  {col.label}
                </th>
              ))}
              <th
                scope="col"
                className="whitespace-nowrap px-2 text-right text-[10px] font-normal uppercase tracking-[0.08em] text-muted-foreground"
              >
                YOY Δ
              </th>
              {/* Trend column header — glyph signals "microchart", sr-only
                  text names it for screen readers. */}
              <th scope="col" className="w-[56px] px-2 text-right text-[10px] font-normal text-muted-foreground">
                <span className="sr-only">Quarterly trend</span>
                <span aria-hidden>↗</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/30">
            {view.rows.map((row) => (
              // 22px data rows — DESIGN_SYSTEM --data-row-height (scope item 7).
              <tr key={row.label} className="h-[22px] transition-colors hover:bg-muted/20">
                {/* Line-item label — muted, uppercase, never wraps. */}
                <td className="whitespace-nowrap px-2 text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
                  {row.label}
                </td>
                {/* Period cells — latest column full-strength, earlier periods
                    slightly muted so the eye lands on the newest figure first
                    (same emphasis ramp the old mini-table used for its
                    current-vs-prior pair, generalised to N columns). */}
                {row.values.map((v, i) => {
                  const isLatest = i === row.values.length - 1;
                  const tone =
                    v == null
                      ? "text-muted-foreground/40"
                      : isLatest
                        ? "text-foreground"
                        : "text-foreground/70";
                  return (
                    <td
                      key={view.columns[i]?.key ?? i}
                      className={`whitespace-nowrap px-2 text-right tabular-nums ${tone}`}
                    >
                      {fmtScaled(v, view.unit.divisor)}
                    </td>
                  );
                })}
                {/* YoY delta — signed percent, colour-coded by direction.
                    yoyPct is a decimal (0.12) so ×100 for the *Direct
                    formatter which expects already-percent input. */}
                <td className={`whitespace-nowrap px-2 text-right tabular-nums ${deltaClass(row.yoyPct)}`}>
                  {row.yoyPct == null ? "—" : formatPercentDirect(row.yoyPct * 100, 1)}
                </td>
                {/* Quarterly trend microchart (scope item 3) — only on flagged
                    rows; em-dash placeholder keeps the column rhythm on the
                    others without implying missing data. */}
                <td className="px-2 text-right">
                  {row.spark ? (
                    <Sparkline
                      data={[...row.spark]}
                      width={48}
                      height={14}
                      trend="auto"
                      label={`${row.label} quarterly trend`}
                    />
                  ) : (
                    <span aria-hidden className="text-muted-foreground/20">
                      ·
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
