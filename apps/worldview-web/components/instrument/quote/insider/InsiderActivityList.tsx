/**
 * components/instrument/quote/insider/InsiderActivityList.tsx
 * — Top-5 insider transactions mini-list (W5-T-16)
 *
 * DATA SOURCE: `data: FundamentalsSectionResponse | null` from the page-bundle
 *   `bundle.insider` field. Zero extra fetch — the bundle already carries the
 *   last 12 months of insider transactions for the instrument.
 *
 * DESIGN:
 *   - `<div data-table-grid="dense">` → 18px `--row-h` rows (Δ4).
 *   - `text-[10px]` labels (F1 floor, Δ2). No `rounded-*` (Δ3).
 *   - Rows: date (10px muted) | owner name truncated | type | value.
 *   - Type color: BUY → positive; SALE → negative; other → muted.
 *   - Max 5 rows; empty state: "No insider activity in last 12 months."
 *
 * WHO USES IT: QuoteTab.tsx (T-25 wiring pass).
 * LINE LIMIT: ≤ 140 LOC.
 */

// WHY no "use client": pure display — props only, no browser APIs.

import type { FundamentalsSectionResponse, InsiderTransaction } from "@/types/api";
import { formatMarketCap } from "@/lib/utils";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Map transaction_type to color class. BUY=positive, SALE=negative. */
// WHY string|undefined: EODHD records occasionally arrive with empty `data`
// objects that pass `filter(Boolean)` but have no transaction_type field.
// Without the undefined guard, `.toUpperCase()` crashes the instrument page.
function txColor(type: string | undefined): string {
  if (!type) return "text-muted-foreground";
  const upper = type.toUpperCase();
  if (upper === "BUY" || upper === "PURCHASE") return "text-positive";
  if (upper === "SALE" || upper === "SELL") return "text-negative";
  return "text-muted-foreground";
}

/** Abbreviate transaction type to 4 chars for tight columns. */
function txLabel(type: string | undefined): string {
  if (!type) return "—";
  const upper = type.toUpperCase();
  if (upper === "BUY" || upper === "PURCHASE") return "BUY";
  if (upper === "SALE" || upper === "SELL") return "SALE";
  if (upper.includes("OPTION")) return "OPT";
  return upper.slice(0, 4);
}

/** Format USD value as compact string (e.g. "-$2.8M"). */
function fmtValue(value: number | null, type: string | undefined): string | null {
  if (value == null || !type) return null;
  const sign = type.toUpperCase() === "BUY" || type.toUpperCase() === "PURCHASE" ? "+" : "-";
  const abs = Math.abs(value);
  return `${sign}${formatMarketCap(abs)}`;
}

/** Format date to MMM D (e.g. "Apr 30"). */
function fmtDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return dateStr.slice(0, 10);
  }
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface InsiderActivityListProps {
  /** Insider transactions from bundle.insider (FundamentalsSectionResponse). */
  data: FundamentalsSectionResponse | null | undefined;
  /** True while bundle is loading — shows skeleton rows. */
  isLoading?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InsiderActivityList({ data, isLoading = false }: InsiderActivityListProps) {
  // WHY records[0].data cast: insider data is stored in records[0].data as an
  // array of InsiderTransaction objects per the EODHD section convention.
  // We cast once rather than on every map call.
  const rawRecords = data?.records ?? [];
  const transactions: InsiderTransaction[] = rawRecords
    .slice(0, 5) // WHY top-5 only: 5 × 18px = 90px card height (design target)
    .map((r) => r.data as unknown as InsiderTransaction)
    .filter(Boolean);

  const isEmpty = !isLoading && transactions.length === 0;

  return (
    <div className="border-t border-[hsl(var(--border-subtle))]">
      {/* Section header */}
      <div className="flex items-center h-[20px] px-3 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">
          Insider Activity
        </span>
      </div>

      {/* WHY data-table-grid="dense": dense variant → --row-h=18px (Δ4).
          18px × 5 rows = 90px card height — compact enough to sit above the fold. */}
      <div data-table-grid="dense">
        {isLoading && Array.from({ length: 5 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,18px)] px-3 gap-2">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {isEmpty && (
          <div className="px-3 py-2 text-[10px] text-muted-foreground/60">
            No insider activity in last 12 months.
          </div>
        )}

        {!isLoading && !isEmpty && transactions.map((tx, idx) => (
          <div
            key={idx}
            role="row"
            className="flex items-center h-[var(--row-h,18px)] px-3 gap-1.5"
          >
            {/* Date: MMM D */}
            <span className="text-[10px] text-muted-foreground shrink-0 w-[36px]">
              {fmtDate(tx.date)}
            </span>
            {/* Owner name: truncated to available space */}
            <span className="text-[10px] text-foreground truncate flex-1 min-w-0">
              {tx.owner_name}
            </span>
            {/* Type: BUY/SALE/OPT in semantic color */}
            <span className={`text-[10px] font-mono shrink-0 ${txColor(tx.transaction_type)}`}>
              {txLabel(tx.transaction_type)}
            </span>
            {/* Value: +$2.8M / -$2.8M */}
            <span className={`text-[10px] font-mono tabular-nums shrink-0 ${txColor(tx.transaction_type)}`}>
              {fmtValue(tx.value, tx.transaction_type) ?? "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
