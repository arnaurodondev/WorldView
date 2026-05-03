/**
 * components/portfolio/transaction-columns.tsx — ColumnDef array for TransactionsTable
 *
 * WHY THIS EXISTS: Extracted from TransactionsTable so the column definitions
 * (badge helpers, formatters, type logic) can be unit-tested in isolation and
 * kept out of the 800-line filter-bar component. A factory function is used
 * instead of a static array because cell renderers need access to
 * `tickerByInstrumentId` — a lookup map that is only available at render time.
 *
 * WHO USES IT: TransactionsTable → DataTable primitive.
 * DATA SOURCE: getTransactions() → Transaction[] via portfolio/page.tsx.
 * DESIGN REFERENCE: PRD-0031 §8.4 Transactions Table; PLAN-0059 F-1.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { cn, formatPrice, formatDateTime } from "@/lib/utils";
import type { Transaction } from "@/types/api";

// ── Helpers (exported for unit tests) ────────────────────────────────────────

/**
 * typeBadgeClass — Tailwind classes for the transaction-type chip.
 *
 * WHY BUY=green / SELL=red / DIVIDEND=blue: Bloomberg trade blotter convention.
 * A trader scanning for dividend income (blue) vs. fills (green/red) can do so
 * at a glance without reading the badge text.
 */
export function typeBadgeClass(type: Transaction["type"]): string {
  switch (type) {
    case "BUY":
      return "bg-positive/20 text-positive";
    case "SELL":
      return "bg-negative/20 text-negative";
    case "DIVIDEND":
      // text-primary (sky blue) = informational / income, no directional bias.
      return "bg-primary/20 text-primary";
    default:
      return "text-muted-foreground";
  }
}

/**
 * assetClassAbbrev — 2-3 char code rendered inside the CLASS badge column.
 *
 * WHY abbreviations: the CLASS column is ~60px wide at compact density. A
 * two-char code ("EQ") reads cleanly; the full word ("EQUITY") would clip.
 */
export function assetClassAbbrev(cls: string | null | undefined): string {
  switch ((cls ?? "").toLowerCase()) {
    case "equity":
      return "EQ";
    case "etf":
      return "ETF";
    case "option":
      return "OPT";
    case "future":
      return "FUT";
    case "bond":
      return "BND";
    case "crypto":
      return "CRY";
    default:
      return "—";
  }
}

/**
 * assetClassBadgeClass — Tailwind classes for the asset-class chip (PLAN-0053 T-D-4-02).
 *
 * WHY distinct hues: a trader can peripherally distinguish option fills (red chip)
 * from equity fills (green chip) without reading the badge. Each palette entry uses
 * /15-/25 opacity backgrounds so the chip stays subtle on the dark theme.
 * 'unknown' renders muted — it signals "unclassified" without false alarm.
 */
export function assetClassBadgeClass(cls: string | null | undefined): string {
  switch ((cls ?? "").toLowerCase()) {
    case "equity":
      return "bg-positive/15 text-positive border-positive/30";
    case "etf":
      return "bg-primary/15 text-primary border-primary/30";
    case "option":
      return "bg-negative/15 text-negative border-negative/30";
    case "future":
      return "bg-warning/15 text-warning border-warning/30";
    case "bond":
      // No "bond" semantic token — muted reads as dignified fixed-income.
      return "bg-muted-foreground/10 text-muted-foreground border-muted-foreground/30";
    case "crypto":
      // primary at higher opacity distinguishes crypto from ETF.
      return "bg-primary/25 text-primary border-primary/40";
    default:
      return "bg-muted/40 text-muted-foreground border-border/40";
  }
}

/**
 * rowTotal — canonical total for a transaction row.
 *
 * BUY/SELL → quantity × price (gross of fees).
 * DIVIDEND → tx.amount (broker-reported cash payment), 0 if null.
 *
 * WHY centralised: the Total cell, Min/Max amount filter, CSV export, and
 * the totals-row all need the same definition. Drift between them would
 * silently mis-filter rows or produce incorrect totals.
 */
export function rowTotal(tx: Transaction): number {
  if (tx.type === "DIVIDEND") return tx.amount ?? 0;
  return tx.quantity * tx.price;
}

// ── Column factory ────────────────────────────────────────────────────────────

/**
 * makeTransactionColumns — produce the 8-column ColumnDef array.
 *
 * WHY a factory (not a static array): the TICKER cell renderer falls back to
 * `tickerByInstrumentId` when `tx.ticker` is absent. That map is a prop on
 * TransactionsTable and is unavailable at module-load time. The factory is
 * called inside `useMemo` in TransactionsTable so it only re-executes when
 * the map reference changes.
 *
 * Column order: DATE | TYPE | CLASS | TICKER | QTY | PRICE | TOTAL | FEE
 * (matches the original raw-table column order exactly — PLAN-0059 F-1 contract:
 * "preserve every existing cell renderer exactly").
 */
export function makeTransactionColumns(
  tickerByInstrumentId?: Record<string, string | null | undefined>,
): ColumnDef<Transaction>[] {
  return [
    {
      id: "executed_at",
      accessorKey: "executed_at",
      header: "DATE",
      size: 130,
      cell: ({ row }) => (
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground whitespace-nowrap">
          {formatDateTime(row.original.executed_at)}
        </span>
      ),
    },
    {
      id: "type",
      accessorKey: "type",
      header: "TYPE",
      size: 70,
      cell: ({ row }) => {
        const { type, transaction_id } = row.original;
        return (
          // data-testid preserved from the original renderTxRow so existing
          // tests that query tx-type-{id} continue to work post-migration.
          <span
            className={cn(
              "inline-flex items-center px-1 rounded-[2px] font-mono text-[10px] font-semibold tabular-nums",
              typeBadgeClass(type),
            )}
            data-testid={`tx-type-${transaction_id}`}
          >
            {type === "DIVIDEND" ? "DIV" : type}
          </span>
        );
      },
    },
    {
      id: "asset_class",
      accessorKey: "asset_class",
      header: "CLASS",
      size: 60,
      cell: ({ row }) => {
        const { asset_class, transaction_id } = row.original;
        return (
          // data-testid preserved from the original renderTxRow.
          <span
            className={cn(
              "inline-flex items-center px-1 rounded-[2px] border font-mono text-[10px] font-semibold uppercase tabular-nums",
              assetClassBadgeClass(asset_class),
            )}
            title={asset_class ?? "Asset class unknown"}
            data-testid={`tx-asset-class-${transaction_id}`}
          >
            {assetClassAbbrev(asset_class)}
          </span>
        );
      },
    },
    {
      id: "ticker",
      header: "TICKER",
      size: 80,
      // WHY no accessorKey: ticker is derived — prefer tx.ticker, fall back to
      // tickerByInstrumentId (deprecated BP-262 workaround) when empty.
      // enableSorting=false because a computed / enriched field has no natural
      // sort key on the Transaction row itself.
      enableSorting: false,
      cell: ({ row }) => {
        const enrichedTicker =
          row.original.ticker || tickerByInstrumentId?.[row.original.instrument_id] || "";
        return (
          <span className="font-mono text-[11px] tabular-nums text-primary font-medium">
            {enrichedTicker || "—"}
          </span>
        );
      },
    },
    {
      id: "quantity",
      accessorKey: "quantity",
      header: "QTY",
      size: 100,
      cell: ({ row }) => {
        const { type, quantity } = row.original;
        return (
          // WHY "—" for DIVIDEND: a dividend is an income event, not a share
          // purchase/sale — quantity is meaningless and could mislead.
          <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
            {type === "DIVIDEND" ? "—" : quantity.toLocaleString("en-US")}
          </span>
        );
      },
    },
    {
      id: "price",
      accessorKey: "price",
      header: "PRICE",
      size: 100,
      cell: ({ row }) => {
        const { type, price } = row.original;
        return (
          <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
            {type === "DIVIDEND" ? "—" : formatPrice(price)}
          </span>
        );
      },
    },
    {
      id: "total",
      header: "TOTAL",
      size: 120,
      // WHY no accessorKey: total is computed from quantity, price, and type —
      // there is no `total` field on Transaction. enableSorting=false for the
      // same reason: no stable sort key.
      enableSorting: false,
      cell: ({ row }) => {
        const tx = row.original;
        // WHY isPlaceholder: brokerage imports occasionally include sentinel rows
        // (corporate actions, fee-only adjustments) with qty=0 AND price=0. These
        // are not user-actionable trades — render "n/a" so the user reads
        // "this isn't a real fill" rather than "$0.00" which looks like a bug.
        const isPlaceholder = tx.type !== "DIVIDEND" && tx.quantity === 0 && tx.price === 0;
        const total = rowTotal(tx);
        return (
          <span className="font-mono text-[11px] tabular-nums text-foreground text-right w-full block">
            {isPlaceholder ? "n/a" : total > 0 ? formatPrice(total) : "—"}
          </span>
        );
      },
    },
    {
      id: "fee",
      accessorKey: "fee",
      header: "FEE",
      size: 100,
      cell: ({ row }) => {
        const { type, fee } = row.original;
        return (
          // WHY "—" for DIVIDEND: dividends carry no brokerage fee in the
          // Transaction schema (the fee field is zero/null for income events).
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground text-right w-full block">
            {type !== "DIVIDEND" && fee > 0 ? formatPrice(fee) : "—"}
          </span>
        );
      },
    },
  ];
}
