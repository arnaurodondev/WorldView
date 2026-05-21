/**
 * components/instrument/quote/bottom/PriceLevelsStrip.tsx
 * — Classic floor pivot levels + MA50/MA200 strip (W5-T-20)
 *
 * DATA: priceLevels from useQuoteSidebarData (GET /v1/fundamentals/{id}/price-levels).
 * DESIGN: data-table-grid (20px, Δ4); R=positive/S=negative/PIVOT=default colors.
 *   ↑ current above level; ↓ below; → at pivot. No rounded-* (Δ3).
 * WHO USES IT: BottomTripleStrip.tsx (T-22). LINE LIMIT: ≤ 130 LOC.
 */

// WHY no "use client": pure display — props only, no browser APIs.

import { formatPrice } from "@/lib/utils";
import type { PriceLevelsResponse, PriceLevel } from "@/types/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Arrow indicator for direction vs current price. */
function dirArrow(dir: PriceLevel["direction"]): string {
  if (dir === "above") return "↓"; // price is below this level
  if (dir === "below") return "↑"; // price is above this level
  return "→";
}

/** Color class for level label (R=positive, S=negative, PIVOT=default). */
function levelColor(label: string): string {
  if (label.startsWith("R")) return "text-positive";
  if (label.startsWith("S")) return "text-negative";
  return "text-muted-foreground";
}

/** Direction color for the arrow. */
function arrowColor(dir: PriceLevel["direction"]): string {
  if (dir === "above") return "text-negative"; // price below this level = bearish
  if (dir === "below") return "text-positive"; // price above this level = bullish
  return "text-muted-foreground";
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface PriceLevelsStripProps {
  data: PriceLevelsResponse | null | undefined;
  isLoading?: boolean;
  isError?: boolean;
  /** Current price to show relative arrows. */
  currentPrice?: number | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PriceLevelsStrip({
  data,
  isLoading = false,
  isError = false,
  currentPrice,
}: PriceLevelsStripProps) {
  const levels = data?.levels ?? [];
  const isEmpty = !isLoading && !isError && levels.length === 0;

  return (
    <div>
      {/* Column headers */}
      <div className="flex items-center h-[20px] px-2 border-b border-[hsl(var(--border-subtle))]">
        <span className="text-[9px] uppercase tracking-widest text-muted-foreground/60">Levels</span>
        <span className="text-[9px] text-muted-foreground/50 ml-auto">value</span>
      </div>

      <div data-table-grid>
        {isLoading && Array.from({ length: 7 }).map((_, i) => (
          <div key={i} role="row" className="flex items-center h-[var(--row-h,20px)] px-2">
            <span className="text-[10px] text-muted-foreground/30">—</span>
          </div>
        ))}

        {(isEmpty || isError) && (
          <div className="px-2 py-2 text-[10px] text-muted-foreground/60">
            Price levels unavailable.
          </div>
        )}

        {!isLoading && !isEmpty && !isError && levels.map((level) => (
          <div
            key={level.label}
            role="row"
            className="flex items-center h-[var(--row-h,20px)] px-2 gap-1.5"
          >
            <span className={`text-[10px] font-mono shrink-0 w-[36px] ${levelColor(level.label)}`}>
              {level.label}
            </span>
            <span className="text-[10px] font-mono tabular-nums text-foreground flex-1 text-right">
              {formatPrice(level.value)}
            </span>
            <span className={`text-[10px] font-mono shrink-0 ${arrowColor(level.direction)}`}>
              {dirArrow(level.direction)}
            </span>
          </div>
        ))}

        {/* MA50 / MA200 rows — separate from pivot levels */}
        {data?.ma50 != null && (
          <div role="row" className="flex items-center h-[var(--row-h,20px)] px-2 gap-1.5">
            <span className="text-[10px] font-mono shrink-0 w-[36px] text-muted-foreground">MA50</span>
            <span className="text-[10px] font-mono tabular-nums text-foreground flex-1 text-right">
              {formatPrice(data.ma50)}
            </span>
            <span className={`text-[10px] font-mono shrink-0 ${currentPrice != null ? (currentPrice >= data.ma50 ? "text-positive" : "text-negative") : "text-muted-foreground"}`}>
              {currentPrice != null ? (currentPrice >= data.ma50 ? "↑" : "↓") : "→"}
            </span>
          </div>
        )}
        {data?.ma200 != null && (
          <div role="row" className="flex items-center h-[var(--row-h,20px)] px-2 gap-1.5">
            <span className="text-[10px] font-mono shrink-0 w-[36px] text-muted-foreground">MA200</span>
            <span className="text-[10px] font-mono tabular-nums text-foreground flex-1 text-right">
              {formatPrice(data.ma200)}
            </span>
            <span className={`text-[10px] font-mono shrink-0 ${currentPrice != null ? (currentPrice >= data.ma200 ? "text-positive" : "text-negative") : "text-muted-foreground"}`}>
              {currentPrice != null ? (currentPrice >= data.ma200 ? "↑" : "↓") : "→"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
