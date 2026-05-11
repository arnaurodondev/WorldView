/**
 * components/instrument/IncomeStatementFY.tsx — Finviz-style FY-column income statement
 *
 * WHY THIS EXISTS (PLAN-0088 Wave G-1):
 * The Fundamentals tab currently shows income-statement data only as TTM metrics
 * (Gross Margin %, Net Margin %, etc.) — ratios that strip the multi-year trend.
 * Analysts need to see the absolute dollar trajectory: did Revenue grow $5B each
 * year or stagnate? Did EBITDA expand or compress? This FY table (Finviz/Macrotrends
 * pattern) answers "show me the last 4 fiscal years side-by-side" in one glance.
 *
 * WHY 4 FY COLUMNS + TTM:
 * - 4 FY is enough to see a trend (2-year is too short; 6-year is too wide for 280px).
 * - TTM (trailing twelve months) is the most recent investor reference — separating
 *   it from FY prevents confusion between calendar/fiscal year boundaries.
 *
 * WHY ROWS = Revenue / Gross Profit / Op. Income / Net Income / EBITDA / EPS:
 * These 6 rows are the standard Finviz Income Statement order. Bloomberg DES "IS"
 * uses the same ordering. Together they answer: scale (Revenue), efficiency (Gross),
 * operating leverage (Op. Income), bottom line (Net Income), cash proxy (EBITDA),
 * and per-share return (EPS).
 *
 * WHY COLLAPSE ROWS WITH ALL-NULL COLUMNS (G-4 placeholder cleanup):
 * When EODHD has no data for a metric across ALL years, rendering 4 "—" cells
 * looks broken and wastes row height. We collapse those rows entirely so the table
 * only shows metrics that have at least one real value.
 *
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId}/income-statement
 *   → S3 FundamentalsSection.INCOME_STATEMENT (period_type=ANNUAL records)
 *   Each record's data dict uses EODHD PascalCase keys: totalRevenue, grossProfit,
 *   operatingIncome, netIncome, ebitda, eps.
 *
 * WHO USES IT: FundamentalsTab left column (below the metrics grid), PLAN-0088 G-1.
 * DESIGN REFERENCE: Finviz Income Statement panel, PLAN-0088 §Wave G §G-1.
 */

"use client";
// WHY "use client": uses useQuery (TanStack) which requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMarketCap, formatPrice } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface IncomeStatementFYProps {
  instrumentId: string;
}

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Shape of each income-statement record's data field from EODHD.
 * All fields are nullable — EODHD data completeness varies by ticker.
 */
interface IncomeStatementData {
  totalRevenue?: number | string | null;
  grossProfit?: number | string | null;
  operatingIncome?: number | string | null;
  netIncome?: number | string | null;
  ebitda?: number | string | null;
  eps?: number | string | null;
  // EODHD also uses lowercase camelCase variants in some ingest paths
  total_revenue?: number | string | null;
  gross_profit?: number | string | null;
  operating_income?: number | string | null;
  net_income?: number | string | null;
}

// ── Row definitions ───────────────────────────────────────────────────────────
// WHY inline row config (not separate constant): the rows are tightly coupled to
// the accessor function logic below — co-locating prevents a mismatch between
// row label and accessor key when either changes.
const ROWS = [
  { key: "revenue",          label: "Revenue" },
  { key: "gross_profit",     label: "Gross Profit" },
  { key: "operating_income", label: "Op. Income" },
  { key: "net_income",       label: "Net Income" },
  { key: "ebitda",           label: "EBITDA" },
  { key: "eps",              label: "EPS" },
] as const;

type RowKey = typeof ROWS[number]["key"];

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * safeNum — coerce EODHD string/number/null to number | null.
 * EODHD returns some financial fields as string-encoded numbers ("391036000000").
 */
function safeNum(v: unknown): number | null {
  if (v == null || v === "" || v === "None") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * extractRowValue — pull the correct field from an income-statement data dict.
 * EODHD uses PascalCase in most records, but the metric_extractor normalizes
 * some to snake_case. We try both forms.
 */
function extractRowValue(data: IncomeStatementData, rowKey: RowKey): number | null {
  switch (rowKey) {
    case "revenue":          return safeNum(data.totalRevenue     ?? data.total_revenue);
    case "gross_profit":     return safeNum(data.grossProfit      ?? data.gross_profit);
    case "operating_income": return safeNum(data.operatingIncome  ?? data.operating_income);
    case "net_income":       return safeNum(data.netIncome        ?? data.net_income);
    case "ebitda":           return safeNum(data.ebitda);
    case "eps":              return safeNum(data.eps);
    default:                 return null;
  }
}

/**
 * formatFY — convert ISO date to short fiscal-year label.
 * "2025-09-28" → "FY25". Fiscal-year end months vary by company (Apple = Sept).
 */
function formatFY(dateStr: string): string {
  try {
    // WHY UTC parse: prevents off-by-one day at midnight UTC in western timezones
    const d = new Date(dateStr + "T00:00:00Z");
    return `FY${String(d.getUTCFullYear()).slice(2)}`;
  } catch {
    return dateStr.slice(0, 4); // fallback: year only
  }
}

/**
 * formatCellValue — display a numeric P&L value with appropriate suffix.
 * For EPS: show as "$N.NN" (typically <$100).
 * For all others: use formatMarketCap which handles B/M/K suffixes.
 */
function formatCellValue(value: number | null, rowKey: RowKey): string {
  if (value == null) return "—";
  if (rowKey === "eps") {
    // WHY separate EPS format: EPS is per-share ($2.43), not billions.
    // formatMarketCap would output "$0.00" for EPS < $1M — wrong scale.
    // WHY formatPrice (not template literal): architecture test bans hand-built
    // currency strings (\$${...}); formatPrice uses Intl.NumberFormat correctly.
    return formatPrice(value);
  }
  return formatMarketCap(value);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function IncomeStatementFY({ instrumentId }: IncomeStatementFYProps) {
  const { accessToken } = useAuth();

  // ── Data fetch ─────────────────────────────────────────────────────────────
  // WHY staleTime 10min: income-statement records are updated at most daily by
  // the EODHD ingest pipeline. No need to refetch within a research session.
  const { data, isLoading } = useQuery({
    queryKey: ["income-statement", instrumentId],
    queryFn: () => createGateway(accessToken).getIncomeStatement(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 10 * 60_000,
  });

  // ── Build FY columns (most-recent 4 + TTM placeholder) ────────────────────
  // Records from S3 can be ANNUAL or QUARTERLY. We keep only ANNUAL records,
  // sort ascending (oldest → newest), and take the last 4 fiscal years.
  // WHY drop QUARTERLY: quarterly income-statement columns would be too narrow
  // and too many (12+ quarters) for the 1fr left-column layout.
  const annualRecords = (data?.records ?? [])
    .filter((r) => r.period_type === "ANNUAL")
    .sort((a, b) => a.period_end.localeCompare(b.period_end));

  // Slice to last N FY columns based on available data (max 4).
  // WHY max 4: at 280px sidebar or 1fr main column, 4 columns keep each cell
  // readable at 11px monospace without horizontal overflow.
  const MAX_COLS = 4;
  const cols = annualRecords.slice(-MAX_COLS);

  // ── Loading skeleton ────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        {/* Header */}
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            INCOME STATEMENT
          </span>
        </div>
        <Skeleton className="m-2 h-[120px] rounded-[2px]" />
      </div>
    );
  }

  // ── Empty state: no annual records available ───────────────────────────────
  // WHY graceful empty (not hidden): the Fundamentals tab should always show
  // the section header so analysts know the data category exists. Hiding the
  // section entirely would make analysts think it wasn't fetched.
  if (cols.length === 0) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            INCOME STATEMENT
          </span>
        </div>
        <div className="px-2 py-2 text-[11px] font-mono text-muted-foreground">
          Annual income-statement data not available
        </div>
      </div>
    );
  }

  // ── Build column labels ─────────────────────────────────────────────────────
  const colLabels = cols.map((r) => formatFY(r.period_end));

  // ── Build row values and apply G-4 placeholder cleanup ─────────────────────
  // G-4 rule: collapse rows where ALL FY columns are null — those rows render
  // 4 dashes that look broken and add no information. Only show rows that have
  // at least one non-null value across the visible columns.
  const rowsToRender = ROWS.filter((row) =>
    cols.some((r) => extractRowValue(r.data as IncomeStatementData, row.key) != null),
  );

  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">

      {/* ── Section header ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          INCOME STATEMENT
        </span>
        {/* WHY "Annual" label: distinguishes from quarterly data on the Fundamentals tab */}
        <span className="text-[9px] font-mono text-muted-foreground/60 ml-auto">
          Annual · {cols.length}Y
        </span>
      </div>

      {/* ── Column header row ──────────────────────────────────────────────── */}
      {/* WHY sticky header (not absolutely positioned): sticky allows the table to
          scroll normally while the header stays visible when many rows are present.
          This is the correct CSS primitive for "header stays with the table", as
          opposed to position:fixed which would detach from the document flow. */}
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] font-mono" role="table" aria-label="Annual income statement">

          {/* Column headers — FY25, FY24, FY23, FY22 (newest right) */}
          <thead>
            <tr>
              {/* WHY min-w-[80px] on label column: metric labels like "Op. Income"
                  need enough width to avoid truncation at 11px font size.
                  The column width doesn't expand to FY columns so the value cells
                  stay compact. */}
              <th
                scope="col"
                className="py-1 px-2 text-left text-[9px] uppercase tracking-[0.08em] text-muted-foreground/60 font-normal min-w-[80px]"
              >
                {/* Empty header over row labels — intentionally blank */}
              </th>
              {colLabels.map((lbl) => (
                <th
                  key={lbl}
                  scope="col"
                  className="py-1 px-2 text-right text-[9px] uppercase tracking-[0.08em] text-muted-foreground font-normal tabular-nums whitespace-nowrap"
                >
                  {lbl}
                </th>
              ))}
            </tr>
          </thead>

          {/* Data rows — only rows with at least one non-null value */}
          <tbody className="divide-y divide-border/30">
            {rowsToRender.map((row) => {
              const values = cols.map((r) =>
                extractRowValue(r.data as IncomeStatementData, row.key),
              );

              return (
                <tr key={row.key} className="hover:bg-muted/20 transition-colors">
                  {/* Row label */}
                  <td className="py-1 px-2 text-[10px] uppercase tracking-[0.06em] text-muted-foreground whitespace-nowrap">
                    {row.label}
                  </td>

                  {/* FY value cells */}
                  {values.map((val, colIdx) => {
                    // Color-code net income by sign — red loss, green profit.
                    // Other rows stay neutral (no sign-based coloring — revenue
                    // being "positive green" adds no information beyond the number).
                    const colorClass =
                      row.key === "net_income" && val != null
                        ? val >= 0
                          ? "text-positive"
                          : "text-negative"
                        : "text-foreground";

                    return (
                      <td
                        key={colIdx}
                        className={`py-1 px-2 text-right tabular-nums whitespace-nowrap ${val == null ? "text-muted-foreground/40" : colorClass}`}
                      >
                        {formatCellValue(val, row.key)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
