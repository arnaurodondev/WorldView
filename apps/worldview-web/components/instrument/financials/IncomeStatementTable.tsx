/**
 * components/instrument/financials/IncomeStatementTable.tsx — P&L table (T-10)
 *
 * WHY THIS EXISTS (PLAN-0090 T-C-02 + PLAN-0089 W3 T-10): Finviz-style P&L
 * block showing the last 4–8 fiscal periods side-by-side. The `p`/`P` chord
 * (Δ12) toggles between Annual (5 cols) and Quarterly (8 cols). Analysts use
 * the quarterly view to see earnings momentum between fiscal years.
 *
 * WHY 4 FY COLUMNS (annual): enough to see a trend; 6 would wrap the 1fr
 * left column at 11px monospace. WHY 8 QTR COLUMNS: 2 years of quarterly
 * data lets analysts see seasonal patterns (Apple's Q1 peak).
 *
 * WHY Sparkline column at right edge (Δ3): revenue trend sparkline gives a
 * "trajectory at a glance" so analysts scanning quickly can see slope without
 * reading individual numbers. Uses F1 Sparkline primitive (no fork).
 *
 * DATA: S9 GET /v1/fundamentals/{id}/income-statement → ANNUAL + QUARTERLY records.
 * DESIGN: PRD-0088 §6.8, PLAN-0090 §T-C-02, PLAN-0089 W3 T-10.
 */

"use client";
// WHY "use client": useQuery + useState (period toggle) require browser runtime.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/primitives/Sparkline";
import { formatMarketCap, formatPrice } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface IncomeStatementTableProps {
  instrumentId: string;
  // WHY controlled prop (not local state): the parent FinancialsTab owns the
  // `p` chord handler. Receiving periodType + onPeriodToggle as props keeps
  // this component purely controlled — easier to test and reuse.
  periodType?: "ANNUAL" | "QUARTERLY";
  onPeriodToggle?: () => void;
}

// ── Data shapes ───────────────────────────────────────────────────────────────

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

// ── Row config ────────────────────────────────────────────────────────────────

const ROWS = [
  { key: "revenue",      label: "Revenue" },
  { key: "gross_profit", label: "Gross Profit" },
  { key: "ebit",         label: "EBIT" },
  { key: "net_income",   label: "Net Income" },
  { key: "eps",          label: "EPS" },
] as const;
type RowKey = typeof ROWS[number]["key"];

// ── Helpers ───────────────────────────────────────────────────────────────────

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
  try {
    const d = new Date(dateStr + "T00:00:00Z");
    const year = String(d.getUTCFullYear()).slice(2);
    if (!quarterly) return `FY${year}`;
    // WHY quarter from month: EODHD period_end dates are the fiscal quarter end.
    // Q1=Jan-Mar (month 3), Q2=Apr-Jun (month 6), Q3=Jul-Sep (month 9), Q4=Oct-Dec (month 12).
    const month = d.getUTCMonth() + 1;
    const q = month <= 3 ? 1 : month <= 6 ? 2 : month <= 9 ? 3 : 4;
    return `Q${q}'${year}`;
  } catch {
    return dateStr.slice(0, 4);
  }
}

function formatCell(v: number | null, key: RowKey): string {
  if (v == null) return "—";
  return key === "eps" ? formatPrice(v) : formatMarketCap(v);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IncomeStatementTable({
  instrumentId,
  periodType = "ANNUAL",
  onPeriodToggle,
}: IncomeStatementTableProps) {
  const { accessToken } = useAuth();
  const isQuarterly = periodType === "QUARTERLY";

  const { data, isLoading } = useQuery({
    queryKey: ["income-statement", instrumentId],
    queryFn: () => createGateway(accessToken).getIncomeStatement(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  // WHY filter by period_type: the endpoint returns both ANNUAL and QUARTERLY
  // records. We show only the selected period. Quarterly view shows last 8 quarters.
  const cols = (data?.records ?? [])
    .filter((r) => r.period_type === (isQuarterly ? "QUARTERLY" : "ANNUAL"))
    .sort((a, b) => a.period_end.localeCompare(b.period_end))
    .slice(isQuarterly ? -8 : -4);

  if (isLoading) return <Skeleton className="h-[140px] rounded-[2px]" />;

  if (cols.length === 0) {
    return (
      <div className="text-[11px] text-muted-foreground px-2 py-2 font-mono">
        Income statement not available.
      </div>
    );
  }

  return (
    // WHY data-table-grid (default 20px): income table rows are 20px, not 18px
    // (dense variant is reserved for DenseMetricsGrid only per Δ5).
    <div data-table-grid className="w-full">
      {/* Section header with period toggle */}
      <div className="flex h-6 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          INCOME STATEMENT
        </span>
        <button
          onClick={onPeriodToggle}
          className="text-[9px] font-mono text-primary hover:text-primary/80 transition-colors"
          aria-label={`Switch to ${isQuarterly ? "annual" : "quarterly"} view (p)`}
          title="Toggle Annual / Quarterly (p)"
        >
          {isQuarterly ? "ANNUAL" : "QUARTERLY"} ↔
        </button>
      </div>

      <table className="w-full text-[11px] font-mono" role="table" aria-label={`${isQuarterly ? "Quarterly" : "Annual"} income statement`}>
        <thead>
          <tr>
            <th scope="col" className="py-1 px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal min-w-[80px]" />
            {cols.map((r) => (
              <th key={r.id} scope="col" className="py-1 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono font-normal tabular-nums whitespace-nowrap">
                {formatFY(r.period_end, isQuarterly)}
              </th>
            ))}
            {/* WHY Sparkline header: signals to the analyst that the last column
                is a trend sparkline, not a period label. */}
            <th scope="col" className="py-1 px-2 text-right text-[10px] text-muted-foreground font-normal">
              <span className="sr-only">Trend</span>
              <span aria-hidden>↗</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/30">
          {ROWS.map((row) => {
            // Extract values for this row across all columns (for the sparkline).
            const values = cols.map((r) => extractValue(r.data as IncomeStatementData, row.key));
            // WHY filter nulls for sparkline: Sparkline expects a dense array.
            const sparkValues = values.filter((v): v is number => v != null);

            return (
              <tr key={row.key} className="hover:bg-muted/20 transition-colors">
                <td className="py-1 px-2 text-[10px] uppercase tracking-[0.06em] text-muted-foreground whitespace-nowrap">
                  {row.label}
                </td>
                {cols.map((r) => {
                  const v = extractValue(r.data as IncomeStatementData, row.key);
                  const color = row.key === "net_income" && v != null
                    ? v >= 0 ? "text-positive" : "text-negative"
                    : "text-foreground";
                  return (
                    <td key={r.id} className={`py-1 px-2 text-right tabular-nums whitespace-nowrap ${v == null ? "text-muted-foreground/40" : color}`}>
                      {formatCell(v, row.key)}
                    </td>
                  );
                })}
                {/* WHY F1 Sparkline (not an inline SVG): the F1 Sparkline primitive
                    owns the color-trend logic and zero-line handling. Using it here
                    keeps the Income table consistent with the BeatMissHistoryPanel. */}
                <td className="py-1 px-2 text-right">
                  {sparkValues.length >= 2 ? (
                    <Sparkline data={sparkValues} width={40} height={12} trend="auto" />
                  ) : (
                    <span className="text-muted-foreground/30">—</span>
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
