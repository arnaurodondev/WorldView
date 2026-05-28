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
 *
 * PRD-0089 SA-C: added 5 new columns (TIME, NAME, FX, CASH_IMPACT, BAL) and
 * the `runningBalance` pre-computed field on TransactionRow.
 */

import type { ColumnDef } from "@tanstack/react-table";
import { cn, formatPrice, formatDateTime } from "@/lib/utils";
import type { Transaction } from "@/types/api";

// ── Extended row type (PRD-0089 SA-C) ─────────────────────────────────────────

/**
 * TransactionRow — Transaction enriched with a pre-computed runningBalance.
 *
 * WHY a wrapper type (not extending Transaction): Transaction is an API-contract
 * type (frozen in @/types/api.ts). Adding a computed field to it would blur the
 * line between "what the server sends" and "what the table renders". Wrapping it
 * keeps the API shape pure while letting the table layer attach derived data.
 *
 * runningBalance is computed in TransactionsTable's pre-processing step (walking
 * chronologically) and made available to the BAL column renderer here.
 */
export interface TransactionRow extends Transaction {
  /**
   * Approximate running portfolio cash balance after this transaction.
   *
   * WHY approximate: excludes FX revaluation, splits, and non-cash corporate
   * actions. It's an indicative figure — useful for spotting buy/sell patterns
   * but not a substitute for a proper cash ledger.
   *
   * Sign: positive = cash in account. BUY reduces balance; SELL/DIV increases.
   * Computed by walking transactions in chronological order and accumulating
   * (amount ?? qty×price with sign).
   */
  runningBalance: number;
}

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
 * makeTransactionColumns — produce the 13-column ColumnDef array.
 *
 * WHY a factory (not a static array): the TICKER cell renderer falls back to
 * `tickerByInstrumentId` when `tx.ticker` is absent. That map is a prop on
 * TransactionsTable and is unavailable at module-load time. The factory is
 * called inside `useMemo` in TransactionsTable so it only re-executes when
 * the map reference changes.
 *
 * Column order: DATE | TIME | TYPE | CLASS | TICKER | NAME | QTY | PRICE | TOTAL | FEE | FX | CASH_IMPACT | BAL
 * (PRD-0089 SA-C added 5 new columns after the original 8)
 *
 * Responsive visibility (hidden at breakpoints):
 *   - NAME, BAL: hidden below xl (hidden xl:table-cell)
 *   - FX: hidden below lg (hidden lg:table-cell)
 *   Below md: only the original 8 columns visible.
 */
export function makeTransactionColumns(
  tickerByInstrumentId?: Record<string, string | null | undefined>,
): ColumnDef<TransactionRow>[] {
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
        // WHY render description here (PRD-0089 §3 / §8.1 line 145, D5 fix):
        // Phase 1 backend added `description` to TransactionListItem (broker-supplied
        // narrative — e.g. "AAPL Apple Inc Common Stock"). Showing it as a 9px
        // subline under the ticker provides context for ambiguous symbols (futures
        // expiries, options, corporate actions) without taking a full column.
        // truncate + title attribute keeps the row at the 20px density target.
        return (
          <div className="leading-none">
            <span className="font-mono text-[11px] tabular-nums text-primary font-medium">
              {enrichedTicker || "—"}
            </span>
            {row.original.description && (
              // WHY slice(0, 500): defense-in-depth — server-side Pydantic
              // `max_length=500` is the source of truth; client-side slice
              // prevents DOM bloat from any unexpected backfill row.
              <div
                className="text-[9px] text-muted-foreground truncate max-w-[160px] leading-none mt-0.5"
                title={(row.original.description ?? "").slice(0, 500)}
              >
                {row.original.description}
              </div>
            )}
          </div>
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
            {/* WHY separate DIVIDEND branch: negative dividend amounts (tax
                withholdings like -$0.76) are legitimate values. The old
                `total > 0` guard silently showed "—" for any negative or
                zero-amount dividend. Show any non-null amount the broker
                reported; use "—" only when the field is absent (null). */}
            {isPlaceholder
              ? "n/a"
              : tx.type === "DIVIDEND"
                ? tx.amount != null
                  ? formatPrice(tx.amount)
                  : "—"
                : total > 0
                  ? formatPrice(total)
                  : "—"}
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

    // ── PRD-0089 SA-C — 5 new columns ────────────────────────────────────

    {
      id: "time",
      header: "TIME",
      size: 55,
      // WHY no accessorKey: the time portion is derived from executed_at —
      // there is no standalone `time` field on Transaction.
      enableSorting: false,
      cell: ({ row }) => {
        const { executed_at } = row.original;
        // Extract HH:MM from the ISO UTC string using toLocaleTimeString with
        // 24-hour format so "14:30" is unambiguous across locales.
        // WHY hour12:false: traders use 24h time to avoid AM/PM ambiguity when
        // reading pre-market vs after-hours execution times.
        const time = new Date(executed_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        });
        return (
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {time}
          </span>
        );
      },
    },

    {
      id: "name",
      header: "NAME",
      size: 140,
      // WHY no accessorKey: name is an optional enrichment field that may or
      // may not be present on the Transaction row depending on the API version.
      enableSorting: false,
      // WHY hidden below xl: the NAME column is the longest text column; on
      // narrower viewports it would push numeric columns off-screen. Hiding it
      // below xl (1280px) preserves the 8 core columns on most monitors.
      meta: { className: "hidden xl:table-cell" },
      cell: ({ row }) => {
        // WHY cast to access name: the API Transaction type doesn't declare
        // `name` but the S9 ListTransactions response may include it via
        // enrichment. We access it safely with optional chaining.
        const name = (row.original as Transaction & { name?: string | null }).name;
        return (
          <span className="text-[11px] truncate max-w-[120px] block text-foreground/80">
            {name || "—"}
          </span>
        );
      },
    },

    {
      id: "fx",
      header: "FX",
      size: 50,
      enableSorting: false,
      // WHY hidden below lg: FX is a secondary data point (most transactions
      // are in USD). Showing it only on lg+ (1024px) keeps the table readable
      // on laptop-sized screens.
      meta: { className: "hidden lg:table-cell" },
      cell: ({ row }) => {
        const { currency } = row.original;
        // WHY only show when non-USD: USD is the base currency for most users.
        // Showing a USD badge on every row would create visual noise with no
        // informational value. Non-USD rows are the exception and warrant a chip.
        if (currency === "USD") return <span className="text-muted-foreground">—</span>;
        return (
          // WHY bg-muted rounded: a minimal pill distinguishes the currency code
          // visually from the numeric columns without using a high-contrast badge.
          <span className="bg-muted text-muted-foreground text-[9px] px-1 rounded font-mono font-semibold tracking-wider">
            {currency}
          </span>
        );
      },
    },

    {
      id: "cash_impact",
      header: "CASH IMPACT",
      size: 110,
      enableSorting: false,
      // WHY no accessorKey: cash impact is computed from amount, type, qty, price.
      cell: ({ row }) => {
        const tx = row.original;

        // ── Cash impact sign convention ────────────────────────────────────
        // BUY: cash leaves the account → negative impact.
        // SELL: cash enters the account → positive impact.
        // DIVIDEND: cash enters → positive impact (tx.amount is already signed).
        //
        // WHY use tx.amount when available: the broker-reported amount includes
        // FX conversion and any broker adjustments. When absent (null), fall back
        // to the computed qty×price with sign.
        let impact: number;
        if (tx.type === "DIVIDEND") {
          impact = tx.amount ?? 0;
        } else if (tx.amount != null) {
          // WHY negate for BUY: the broker reports amount as a positive absolute
          // value ("you paid $1,500"); we negate it to reflect cash leaving.
          // SELL amounts are already positive (cash received) — no negation needed.
          impact = tx.type === "BUY" ? -Math.abs(tx.amount) : Math.abs(tx.amount);
        } else {
          // Fallback: compute from qty × price with sign.
          const raw = tx.quantity * tx.price;
          impact = tx.type === "BUY" ? -raw : raw;
        }

        const formatted = `${impact >= 0 ? "+" : ""}${formatPrice(Math.abs(impact))}`;
        const signed = impact >= 0
          ? `+${formatPrice(Math.abs(impact))}`
          : `-${formatPrice(Math.abs(impact))}`;

        void formatted; // WHY: formatted was replaced by signed — suppress lint

        return (
          <span
            className={cn(
              "font-mono text-[11px] tabular-nums text-right w-full block",
              impact > 0 ? "text-positive" : impact < 0 ? "text-negative" : "text-foreground",
            )}
          >
            {impact === 0 ? "—" : signed}
          </span>
        );
      },
    },

    {
      id: "bal",
      // WHY title attribute on header: the running balance is an approximation.
      // The tooltip warns the user that FX revaluation is excluded so they don't
      // mistake this for a reconciled cash balance.
      header: () => (
        <span title="Approximate — excludes FX revaluation" className="cursor-help underline decoration-dotted decoration-muted-foreground/50">
          BAL
        </span>
      ),
      size: 110,
      enableSorting: false,
      // WHY hidden below xl: BAL is a derived value that requires the full
      // transaction history to be meaningful. On smaller screens the extra
      // column width isn't worth the trade-off against readable core columns.
      meta: { className: "hidden xl:table-cell" },
      cell: ({ row }) => {
        const { runningBalance } = row.original;
        return (
          <span className="font-mono text-[11px] tabular-nums text-right w-full block text-foreground/80">
            {formatPrice(runningBalance)}
          </span>
        );
      },
    },
  ];
}
