/**
 * components/instrument/quote/earnings/EarningsMiniList.tsx
 * — Last 4 annual EPS records mini-list (W5-T-17)
 *
 * DATA SOURCE: `data` from useQuoteSidebarData().earningsHistory.
 * DESIGN: data-table-grid="dense" (18px, Δ4); text-[10px] labels (Δ2).
 *   Surprise chip: positive=beat, negative=miss (Δ19). Max 4 records.
 * WHO USES IT: QuoteTab.tsx (T-25). LINE LIMIT: ≤ 130 LOC.
 */

// WHY no "use client": pure display — props only, no browser APIs.

import type { FundamentalsSectionResponse } from "@/types/api";
import { formatPrice } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Extract fiscal year from an ISO date string (e.g. "2024-12-31" → "FY24"). */
function fmtYear(date: string): string {
  const year = date.slice(2, 4); // "24"
  return `FY${year}`;
}

/** Format EPS value: "$1.26" or "—". */
function fmtEPS(v: number | null | undefined): string {
  if (v == null) return "—";
  return formatPrice(v);
}

/** Format surprise percent with sign (e.g. "+4.2%", "−3.1%"). */
function fmtSurprise(v: number | null | undefined): string | null {
  if (v == null) return null;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

/** Color class for surprise chip. */
function surpriseColor(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground/60";
  return v > 0 ? "text-positive" : "text-negative";
}

// ── Types ─────────────────────────────────────────────────────────────────────

// EODHD earnings-annual-trend stores data in PascalCase keys verbatim.
interface EarningsData {
  date?: string;
  epsActual?: number | null;
  epsEstimate?: number | null;
  surprisePercent?: number | null;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface EarningsMiniListProps {
  /** Annual earnings records from useQuoteSidebarData().earningsHistory. */
  data: FundamentalsSectionResponse | null | undefined;
  /** True while the query is in-flight. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EarningsMiniList({ data, isLoading = false }: EarningsMiniListProps) {
  const rawRecords = data?.records ?? [];
  // slice(-4): most recent 4 annual records (ascending order); reverse() = newest first.
  const records: EarningsData[] = rawRecords.slice(-4).reverse().map((r) => r.data as EarningsData);

  const isEmpty = !isLoading && records.length === 0;

  return (
    <div className="border-t border-[hsl(var(--border-subtle))]">
      {/* Section header */}
      <div className="flex items-center h-[20px] px-3 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          Annual EPS
        </span>
        <span className="ml-auto text-[9px] text-muted-foreground/40">actual / est / surprise</span>
      </div>

      <div data-table-grid="dense">
        {isLoading && Array.from({ length: 4 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,18px)] px-3 gap-2">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {isEmpty && (
          <div className="px-3 py-2 text-[10px] text-muted-foreground/60">
            No earnings history (ETF / fund).
          </div>
        )}

        {!isLoading && !isEmpty && records.map((rec, idx) => {
          const year = rec.date ? fmtYear(rec.date) : `—`;
          return (
            <div
              key={idx}
              role="row"
              className="flex items-center h-[var(--row-h,18px)] px-3 gap-1.5"
            >
              {/* Fiscal year */}
              <span className="text-[10px] text-muted-foreground shrink-0 w-[28px]">
                {year}
              </span>
              {/* EPS actual */}
              <span className="text-[10px] font-mono tabular-nums text-foreground shrink-0 w-[40px]">
                {fmtEPS(rec.epsActual)}
              </span>
              {/* EPS estimate */}
              <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0 w-[40px]">
                {fmtEPS(rec.epsEstimate)}
              </span>
              {/* Surprise % chip */}
              <span className={`text-[10px] font-mono tabular-nums shrink-0 ${surpriseColor(rec.surprisePercent)}`}>
                {fmtSurprise(rec.surprisePercent) ?? "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
