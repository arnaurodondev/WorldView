/**
 * components/portfolio/SemanticHoldingsTable.tsx — 10-column holdings table
 *
 * WHY THIS EXISTS: The portfolio holdings table is the most data-critical surface
 * for a portfolio manager. Ten columns give enough data to make re-balancing
 * decisions without navigating to the instrument detail page:
 *   Ticker | Name | Qty | Avg Cost | Current | P&L$ | P&L% | Value | Weight | Sector
 *
 * WHY `<table>` (not div grid): Semantic HTML tables are screen-reader accessible
 * (correct role=rowheader/cell/row semantics, keyboard navigation). Div grids
 * require manual ARIA to achieve the same — more code for lower reliability.
 *
 * WHY sticky thead: traders scroll through many holdings; they need the column
 * labels visible at all times to compare numbers across rows. `sticky top-0` on
 * thead keeps headers in view during vertical scroll.
 *
 * WHY tabular-nums on every td with a number: monospace tabular-nums forces
 * fixed-width digits so decimal points align vertically across rows — a hard
 * Bloomberg UX requirement for any financial table.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab
 * DATA SOURCE: holdingsResp.holdings + batch quotes from S9
 * DESIGN REFERENCE: PRD-0031 §8.2 Holdings Table, Wave 4
 */

"use client";
// WHY "use client": uses useRouter().push() for row-click navigation to instrument detail.

import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent } from "@/lib/utils";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { Holding } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SemanticHoldingsTableProps {
  holdings: Holding[];
  /** Live quotes keyed by instrument_id */
  quotes: Record<string, {
    price: number;
    change: number;
    change_pct: number;
    freshness_status?: string;
  }>;
  /** GICS sector per instrument_id (loaded lazily from fundamentals) */
  sectors?: Record<string, string | null>;
  /** Total portfolio market value — used to compute Weight column */
  totalValue: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * fmtPnl — format an absolute P&L value with sign prefix
 *
 * WHY prefix: traders instantly need to see positive vs negative without looking
 * at color (useful for printing/export and colorblind users).
 */
function fmtPnl(value: number): string {
  return value >= 0 ? `+${formatPrice(value)}` : formatPrice(value);
}

/**
 * formatStalenessAwarePrice — prefix "~" when quote is stale/delayed.
 *
 * WHY: when the EODHD circuit breaker opens (PLAN-0036), S9 returns cached/EOD
 * snapshots. "~" tells the trader "this price may be hours old." The title tooltip
 * explains the reason. This matches the behavior of the original portfolio page.
 */
function formatStalenessAwarePrice(price: number, freshness?: string): string {
  const isStale = freshness != null && freshness !== "live";
  return isStale ? `~${formatPrice(price)}` : formatPrice(price);
}

// ── SemanticHoldingsTable ────────────────────────────────────────────────────

export function SemanticHoldingsTable({
  holdings,
  quotes,
  sectors,
  totalValue,
}: SemanticHoldingsTableProps) {
  const router = useRouter();

  if (holdings.length === 0) {
    return <InlineEmptyState message="No holdings yet." />;
  }

  // WHY compute totals first: the tfoot row needs portfolio-level aggregates.
  // Computing in one pass avoids a second iteration.
  let totalPnl = 0;
  let totalPnlCost = 0; // for P&L% = totalPnl / totalCost

  const rows = holdings.map((h) => {
    const quote = quotes[h.instrument_id];
    // WHY fallback chain: quote → h.current_price → h.average_cost (break-even)
    const livePrice = quote?.price ?? h.current_price ?? h.average_cost;
    const freshness = quote?.freshness_status;
    const value = livePrice * h.quantity;
    const pnl = (livePrice - h.average_cost) * h.quantity;
    const pnlPct =
      h.average_cost > 0
        ? ((livePrice - h.average_cost) / h.average_cost) * 100
        : 0;
    const weight =
      totalValue > 0 ? (value / totalValue) * 100 : 0;
    const sector = sectors?.[h.instrument_id] ?? null;

    totalPnl += pnl;
    totalPnlCost += h.average_cost * h.quantity;

    return { h, livePrice, freshness, value, pnl, pnlPct, weight, sector };
  });

  const totalPnlPct = totalPnlCost > 0 ? (totalPnl / totalPnlCost) * 100 : 0;

  return (
    // WHY overflow-auto: the 10-column table may exceed the panel width on small
    // screens. overflow-auto adds a scroll bar rather than clipping data.
    <div className="overflow-auto">
      {/* WHY border-collapse: removes default cell spacing so 1px borders read
          as clean grid lines rather than double-bordered gaps. */}
      <table className="w-full border-collapse text-[11px]">

        {/* ── Column headers ───────────────────────────────────────────── */}
        {/* WHY sticky top-0 bg-card z-10: keeps column labels visible while
            scrolling through many holdings. bg-card matches the panel surface
            so headers don't expose the table body when scrolling. */}
        <thead className="sticky top-0 bg-card z-10">
          <tr className="h-[22px] border-b border-border">
            {/* WHY font-normal (not font-medium/semibold): terminal headers use
                ALL CAPS + tracking to create hierarchy, not font weight.
                font-normal keeps headers visually lighter than data. */}
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              TICKER
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              NAME
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              QTY
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              AVG COST
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              CURRENT
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              P&amp;L $
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              P&amp;L %
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              VALUE
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              WEIGHT
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              SECTOR
            </th>
          </tr>
        </thead>

        {/* ── Data rows ─────────────────────────────────────────────────── */}
        {/* WHY divide-y divide-border/30: subtle 30%-opacity borders between rows
            give row delineation without heavy visual noise. */}
        <tbody className="divide-y divide-border/30">
          {rows.map(({ h, livePrice, freshness, value, pnl, pnlPct, weight, sector }) => (
            // WHY h-[22px]: matches terminal row density standard (Wave 1 §0 spec).
            // 22px rows pack more data per viewport without becoming unreadable.
            <tr
              key={h.holding_id}
              className="h-[22px] hover:bg-muted/40 cursor-pointer transition-colors"
              onClick={() => router.push(`/instruments/${encodeURIComponent(h.entity_id)}`)}
              // WHY role=row + tabIndex + onKeyDown: semantic table already has correct
              // ARIA roles; tabIndex makes rows keyboard-focusable; Enter/Space triggers nav.
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  router.push(`/instruments/${encodeURIComponent(h.entity_id)}`);
                }
              }}
            >
              {/* Ticker — text-primary distinguishes the instrument identifier */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
                {h.ticker}
              </td>

              {/* Name — truncate prevents overflow in constrained panel widths */}
              <td className="px-2 text-[11px] text-foreground max-w-[120px] truncate">
                {h.name}
              </td>

              {/* Quantity */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {h.quantity.toLocaleString("en-US")}
              </td>

              {/* Avg Cost */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {formatPrice(h.average_cost)}
              </td>

              {/* Current Price — "~" prefix when quote is stale (PLAN-0036) */}
              <td
                className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right"
                title={
                  freshness && freshness !== "live"
                    ? "Delayed or end-of-day price — live feed unavailable"
                    : undefined
                }
              >
                {formatStalenessAwarePrice(livePrice, freshness)}
              </td>

              {/* P&L $ — green/red with + prefix */}
              <td
                className={cn(
                  "px-2 font-mono text-[11px] tabular-nums text-right",
                  pnl >= 0 ? "text-positive" : "text-negative",
                )}
              >
                {fmtPnl(pnl)}
              </td>

              {/* P&L % */}
              <td
                className={cn(
                  "px-2 font-mono text-[11px] tabular-nums text-right",
                  pnlPct >= 0 ? "text-positive" : "text-negative",
                )}
              >
                {pnlPct >= 0 ? "+" : ""}{formatPercent(pnlPct / 100)}
              </td>

              {/* Value — total position value */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {formatPrice(value)}
              </td>

              {/* Weight — % of total portfolio */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">
                {formatPercent(weight / 100)}
              </td>

              {/* Sector — from fundamentals; "—" if not yet loaded */}
              <td className="px-2 text-[11px] text-muted-foreground truncate max-w-[100px]">
                {sector ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>

        {/* ── Total row ─────────────────────────────────────────────────── */}
        {/* WHY border-t-2: a thicker top border visually separates the summary
            row from the data rows — the one allowed exception to the "1px only" rule. */}
        <tfoot>
          <tr className="h-[22px] border-t-2 border-border">
            {/* WHY colSpan={5}: TOTAL label spans the non-numeric left columns */}
            <td
              colSpan={5}
              className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground"
            >
              TOTAL
            </td>

            {/* Total P&L $ */}
            <td
              className={cn(
                "px-2 font-mono text-[11px] tabular-nums text-right font-semibold",
                totalPnl >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {fmtPnl(totalPnl)}
            </td>

            {/* Total P&L % */}
            <td
              className={cn(
                "px-2 font-mono text-[11px] tabular-nums text-right font-semibold",
                totalPnlPct >= 0 ? "text-positive" : "text-negative",
              )}
            >
              {totalPnlPct >= 0 ? "+" : ""}{formatPercent(totalPnlPct / 100)}
            </td>

            {/* Total Value */}
            <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right font-semibold">
              {formatPrice(totalValue)}
            </td>

            {/* Remaining columns (Weight, Sector) — empty in total row */}
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
