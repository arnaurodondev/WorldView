/**
 * components/instrument/financials/IncomeStatementTable.tsx
 *
 * WHY THIS EXISTS (PLAN-0090 T-C-02): Finviz-style P&L block showing the last
 * 4 fiscal years side-by-side. Ratios (margins/PE) compress the trajectory
 * analysts want — a 5-row × 4-FY table answers the multi-year story at a glance.
 *
 * WHY 4 FY COLUMNS: enough to see a trend; six would wrap the 1fr left column
 * at 11px monospace. WHY ROWS = Revenue / Gross Profit / EBIT / Net Income /
 * EPS: the standard P&L ladder — scale, efficiency, op leverage, bottom line,
 * per-share. Bloomberg DES "IS" uses the same ordering.
 *
 * DATA: S9 GET /v1/fundamentals/{id}/income-statement → ANNUAL records.
 * data dict uses EODHD PascalCase (totalRevenue, grossProfit, operatingIncome,
 * netIncome, eps); some metric-extractor paths normalize to snake_case so we
 * try both. DESIGN: PRD-0088 §6.8, PLAN-0090 §T-C-02.
 */

"use client";
// WHY "use client": useQuery requires React context (TanStack Query provider).

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatMarketCap, formatPrice } from "@/lib/utils";

interface IncomeStatementTableProps {
  instrumentId: string;
}

// WHY typed (not Record<string, unknown>): records.data is JSONB; typing the
// cast prevents typos from silently rendering "—" in every cell.
interface IncomeStatementData {
  totalRevenue?: number | string | null;
  grossProfit?: number | string | null;
  operatingIncome?: number | string | null;  // EODHD's EBIT field
  netIncome?: number | string | null;
  eps?: number | string | null;
  total_revenue?: number | string | null;
  gross_profit?: number | string | null;
  operating_income?: number | string | null;
  net_income?: number | string | null;
}

// WHY co-located row config: label and accessor key are tightly coupled — a
// separate constants file would invite mismatch when either changes.
const ROWS = [
  { key: "revenue",      label: "Revenue" },
  { key: "gross_profit", label: "Gross Profit" },
  { key: "ebit",         label: "EBIT" },
  { key: "net_income",   label: "Net Income" },
  { key: "eps",          label: "EPS" },
] as const;
type RowKey = typeof ROWS[number]["key"];

// EODHD returns some fields as string-encoded numbers ("391036000000").
function safeNum(v: unknown): number | null {
  if (v == null || v === "" || v === "None") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function extractValue(data: IncomeStatementData, key: RowKey): number | null {
  // EBIT === operatingIncome in EODHD's income-statement section.
  switch (key) {
    case "revenue":      return safeNum(data.totalRevenue    ?? data.total_revenue);
    case "gross_profit": return safeNum(data.grossProfit     ?? data.gross_profit);
    case "ebit":         return safeNum(data.operatingIncome ?? data.operating_income);
    case "net_income":   return safeNum(data.netIncome       ?? data.net_income);
    case "eps":          return safeNum(data.eps);
  }
}

// WHY UTC parse: avoids off-by-one-day in western timezones at midnight UTC.
function formatFY(dateStr: string): string {
  try {
    return `FY${String(new Date(dateStr + "T00:00:00Z").getUTCFullYear()).slice(2)}`;
  } catch {
    return dateStr.slice(0, 4);
  }
}

// WHY split EPS from money: formatMarketCap renders "$0.00" for EPS under $1M
// (wrong scale). EPS is per-share — use Intl currency formatter via formatPrice.
function formatCell(v: number | null, key: RowKey): string {
  if (v == null) return "—";
  return key === "eps" ? formatPrice(v) : formatMarketCap(v);
}

export function IncomeStatementTable({ instrumentId }: IncomeStatementTableProps) {
  const { accessToken } = useAuth();

  // WHY staleTime 24h: annual P&L changes only on new fiscal-year 10-K filings.
  // Matches the T-A-03 useFinancialsTabData policy → TanStack dedupes shared keys.
  const { data, isLoading } = useQuery({
    queryKey: ["income-statement", instrumentId],
    queryFn: () => createGateway(accessToken).getIncomeStatement(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 24 * 60 * 60 * 1000,
  });

  // WHY ANNUAL only: quarterly columns (12+ narrow cells) would overflow 1fr.
  // Sort ascending then slice last 4 for newest-on-right Finviz convention.
  const cols = (data?.records ?? [])
    .filter((r) => r.period_type === "ANNUAL")
    .sort((a, b) => a.period_end.localeCompare(b.period_end))
    .slice(-4);

  if (isLoading) return <Skeleton className="h-[140px] rounded-[2px]" />;
  if (cols.length === 0) {
    return <div className="text-[11px] text-muted-foreground px-2 py-2">Income statement not available.</div>;
  }

  return (
    <table className="w-full text-[11px] font-mono" role="table" aria-label="Annual income statement">
      <thead>
        <tr>
          {/* Blank header over row labels; min-w-[80px] keeps "Gross Profit" un-truncated at 11px. */}
          <th scope="col" className="py-1 px-2 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-normal min-w-[80px]" />
          {cols.map((r) => (
            <th key={r.id} scope="col" className="py-1 px-2 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono font-normal tabular-nums whitespace-nowrap">
              {formatFY(r.period_end)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border/30">
        {ROWS.map((row) => (
          <tr key={row.key} className="hover:bg-muted/20 transition-colors">
            <td className="py-1 px-2 text-[10px] uppercase tracking-[0.06em] text-muted-foreground whitespace-nowrap">{row.label}</td>
            {cols.map((r) => {
              const v = extractValue(r.data as IncomeStatementData, row.key);
              // WHY color only net_income: revenue/gross/EBIT being "positive
              // green" adds no information beyond the number; net-income sign
              // coloring flags loss-years immediately (the actionable signal).
              const color = row.key === "net_income" && v != null
                ? v >= 0 ? "text-positive" : "text-negative"
                : "text-foreground";
              return (
                <td key={r.id} className={`py-1 px-2 text-right tabular-nums whitespace-nowrap ${v == null ? "text-muted-foreground/40" : color}`}>
                  {formatCell(v, row.key)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
