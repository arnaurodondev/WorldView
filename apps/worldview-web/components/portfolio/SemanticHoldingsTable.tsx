/**
 * components/portfolio/SemanticHoldingsTable.tsx — 12-column holdings table with sort
 *
 * WHY THIS EXISTS: The portfolio holdings table is the most data-critical surface
 * for a portfolio manager. Twelve columns give enough data to make re-balancing
 * decisions without navigating to the instrument detail page:
 *   Ticker | Name | Qty | Avg Cost | Current | Day$ | Day% | P&L$ | P&L% | Value | Weight | Sector
 *
 * WHY 12 columns (was 10): Day$ and Day% show today's price movement per position,
 * which is distinct from the cumulative unrealised P&L. Bloomberg PORT function
 * always shows both — traders need "how am I doing today" separate from
 * "how am I doing overall".
 *
 * WHY visual weight bars: a numeric percentage ("+33.27%") conveys no spatial
 * intuition — a proportional bar lets a portfolio manager immediately see
 * concentration risk. Bloomberg's portfolio view uses the same pattern.
 *
 * WHY click-to-sort: fixed row order is inconvenient for large portfolios.
 * Sorting by P&L$ immediately shows biggest winners/losers. Sorting by VALUE
 * reveals concentration. This is standard for every finance terminal.
 *
 * WHY `<table>` (not div grid): Semantic HTML tables are screen-reader accessible
 * (correct role=rowheader/cell/row semantics, keyboard navigation).
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab
 * DATA SOURCE: holdingsResp.holdings + batch quotes from S9
 * DESIGN REFERENCE: PLAN-0044 Wave 2
 */

"use client";
// WHY "use client": uses useRouter().push() for row-click navigation + useState for sort.

import { useState } from "react";
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

// ── Sort types ─────────────────────────────────────────────────────────────────

type SortCol = "qty" | "dayChange" | "dayChangePct" | "pnl" | "pnlPct" | "value" | "weight";
type SortDir = "asc" | "desc";

interface SortState {
  col: SortCol;
  dir: SortDir;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPnl(value: number): string {
  return value >= 0 ? `+${formatPrice(value)}` : formatPrice(value);
}

function formatStalenessAwarePrice(price: number, freshness?: string): string {
  const isStale = freshness != null && freshness !== "live";
  return isStale ? `~${formatPrice(price)}` : formatPrice(price);
}

// ── SortableHeader ─────────────────────────────────────────────────────────────

/**
 * SortableHeader — a <th> that shows a sort indicator and toggles direction on click.
 *
 * WHY separate component: the sort affordance (hover state + indicator) is
 * the same for every sortable column — extracting avoids repeating 4 classNames.
 */
function SortableHeader({
  col,
  label,
  sortState,
  onSort,
  align = "right",
}: {
  col: SortCol;
  label: string;
  sortState: SortState | null;
  onSort: (col: SortCol) => void;
  align?: "left" | "right";
}) {
  const isActive = sortState?.col === col;
  const indicator = isActive ? (sortState!.dir === "asc" ? " ▲" : " ▼") : "";

  return (
    <th
      className={cn(
        "px-2 text-[10px] uppercase tracking-[0.08em] font-normal cursor-pointer select-none",
        "hover:text-foreground transition-colors",
        isActive ? "text-primary" : "text-muted-foreground",
        align === "right" ? "text-right" : "text-left",
      )}
      onClick={() => onSort(col)}
      title={`Sort by ${label}`}
    >
      {label}
      <span className="text-[9px]">{indicator}</span>
    </th>
  );
}

// ── SemanticHoldingsTable ────────────────────────────────────────────────────

export function SemanticHoldingsTable({
  holdings,
  quotes,
  sectors,
  totalValue,
}: SemanticHoldingsTableProps) {
  const router = useRouter();

  // WHY default sort DESC by value: traders most care about their largest positions.
  // Showing the biggest positions first matches Bloomberg's default PORT view.
  const [sortState, setSortState] = useState<SortState>({ col: "value", dir: "desc" });

  if (holdings.length === 0) {
    return <InlineEmptyState message="No holdings yet." />;
  }

  // ── Compute per-row values ──────────────────────────────────────────────────
  let totalPnl = 0;
  let totalPnlCost = 0;

  const rows = holdings.map((h) => {
    const quote = quotes[h.instrument_id];
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

    // Day change — from today's price movement, not vs avg cost
    const dayChange = quote?.change ?? null;           // absolute price change today
    const dayChangePct = quote?.change_pct ?? null;    // percentage price change today
    // WHY multiply dayChange by quantity: the absolute day P&L contribution of this
    // position is dayChange (per share) × quantity (shares held).
    const dayChangeValue = dayChange != null ? dayChange * h.quantity : null;

    totalPnl += pnl;
    totalPnlCost += h.average_cost * h.quantity;

    return { h, livePrice, freshness, value, pnl, pnlPct, weight, sector, dayChange, dayChangePct, dayChangeValue };
  });

  // ── Sort rows ──────────────────────────────────────────────────────────────
  const sortedRows = [...rows].sort((a, b) => {
    let aVal: number;
    let bVal: number;

    switch (sortState.col) {
      case "qty":         aVal = a.h.quantity;            bVal = b.h.quantity;            break;
      case "dayChange":   aVal = a.dayChangeValue ?? 0;   bVal = b.dayChangeValue ?? 0;   break;
      case "dayChangePct": aVal = a.dayChangePct ?? 0;    bVal = b.dayChangePct ?? 0;     break;
      case "pnl":         aVal = a.pnl;                   bVal = b.pnl;                   break;
      case "pnlPct":      aVal = a.pnlPct;                bVal = b.pnlPct;                break;
      case "value":       aVal = a.value;                  bVal = b.value;                 break;
      case "weight":      aVal = a.weight;                 bVal = b.weight;                break;
    }

    return sortState.dir === "asc" ? aVal - bVal : bVal - aVal;
  });

  function handleSort(col: SortCol) {
    setSortState((prev) => {
      if (prev.col === col) {
        // Same column: toggle direction
        return { col, dir: prev.dir === "asc" ? "desc" : "asc" };
      }
      // New column: default descending (largest first)
      return { col, dir: "desc" };
    });
  }

  const totalPnlPct = totalPnlCost > 0 ? (totalPnl / totalPnlCost) * 100 : 0;

  return (
    <div className="overflow-auto">
      <table className="w-full border-collapse text-[11px]">

        {/* ── Column headers ─────────────────────────────────────────────── */}
        <thead className="sticky top-0 bg-card z-10">
          <tr className="h-[22px] border-b border-border">
            {/* Non-sortable columns: TICKER, NAME, AVG COST, CURRENT */}
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              TICKER
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              NAME
            </th>
            <SortableHeader col="qty" label="QTY" sortState={sortState} onSort={handleSort} />
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              AVG COST
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              CURRENT
            </th>
            {/* Sortable: DAY$ and DAY% — new columns showing today's price movement */}
            <SortableHeader col="dayChange" label="DAY $" sortState={sortState} onSort={handleSort} />
            <SortableHeader col="dayChangePct" label="DAY %" sortState={sortState} onSort={handleSort} />
            <SortableHeader col="pnl" label="P&L $" sortState={sortState} onSort={handleSort} />
            <SortableHeader col="pnlPct" label="P&L %" sortState={sortState} onSort={handleSort} />
            <SortableHeader col="value" label="VALUE" sortState={sortState} onSort={handleSort} />
            <SortableHeader col="weight" label="WEIGHT" sortState={sortState} onSort={handleSort} />
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              SECTOR
            </th>
          </tr>
        </thead>

        {/* ── Data rows ─────────────────────────────────────────────────── */}
        <tbody className="divide-y divide-border/30">
          {sortedRows.map(({ h, livePrice, freshness, value, pnl, pnlPct, weight, sector, dayChangeValue, dayChangePct }) => (
            <tr
              key={h.holding_id}
              className="h-[22px] hover:bg-muted/40 cursor-pointer transition-colors"
              onClick={() => router.push(`/instruments/${encodeURIComponent(h.entity_id)}`)}
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  router.push(`/instruments/${encodeURIComponent(h.entity_id)}`);
                }
              }}
            >
              {/* Ticker */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
                {h.ticker}
              </td>

              {/* Name */}
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

              {/* Current Price — "~" prefix when quote is stale */}
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

              {/* Day $ — today's absolute P&L contribution from this position.
                  WHY show "—" instead of $0 when no quote: $0 could mean the price
                  genuinely didn't move, or that no live quote is available. "—" is honest. */}
              <td
                className={cn(
                  "px-2 font-mono text-[11px] tabular-nums text-right",
                  dayChangeValue == null
                    ? "text-muted-foreground"
                    : dayChangeValue >= 0 ? "text-positive" : "text-negative",
                )}
              >
                {dayChangeValue == null ? "—" : fmtPnl(dayChangeValue)}
              </td>

              {/* Day % — today's percentage price change (per-share, not position) */}
              <td
                className={cn(
                  "px-2 font-mono text-[11px] tabular-nums text-right",
                  dayChangePct == null
                    ? "text-muted-foreground"
                    : dayChangePct >= 0 ? "text-positive" : "text-negative",
                )}
              >
                {dayChangePct == null
                  ? "—"
                  : `${dayChangePct >= 0 ? "+" : ""}${formatPercent(dayChangePct / 100)}`}
              </td>

              {/* P&L $ — cumulative unrealised P&L (vs avg cost) */}
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

              {/* Value */}
              <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                {formatPrice(value)}
              </td>

              {/* Weight — visual bar + percentage.
                  WHY w-[56px] container: fixed width ensures all bars are on the same
                  scale regardless of the text length. A 33% weight bar fills 33% of 56px.
                  WHY h-[3px] bar: 3px is the thinnest bar visible at 22px row height that
                  still reads as intentional (not a border artefact). */}
              <td className="px-2 text-muted-foreground">
                <div className="flex items-center gap-1.5 justify-end">
                  <div className="w-[48px] h-[3px] rounded-[1px] bg-muted/50 shrink-0">
                    <div
                      className="h-full rounded-[1px] bg-primary/50"
                      style={{ width: `${Math.min(weight, 100).toFixed(1)}%` }}
                    />
                  </div>
                  <span className="font-mono text-[11px] tabular-nums w-[36px] text-right">
                    {formatPercent(weight / 100)}
                  </span>
                </div>
              </td>

              {/* Sector */}
              <td className="px-2 text-[11px] text-muted-foreground truncate max-w-[100px]">
                {sector ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>

        {/* ── Total row ─────────────────────────────────────────────────── */}
        <tfoot>
          {/* WHY colSpan={7}: the 12 columns split as 7 non-aggregate left columns
              (TICKER, NAME, QTY, AVG COST, CURRENT, DAY$, DAY%) and 5 aggregate right
              columns (P&L$, P&L%, VALUE, WEIGHT-bar, SECTOR). TOTAL label spans the left. */}
          <tr className="h-[22px] border-t-2 border-border">
            <td
              colSpan={7}
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

            {/* Remaining columns (WEIGHT bar, SECTOR) — no aggregates */}
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
