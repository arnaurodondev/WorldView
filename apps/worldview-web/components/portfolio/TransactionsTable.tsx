/**
 * components/portfolio/TransactionsTable.tsx — Transaction history with filter bar
 *
 * WHY THIS EXISTS: Traders need to review their execution history to verify fills,
 * assess average-cost basis accuracy, and track dividend income. Extracted from
 * portfolio/page.tsx as a standalone component so it can be tested independently.
 *
 * WHY 7 COLUMNS: Date | Type | Ticker | Qty | Price | Total | Fee covers the
 * full picture of a trade execution without becoming wider than a typical panel.
 *
 * WHY [All] [BUY] [SELL] [DIVIDEND] filter: Traders often want to isolate one
 * transaction class — e.g., "show me all dividends this quarter" or "show only
 * sells to check my harvesting activity." A segmented control is faster than
 * typing a filter query.
 *
 * WHY DIVIDEND row shows "—" for Qty and Price: a dividend is an income event,
 * not a share purchase/sale. Qty and Price are meaningless for dividends; the
 * relevant amount is in the Fee column (repurposed as "amount" for DIVIDEND type).
 *
 * WHY data-testid on the type badge: tests assert BUY=text-positive, SELL=text-negative.
 * The data-testid uses the transaction_id to be stable even if row order changes.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Transactions tab
 * DATA SOURCE: getTransactions() via parent page
 * DESIGN REFERENCE: PRD-0031 §8.4 Transactions Table, Wave 4
 */

"use client";
// WHY "use client": uses useState for the active type filter.

import { useState } from "react";
import { cn } from "@/lib/utils";
import { formatPrice, formatDateTime } from "@/lib/utils";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { Transaction } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface TransactionsTableProps {
  transactions: Transaction[];
}

// WHY all four filter values: "ALL" avoids special-casing null in filter logic —
// every tx.type matches "ALL", BUY matches only BUY transactions, etc.
type FilterType = "ALL" | "BUY" | "SELL" | "DIVIDEND";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * typeBadgeClass — color for the type badge based on transaction type.
 *
 * WHY background + text pair: a colored badge is more scannable than plain text.
 * Bloomberg uses color-coded action indicators in trade blotters for the same reason.
 */
function typeBadgeClass(type: Transaction["type"]): string {
  switch (type) {
    case "BUY":
      return "bg-positive/20 text-positive";
    case "SELL":
      return "bg-negative/20 text-negative";
    case "DIVIDEND":
      // WHY text-primary for DIVIDEND: it's a neutral income event (neither gain nor loss).
      // text-primary (sky blue) signals "informational" without positive/negative connotation.
      return "bg-primary/20 text-primary";
    default:
      return "text-muted-foreground";
  }
}

// ── TransactionsTable ─────────────────────────────────────────────────────────

export function TransactionsTable({ transactions }: TransactionsTableProps) {
  // WHY local state: filter is ephemeral UI state, not part of the API query.
  // We filter client-side on the already-loaded transaction list (max 100 items).
  const [activeFilter, setActiveFilter] = useState<FilterType>("ALL");

  if (transactions.length === 0) {
    return <InlineEmptyState message="No transactions yet." />;
  }

  // WHY sort newest-first client-side: the API returns insertion order which
  // may not match execution order. Traders always review most-recent activity first.
  const sorted = [...transactions].sort(
    (a, b) => b.executed_at.localeCompare(a.executed_at),
  );

  // WHY filter after sort: sort is idempotent; filtering the sorted list avoids
  // resorting after a filter change.
  const filtered =
    activeFilter === "ALL"
      ? sorted
      : sorted.filter((tx) => tx.type === activeFilter);

  const filterButtons: { label: string; value: FilterType }[] = [
    { label: "All", value: "ALL" },
    { label: "BUY", value: "BUY" },
    { label: "SELL", value: "SELL" },
    { label: "DIV", value: "DIVIDEND" },
  ];

  return (
    <div className="flex flex-col gap-0">
      {/* ── Filter bar ──────────────────────────────────────────────────── */}
      {/* WHY h-9: matches the standard 36px header bar height used throughout */}
      <div className="flex h-9 items-center gap-1 border-b border-border px-2 shrink-0">
        {filterButtons.map(({ label, value }) => (
          <button
            key={value}
            aria-pressed={activeFilter === value}
            aria-label={`Show ${value === "ALL" ? "all transactions" : value + " transactions"}`}
            className={cn(
              "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] transition-colors",
              activeFilter === value
                ? "bg-primary/10 border-primary text-primary"
                : "bg-transparent border-border text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setActiveFilter(value)}
          >
            {label}
          </button>
        ))}

        {/* Row count — shows how many transactions match the active filter */}
        <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
          {filtered.length} / {transactions.length}
        </span>
      </div>

      {/* ── Table ───────────────────────────────────────────────────────── */}
      <div className="overflow-auto">
        <table className="w-full border-collapse text-[11px]">
          <thead className="sticky top-0 bg-card z-10">
            <tr className="h-[22px] border-b border-border">
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
                DATE
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
                TYPE
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
                TICKER
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                QTY
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                PRICE
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                TOTAL
              </th>
              <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
                FEE
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-border/30">
            {filtered.length === 0 ? (
              <tr>
                <td
                  colSpan={7}
                  className="px-2 py-3 text-center text-[11px] text-muted-foreground"
                >
                  No {activeFilter === "ALL" ? "" : activeFilter} transactions.
                </td>
              </tr>
            ) : (
              filtered.map((tx) => {
                const isDividend = tx.type === "DIVIDEND";
                // WHY quantity: for dividends, qty and price are meaningless (income event)
                const total = isDividend ? tx.fee : tx.quantity * tx.price;

                return (
                  <tr
                    key={tx.transaction_id}
                    className="h-[22px] hover:bg-muted/40 transition-colors"
                  >
                    {/* Date */}
                    <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground whitespace-nowrap">
                      {formatDateTime(tx.executed_at)}
                    </td>

                    {/* Type badge — data-testid for testing BUY/SELL color classes */}
                    <td className="px-2">
                      <span
                        className={cn(
                          "inline-flex items-center px-1 rounded-[2px] font-mono text-[10px] font-semibold tabular-nums",
                          typeBadgeClass(tx.type),
                        )}
                        // WHY data-testid with transaction_id: tests use this to assert
                        // BUY=text-positive and SELL=text-negative without searching by text.
                        // Pattern: "tx-type-{transaction_id}" e.g. "tx-type-tx-1"
                        data-testid={`tx-type-${tx.transaction_id}`}
                      >
                        {tx.type === "DIVIDEND" ? "DIV" : tx.type}
                      </span>
                    </td>

                    {/* Ticker */}
                    <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
                      {tx.ticker || "—"}
                    </td>

                    {/* Qty — "—" for DIVIDEND (not applicable) */}
                    <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                      {isDividend ? "—" : tx.quantity.toLocaleString("en-US")}
                    </td>

                    {/* Price — "—" for DIVIDEND */}
                    <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                      {isDividend ? "—" : formatPrice(tx.price)}
                    </td>

                    {/* Total — for DIVIDEND this is the income amount (fee field) */}
                    <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
                      {total > 0 ? formatPrice(total) : "—"}
                    </td>

                    {/* Fee — "—" for DIVIDEND (fee field repurposed as amount above) */}
                    <td className="px-2 font-mono text-[11px] tabular-nums text-muted-foreground text-right">
                      {!isDividend && tx.fee > 0 ? formatPrice(tx.fee) : "—"}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
