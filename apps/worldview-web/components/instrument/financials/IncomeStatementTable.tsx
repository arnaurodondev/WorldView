/**
 * components/instrument/financials/IncomeStatementTable.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-C-02 / W3-T-10): Finviz-style P&L block showing
 * annual or quarterly fiscal periods side-by-side. The periodType prop (wired
 * to the parent's `p` chord toggle) lets analysts flip between the 5-year
 * annual trend and the 8-quarter trailing view without any tab navigation.
 *
 * WHY BOTH PERIODS FROM ONE ENDPOINT: S3 /income-statement returns all
 * period_type records. Filtering client-side avoids a second fetch and lets
 * TanStack Query serve quarterly from the same cache entry as annual.
 *
 * WHY SPARKLINE TREND COLUMN: The rightmost column is a 40×12px trend line
 * summarising each metric's multi-period trajectory. Analysts can scan the
 * column to see "all rows trending up" (company growing) or mixed signals
 * before reading individual values. Uses the F1 Sparkline primitive.
 *
 * WHO USES IT: FinancialsTab.tsx — Block 2 of the left column.
 * DATA SOURCES: S9 GET /v1/fundamentals/{id}/income-statement (all period types).
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.2
 */

"use client";
// WHY "use client": useQuery + useAuth require client-side React context.

import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/primitives/Sparkline";
import { formatMarketCap, formatPrice } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface IncomeStatementTableProps {
  instrumentId: string;
  /** Controlled by FinancialsTab's `p` chord toggle. Defaults to ANNUAL. */
  periodType?: "ANNUAL" | "QUARTERLY";
}

// WHY typed (not Record<string, unknown>): records.data is JSONB; typing the
// cast prevents typos from silently rendering "—" in every cell.
interface IncomeStatementData {
  totalRevenue?: number | string | null;
  grossProfit?: number | string | null;
  operatingIncome?: number | string | null;
  netIncome?: number | string | null;
  eps?: number | string | null;
  total_revenue?: number | string | null;
  gross_profit?: number | string | null;
  operating_income?: number | string | null;
  net_income?: number | string | null;
}

const ROWS = [
  { key: "revenue",      label: "Revenue" },
  { key: "gross_profit", label: "Gross Profit" },
  { key: "ebit",         label: "EBIT" },
  { key: "net_income",   label: "Net Income" },
  { key: "eps",          label: "EPS" },
] as const;
type RowKey = typeof ROWS[number]["key"];

function safeNum(v: unknown): number | null {
  if (v == null || v === "" || v === "None") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function extractValue(data: IncomeStatementData, key: RowKey): number | null {
  switch (key) {
    case "revenue":      return safeNum(data.totalRevenue    ?? data.total_revenue);
    case "gross_profit": return safeNum(data.grossProfit     ?? data.gross_profit);
    case "ebit":         return safeNum(data.operatingIncome ?? data.operating_income);
    case "net_income":   return safeNum(data.netIncome       ?? data.net_income);
    case "eps":          return safeNum(data.eps);
  }
}

function formatFY(dateStr: string, quarterly: boolean): string {
  // WHY UTC parse: avoids off-by-one-day in western timezones at midnight UTC.
  // WHY slice before "T": S3's Pydantic datetime serialiser emits full ISO
  // strings like "2024-09-30T00:00:00".  Appending "T00:00:00Z" to such a
  // string produces "2024-09-30T00:00:00T00:00:00Z" — an invalid date that
  // new Date() silently accepts as Invalid Date (no throw), causing
  // getUTCFullYear() → NaN → String(NaN).slice(2) → "N" → "FYN".
  // Stripping any existing time component before appending fixes the bug for
  // both date-only strings ("2024-09-30") and full datetime strings.
  const datePart = dateStr.split("T")[0] ?? dateStr;
  try {
    const d = new Date(datePart + "T00:00:00Z");
    if (quarterly) {
      // WHY Q1-Q4 mapping: quarters end March/June/September/December per EODHD.
      const m = d.getUTCMonth(); // 0-indexed
      const q = m <= 2 ? "Q1" : m <= 5 ? "Q2" : m <= 8 ? "Q3" : "Q4";
      return `${q}'${String(d.getUTCFullYear()).slice(2)}`;
    }
    return `FY${String(d.getUTCFullYear()).slice(2)}`;
  } catch {
    return datePart.slice(0, 4);
  }
}

function formatCell(v: number | null, key: RowKey): string {
  if (v == null) return "—";
  // WHY formatPrice for EPS: EPS is a per-share currency value, not a
  // magnitude — formatMarketCap ($4.89B) would be wrong for a $2.34 EPS.
  return key === "eps" ? formatPrice(v) : formatMarketCap(v);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IncomeStatementTable({
  instrumentId,
  periodType = "ANNUAL",
}: IncomeStatementTableProps) {
  const gateway = useApiClient();
  const isQuarterly = periodType === "QUARTERLY";

  // WHY staleTime 24h: annual P&L changes only on 10-K filings; quarterly on
  // earnings calls. 24h refresh is safe and matches useFinancialsTabData policy.
  const { data, isLoading } = useQuery({
    queryKey: ["income-statement", instrumentId],
    queryFn: () => gateway.getIncomeStatement(instrumentId),
    enabled: !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  // WHY filter then sort then slice: S3 returns mixed period_types.
  // Annual: 5 most recent fiscal years (newest rightmost = L-to-R timeline).
  // Quarterly: 8 most recent quarters.
  const cols = (data?.records ?? [])
    .filter((r) => r.period_type === (isQuarterly ? "QUARTERLY" : "ANNUAL"))
    .sort((a, b) => a.period_end.localeCompare(b.period_end))
    .slice(isQuarterly ? -8 : -5);

  if (isLoading) return <Skeleton className="h-[140px] rounded-none" />;
  if (cols.length === 0) {
    return (
      <div className="text-[11px] text-muted-foreground px-2 py-2">
        Income statement not available.
      </div>
    );
  }

  return (
    // WHY data-table-grid (not dense): income statement rows use the default
    // 20px row height — they are NOT part of the 6-col DenseMetricsGrid.
    // Only the snapshot grid above uses data-table-grid="dense".
    <div data-table-grid className="border-t border-border">
      {/* Section header: shows which period mode is active */}
      <div className="flex items-center justify-between h-[var(--row-h,20px)] px-2 border-b border-border bg-muted/20">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70">
          INCOME STATEMENT — {isQuarterly ? "QUARTERLY" : "ANNUAL"}
        </span>
        <span className="text-[9px] text-muted-foreground/40">[p] toggle</span>
      </div>

      <table
        className="w-full text-[11px] font-mono"
        role="table"
        aria-label={`${isQuarterly ? "Quarterly" : "Annual"} income statement`}
      >
        <thead>
          <tr>
            {/* Row label column — min-w keeps "Gross Profit" un-truncated. */}
            <th
              scope="col"
              className="py-0 px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal min-w-[80px]"
            />
            {cols.map((r) => (
              <th
                key={r.id}
                scope="col"
                className="py-0 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono font-normal tabular-nums whitespace-nowrap"
              >
                {formatFY(r.period_end, isQuarterly)}
              </th>
            ))}
            {/* WHY trend header: documents the Sparkline column without polluting
                the value columns with a Δ or % annotation. */}
            <th
              scope="col"
              className="py-0 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground/40 font-normal"
            >
              trend
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {ROWS.map((row) => {
            // Collect values across all columns for the Sparkline trend line.
            const rowValues = cols
              .map((r) => extractValue(r.data as IncomeStatementData, row.key))
              .filter((v): v is number => v !== null);

            return (
              <tr key={row.key} className="hover:bg-muted/20 transition-colors">
                <td className="py-0 px-2 text-[10px] uppercase tracking-[0.06em] text-muted-foreground whitespace-nowrap h-[var(--row-h,20px)]">
                  {row.label}
                </td>
                {cols.map((r) => {
                  const v = extractValue(r.data as IncomeStatementData, row.key);
                  const color =
                    row.key === "net_income" && v != null
                      ? v >= 0
                        ? "text-positive"
                        : "text-negative"
                      : "text-foreground";
                  return (
                    <td
                      key={r.id}
                      className={`py-0 px-2 text-right tabular-nums whitespace-nowrap ${v == null ? "text-muted-foreground/40" : color}`}
                    >
                      {formatCell(v, row.key)}
                    </td>
                  );
                })}
                {/* WHY F1 Sparkline (not recharts): keeps bundle size down and
                    matches the primitive used across the platform (Peers strip,
                    Beat/Miss history sidebar). trend="auto" derives sign from
                    first-to-last comparison. */}
                <td className="py-0 px-2 text-right">
                  {rowValues.length >= 2 ? (
                    <Sparkline
                      data={rowValues}
                      width={40}
                      height={12}
                      trend="auto"
                      label={`${row.label} trend`}
                    />
                  ) : (
                    <span className="text-muted-foreground/30 text-[9px]">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
