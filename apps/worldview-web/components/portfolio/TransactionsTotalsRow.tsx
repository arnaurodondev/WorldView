/**
 * components/portfolio/TransactionsTotalsRow.tsx — Sticky aggregate summary strip
 * shown below the transactions table (PRD-0089 SA-C Task 5).
 *
 * WHY THIS EXISTS: A trader reviewing their transaction history needs a quick
 * "bottom line" — how much did I spend buying, how much did I get selling, how
 * much in dividends, and what did I pay in fees? This strip shows those aggregates
 * instantly and updates live as filters change.
 *
 * WHY STICKY bottom-0: the strip must stay visible as the user scrolls through
 * hundreds of rows. Sticky positioning keeps it anchored to the bottom of the
 * table panel without JavaScript scroll tracking.
 *
 * CURRENCY GROUPING (D-001 — ISO 4217 / IBKR standard):
 * Multi-currency portfolios (e.g. IBKR users trading USD + CAD + EUR stocks)
 * must NOT have their totals aggregated across currencies. Summing $1,000 USD
 * + $1,000 CAD as "$2,000" is arithmetically wrong — it ignores FX rates.
 * We follow the IBKR Portfolio Analyst convention: group by currency and display
 * one totals row per currency. For single-currency portfolios, the display is
 * identical to the pre-D-001 layout (same data-testid values preserved for tests).
 *
 * SIGN CONVENTION:
 *   BUY COST      — sum of (quantity × price) for BUY rows (cash you paid OUT)
 *   SELL PROCEEDS — sum of (quantity × price) for SELL rows (cash you received IN)
 *   DIV INCOME    — sum of tx.amount for DIVIDEND rows (income events)
 *   FEES          — sum of tx.fee across all filtered rows
 *   NET           — SELL + DIV - BUY_COST - FEES (net cash impact)
 *
 * WHO USES IT: features/portfolio/components/TransactionsTab.tsx
 * DATA SOURCE: Transaction[] filtered array passed as prop from TransactionsTab
 */

"use client";
// WHY "use client": relies on JSX with design-token class names that use CSS
// variables defined at runtime.

import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/utils";
import type { Transaction } from "@/types/api";

// ── Props ──────────────────────────────────────────────────────────────────────

interface TransactionsTotalsRowProps {
  /**
   * The filtered (and sorted) transaction rows currently visible in the table.
   * Aggregates update automatically when the filter changes.
   */
  filtered: Transaction[];
}

// ── Currency grouping ─────────────────────────────────────────────────────────

interface CurrencyTotals {
  currency: string;
  buyCost: number;
  sellProceeds: number;
  divIncome: number;
  fees: number;
  net: number;
}

/**
 * computeCurrencyTotals — groups filtered transactions by currency and returns
 * one CurrencyTotals entry per distinct currency, sorted alphabetically.
 *
 * WHY group by currency (D-001): aggregating across multiple currencies produces
 * a meaningless number (1000 USD + 1000 CAD ≠ 2000 of any real currency). The
 * IBKR Portfolio Analyst convention is to show a separate totals strip per
 * currency — we follow the same standard.
 */
function computeCurrencyTotals(filtered: Transaction[]): CurrencyTotals[] {
  const map = new Map<string, CurrencyTotals>();

  for (const tx of filtered) {
    // Default to "USD" only as an absolute last resort for missing data.
    const ccy = tx.currency ?? "USD";
    if (!map.has(ccy)) {
      map.set(ccy, { currency: ccy, buyCost: 0, sellProceeds: 0, divIncome: 0, fees: 0, net: 0 });
    }
    const totals = map.get(ccy)!;

    if (tx.type === "BUY") {
      // WHY quantity × price (not tx.amount): gross cost excludes fees and matches
      // the BUY COST label semantics. tx.amount may include FX adjustment by the broker.
      totals.buyCost += tx.quantity * tx.price;
    } else if (tx.type === "SELL") {
      totals.sellProceeds += tx.quantity * tx.price;
    } else if (tx.type === "DIVIDEND") {
      // WHY tx.amount for dividends: dividends carry no meaningful qty/price.
      // The broker-reported amount IS the dividend payment.
      totals.divIncome += tx.amount ?? 0;
    }
    // Fees apply to all row types (DIVIDEND fee = 0 by schema convention).
    totals.fees += tx.fee ?? 0;
  }

  // Compute net per currency after all rows are accumulated.
  for (const totals of map.values()) {
    totals.net = totals.sellProceeds + totals.divIncome - totals.buyCost - totals.fees;
  }

  // Sort by currency code for deterministic display ordering.
  return Array.from(map.values()).sort((a, b) => a.currency.localeCompare(b.currency));
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * SingleCurrencyRow — the original layout for single-currency portfolios.
 *
 * WHY preserve this layout unchanged: single-currency is the common case and the
 * existing tests assert on data-testid="totals-row-buy" etc. without a currency
 * suffix. Keeping this component guarantees test backward-compatibility while the
 * multi-currency path adds new layout below it.
 */
function SingleCurrencyRow({ t }: { t: CurrencyTotals }) {
  return (
    <div className="flex gap-4 px-2 py-1 text-[10px] font-mono tabular-nums">
      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">BUY cost</span>
        <span
          data-testid="totals-row-buy"
          className={cn("font-medium", t.buyCost > 0 ? "text-negative" : "text-foreground")}
        >
          {formatPrice(t.buyCost)}
        </span>
      </span>

      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">SELL proceeds</span>
        <span
          data-testid="totals-row-sell"
          className={cn("font-medium", t.sellProceeds > 0 ? "text-positive" : "text-foreground")}
        >
          {formatPrice(t.sellProceeds)}
        </span>
      </span>

      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">DIV income</span>
        <span
          data-testid="totals-row-div"
          className={cn("font-medium", t.divIncome > 0 ? "text-positive" : "text-foreground")}
        >
          {formatPrice(t.divIncome)}
        </span>
      </span>

      <span className="flex items-baseline gap-1">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">Fees</span>
        <span
          data-testid="totals-row-fees"
          className={cn("font-medium", t.fees > 0 ? "text-negative" : "text-foreground")}
        >
          {formatPrice(t.fees)}
        </span>
      </span>

      <span className="flex items-baseline gap-1 ml-auto">
        <span className="text-muted-foreground uppercase tracking-[0.06em]">Net</span>
        <span
          data-testid="totals-row-net"
          className={cn(
            "font-semibold",
            t.net > 0 ? "text-positive" : t.net < 0 ? "text-negative" : "text-foreground",
          )}
        >
          {t.net >= 0 ? "+" : ""}
          {formatPrice(t.net)}
        </span>
      </span>
    </div>
  );
}

/**
 * MultiCurrencyRows — one compact row per currency for multi-currency portfolios.
 *
 * WHY a separate sub-component: the currency label prefix changes the visual
 * rhythm of the row. Keeping it separate avoids polluting SingleCurrencyRow
 * with conditional rendering.
 */
function MultiCurrencyRows({ groups }: { groups: CurrencyTotals[] }) {
  return (
    <>
      {groups.map((t) => (
        <div
          key={t.currency}
          className="flex gap-4 px-2 py-0.5 text-[10px] font-mono tabular-nums border-t border-border/40 first:border-t-0"
        >
          {/* Currency code label so users know which row is which. */}
          <span className="w-[32px] shrink-0 text-muted-foreground font-medium">{t.currency}</span>

          <span className="flex items-baseline gap-1">
            <span className="text-muted-foreground uppercase tracking-[0.06em]">BUY</span>
            <span className={cn("font-medium", t.buyCost > 0 ? "text-negative" : "text-foreground")}>
              {formatPrice(t.buyCost)}
            </span>
          </span>

          <span className="flex items-baseline gap-1">
            <span className="text-muted-foreground uppercase tracking-[0.06em]">SELL</span>
            <span className={cn("font-medium", t.sellProceeds > 0 ? "text-positive" : "text-foreground")}>
              {formatPrice(t.sellProceeds)}
            </span>
          </span>

          <span className="flex items-baseline gap-1">
            <span className="text-muted-foreground uppercase tracking-[0.06em]">DIV</span>
            <span className={cn("font-medium", t.divIncome > 0 ? "text-positive" : "text-foreground")}>
              {formatPrice(t.divIncome)}
            </span>
          </span>

          <span className="flex items-baseline gap-1">
            <span className="text-muted-foreground uppercase tracking-[0.06em]">Fees</span>
            <span className={cn("font-medium", t.fees > 0 ? "text-negative" : "text-foreground")}>
              {formatPrice(t.fees)}
            </span>
          </span>

          <span className="flex items-baseline gap-1 ml-auto">
            <span className="text-muted-foreground uppercase tracking-[0.06em]">Net</span>
            <span
              className={cn(
                "font-semibold",
                t.net > 0 ? "text-positive" : t.net < 0 ? "text-negative" : "text-foreground",
              )}
            >
              {t.net >= 0 ? "+" : ""}
              {formatPrice(t.net)}
            </span>
          </span>
        </div>
      ))}
    </>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * TransactionsTotalsRow — sticky bottom aggregate strip.
 *
 * Single-currency: five stats in one row (BUY COST | SELL | DIV | FEES | NET).
 * Multi-currency: one compact row per currency with a currency-code label prefix.
 *
 * WHY no state: this component is a pure function of `filtered`. All maths
 * happen inline — no useEffect, no useMemo needed for a straightforward O(n) scan.
 */
export function TransactionsTotalsRow({ filtered }: TransactionsTotalsRowProps) {
  const groups = computeCurrencyTotals(filtered);

  return (
    <div
      data-testid="transactions-totals-row"
      // WHY sticky bottom-0: keeps the totals bar anchored to the bottom of the
      // scrollable table panel as the user scrolls through hundreds of rows.
      className="border-t border-border bg-card sticky bottom-0"
    >
      {/* Single-currency path: identical layout + testids to the pre-D-001 design. */}
      {groups.length <= 1 && (
        <SingleCurrencyRow
          t={groups[0] ?? { currency: "", buyCost: 0, sellProceeds: 0, divIncome: 0, fees: 0, net: 0 }}
        />
      )}

      {/* Multi-currency path: one row per currency (IBKR/Bloomberg standard). */}
      {groups.length > 1 && <MultiCurrencyRows groups={groups} />}
    </div>
  );
}
