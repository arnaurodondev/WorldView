/**
 * components/portfolio/TransactionsTotalsRow.tsx — Sticky aggregate summary strip
 * shown below the transactions table (PRD-0089 SA-C Task 5).
 *
 * WHY THIS EXISTS: A trader reviewing their transaction history needs a quick
 * "bottom line" — how much did I spend buying, how much did I get selling, how
 * much in dividends, and what did I pay in fees? Scrolling the table to sum
 * numbers mentally is error-prone. This strip shows those aggregates instantly
 * and updates live as filters change.
 *
 * WHY STICKY bottom-0: the strip must stay visible as the user scrolls through
 * hundreds of rows. Sticky positioning keeps it anchored to the bottom of the
 * table panel without JavaScript scroll tracking.
 *
 * SIGN CONVENTION:
 *   BUY COST      — sum of abs(amount) for BUY rows (cash you paid OUT)
 *   SELL PROCEEDS — sum of amount for SELL rows (cash you received IN)
 *   DIV INCOME    — sum of amount for DIV rows (income events)
 *   FEES          — sum of fee across all filtered rows
 *   NET           — SELL + DIV - BUY_COST - FEES (net cash impact)
 *
 * WHY abs(amount) for BUY COST: BUY transactions represent cash leaving the
 * account — the amount is negative (or we compute quantity × price which is
 * positive). Using abs() here makes BUY COST always display as a positive
 * dollar figure so the label "BUY cost" reads naturally.
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx
 * DATA SOURCE: Transaction[] filtered array passed as prop from TransactionsTab
 */

"use client";
// WHY "use client": relies on JSX with design-token class names that use CSS
// variables defined at runtime. No server-component rendering benefit here.

import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/utils";
import type { Transaction } from "@/types/api";

// ── Props ──────────────────────────────────────────────────────────────────────

interface TransactionsTotalsRowProps {
  /**
   * The filtered (and sorted) transaction rows that are currently visible in the
   * table. Aggregates update automatically when the filter changes.
   */
  filtered: Transaction[];
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * TransactionsTotalsRow — sticky bottom aggregate strip.
 *
 * Renders five stats across one horizontal row:
 *   BUY COST | SELL PROCEEDS | DIV INCOME | FEES | NET
 *
 * WHY no state: this component is a pure function of `filtered`. All maths
 * happen inline — no useEffect, no useMemo needed for a straightforward
 * O(n) scan. If the list is ≤ 200 rows (VIRTUALISATION_THRESHOLD), this
 * runs in < 1ms on any modern device.
 */
export function TransactionsTotalsRow({ filtered }: TransactionsTotalsRowProps) {
  // ── Aggregate computation ───────────────────────────────────────────────
  // Single O(n) pass over filtered rows to compute all five aggregates.
  // WHY not useMemo: the parent (TransactionsTab) only passes a new `filtered`
  // reference when the filter actually changes, so this already re-runs only
  // when data changes. Adding useMemo would be an over-optimisation.

  let buyCost = 0;      // Sum of (quantity × price) for BUY rows
  let sellProceeds = 0; // Sum of (quantity × price) for SELL rows
  let divIncome = 0;    // Sum of tx.amount for DIVIDEND rows
  let totalFees = 0;    // Sum of tx.fee across all rows

  for (const tx of filtered) {
    if (tx.type === "BUY") {
      // WHY quantity × price (not tx.amount): for BUY/SELL the canonical total
      // is qty × price (gross of fees). tx.amount is broker-reported and may
      // differ slightly due to rounding or FX conversion. rowTotal() uses the
      // same formula — we stay consistent.
      buyCost += tx.quantity * tx.price;
    } else if (tx.type === "SELL") {
      sellProceeds += tx.quantity * tx.price;
    } else if (tx.type === "DIVIDEND") {
      // WHY tx.amount (not qty × price): dividends carry no meaningful qty/price.
      // The broker-reported amount IS the dividend payment.
      divIncome += tx.amount ?? 0;
    }
    // WHY fee for ALL rows: fees apply to BUY and SELL; DIVIDEND rows carry
    // fee = 0 by schema convention so they add nothing but are safe to include.
    totalFees += tx.fee ?? 0;
  }

  // NET cash impact: inflows minus outflows.
  // WHY positive NET is good: SELL + DIV are money received; BUY + FEES are
  // money paid. A positive NET means the portfolio generated more cash than it
  // spent (realised gains + dividends exceed purchase costs).
  const net = sellProceeds + divIncome - buyCost - totalFees;

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div
      data-testid="transactions-totals-row"
      // WHY sticky bottom-0: keeps the totals bar anchored to the bottom of the
      // scrollable table panel as the user scrolls through hundreds of rows.
      // bg-card ensures the bar paints over row content below it (no see-through).
      className="flex gap-4 px-2 py-1 border-t border-border bg-card sticky bottom-0 text-[10px] font-mono tabular-nums"
    >
      {/* ── BUY COST ─────────────────────────────────────────── */}
      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">
          BUY cost
        </span>
        <span
          data-testid="totals-row-buy"
          // WHY text-negative for BUY cost: you spent this money — it's cash
          // that left the account. Red colouring matches the BUY badge convention
          // (Bloomberg: green = fill, but cost is a liability in cash terms).
          // We keep it neutral foreground unless the cost is non-zero to avoid
          // alarming colour when the filter shows no BUY rows.
          className={cn(
            "font-medium",
            buyCost > 0 ? "text-negative" : "text-foreground",
          )}
        >
          {formatPrice(buyCost)}
        </span>
      </span>

      {/* ── SELL PROCEEDS ────────────────────────────────────── */}
      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">
          SELL proceeds
        </span>
        <span
          data-testid="totals-row-sell"
          className={cn(
            "font-medium",
            // Positive proceeds = cash received = positive colour.
            sellProceeds > 0 ? "text-positive" : "text-foreground",
          )}
        >
          {formatPrice(sellProceeds)}
        </span>
      </span>

      {/* ── DIV INCOME ───────────────────────────────────────── */}
      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">
          DIV income
        </span>
        <span
          data-testid="totals-row-div"
          className={cn(
            "font-medium",
            // Dividend income is positive cash — same colour convention as SELL.
            divIncome > 0 ? "text-positive" : "text-foreground",
          )}
        >
          {formatPrice(divIncome)}
        </span>
      </span>

      {/* ── FEES ─────────────────────────────────────────────── */}
      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">
          Fees
        </span>
        <span
          data-testid="totals-row-fees"
          // Fees are a cost — render in negative colour when non-zero.
          className={cn(
            "font-medium",
            totalFees > 0 ? "text-negative" : "text-foreground",
          )}
        >
          {formatPrice(totalFees)}
        </span>
      </span>

      {/* ── NET ──────────────────────────────────────────────── */}
      <span className="flex items-baseline gap-1 ml-auto">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">
          Net
        </span>
        <span
          data-testid="totals-row-net"
          // WHY conditional colour: positive NET = you've taken more cash out
          // than you've put in (profitable). Negative NET = you're still net
          // invested (common for long-term buy-and-hold portfolios).
          className={cn(
            "font-semibold",
            net > 0
              ? "text-positive"
              : net < 0
                ? "text-negative"
                : "text-foreground",
          )}
        >
          {net >= 0 ? "+" : ""}
          {formatPrice(net)}
        </span>
      </span>
    </div>
  );
}
