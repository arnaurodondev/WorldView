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

/**
 * Extract 2-digit fiscal year from an ISO date string (e.g. "2024-12-31" → "FY24").
 * WHY slice(2,4): EODHD dates are "YYYY-MM-DD". Chars at index 2-3 are the
 * last two digits of the 4-digit year ("24" from "2024"). This is intentional
 * — FY-prefixed 2-digit years are the standard display on Bloomberg terminals.
 */
function fmtYear(date: string): string {
  const year = date.slice(2, 4); // e.g. "2024-09-30" → "24"
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
  // WHY .sort() before slice(-4): the backend query_fundamentals() now orders
  // by period_end_date ASC, but we add a safety sort here so the component
  // is correct even against unordered responses (e.g. older cached payloads).
  // Sorting by `date` string is safe because EODHD uses ISO 8601 (YYYY-MM-DD)
  // which sorts lexicographically identically to chronologically.
  // slice(-4) then takes the 4 MOST RECENT records; reverse() → newest first.
  const records: EarningsData[] = rawRecords
    .map((r) => r.data as EarningsData)
    .filter((r) => !!r.date)
    .sort((a, b) => (a.date ?? "").localeCompare(b.date ?? "")) // ascending by date string
    .slice(-4) // last 4 = most recent
    .reverse(); // newest first for display

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
          <div key={i} role="row" className="flex items-center h-[var(--row-h,18px)] px-3 gap-1.5">
            <span className="text-[10px] text-muted-foreground/30 shrink-0 w-[28px]">—</span>
            <span className="text-[10px] text-muted-foreground/30 shrink-0 w-[40px]" />
            <span className="text-[10px] text-muted-foreground/30 shrink-0 w-[40px]" />
            <span className="text-[10px] text-muted-foreground/30 flex-1" />
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
              {/* EPS actual — right-aligned in fixed column */}
              <span className="text-[10px] font-mono tabular-nums text-foreground shrink-0 w-[40px] text-right">
                {fmtEPS(rec.epsActual)}
              </span>
              {/* EPS estimate — right-aligned in fixed column */}
              <span className="text-[10px] font-mono tabular-nums text-muted-foreground shrink-0 w-[40px] text-right">
                {fmtEPS(rec.epsEstimate)}
              </span>
              {/* Surprise % — flex-1 so it fills remaining space, right-aligned */}
              <span className={`text-[10px] font-mono tabular-nums flex-1 text-right ${surpriseColor(rec.surprisePercent)}`}>
                {fmtSurprise(rec.surprisePercent) ?? "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
