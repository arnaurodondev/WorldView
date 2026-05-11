/**
 * components/instrument/InsiderTransactionsTable.tsx — Insider buy/sell activity
 *
 * WHY THIS EXISTS: Insider transactions are a leading governance signal. When
 * executives buy shares on the open market (code "P"), it signals conviction that
 * the stock is undervalued — insiders know the business better than any analyst.
 * Consistent insider selling (code "S") can signal overvaluation or personal
 * liquidity needs, though single sales are less informative than clusters.
 * Bloomberg uses a dedicated insider activity panel on the DES page.
 *
 * WHY DICT-BY-INDEX FORMAT: EODHD returns the insider transactions array as a
 * JSON object keyed by index string — `{"0": {...}, "1": {...}}`. This is a
 * quirk of their PHP-style JSON serialization. We convert to an array client-side
 * using Object.values(), then sort by transactionDate descending.
 *
 * WHY transactionAcquiredDisposed (not transactionCode) for color coding:
 * EODHD transaction codes are granular (S, P, A, D, M, C, F, G, J, K, L, U, W, X, Z)
 * and not consistently meaningful for buy/sell signal. The AcquiredDisposed field
 * is the authoritative SEC form 4 field: "A" = Acquired (inflow), "D" = Disposed
 * (outflow). For institutional clients: "A" = positive signal, "D" = negative.
 *
 * WHY 10-ROW LIMIT: Insider transactions are published in batches on SEC form 4
 * filing dates. More than 10 rows introduces noise (old grants, automatic plan
 * sales). 10 rows covers ~3-6 months of activity for most large-cap stocks.
 *
 * WHO USES IT: FundamentalsTab left column (Wave D-3), below EarningsHistoryChart
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId}/insider-transactions
 * DESIGN REFERENCE: PLAN-0041 §T-D-3-02
 */

"use client";
// WHY "use client": uses useQuery for insider transactions fetch.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

// ── Props ─────────────────────────────────────────────────────────────────────

interface InsiderTransactionsTableProps {
  instrumentId: string;
}

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * S3 insider transaction record — PascalCase from EODHD.
 *
 * WHY PascalCase: EODHD returns raw PascalCase keys in the JSON blob stored
 * in S3. The database persists the raw payload without normalization, so the
 * wire format coming from S9 uses EODHD's original casing.
 *
 * WHY transactionAcquiredDisposed as "A"|"D"|string: SEC form 4 defines two
 * values — "A" (Acquired) and "D" (Disposed). In practice, some filings use
 * lowercase or null, so we treat the field as a general string.
 */
interface InsiderTxRaw {
  ownerName?: string | null;
  ownerType?: string | null;             // e.g. "director", "officer"
  transactionCode?: string | null;       // SEC form 4 transaction type
  transactionAcquiredDisposed?: string | null; // "A" = acquire, "D" = dispose
  transactionDate?: string | null;       // "YYYY-MM-DD"
  transactionPrice?: number | null;      // per-share price at transaction
  transactionAmount?: number | null;     // number of shares
}

// ── Color constants ────────────────────────────────────────────────────────────

const COLOR_ACQUIRE = "text-positive"; // Teal green — insider buying = positive
const COLOR_DISPOSE = "text-negative"; // Red — insider selling = negative
const COLOR_NEUTRAL = "text-muted-foreground";

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatTxDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  // WHY slice to "MMM DD": full date at 9px font is unreadable in the tight row.
  // "Jan 15" is the Bloomberg convention for insider table date cells.
  const date = new Date(dateStr + "T00:00:00Z");
  // POLISH PASS 2026-05-09: SplitsDividendsPanel formatDate already had this
  // guard; copy the same pattern here so a malformed insider `transaction_date`
  // (S4 EODHD adapter occasionally hands back "0000-00-00" for redacted Form 4
  // filings) renders as "—" instead of the literal string "Invalid Date".
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * formatTxShares — compact share count for table cell.
 *
 * WHY "K" suffix at ≥1000: insider transactions are often in thousands of shares
 * (1,500 shares of AAPL at $170 = $255k). Displaying "1.5K" vs "1,500" keeps the
 * amount column readable at 11px monospace font.
 */
function formatTxShares(amount: number | null | undefined): string {
  if (amount == null) return "—";
  if (amount >= 1_000_000) return `${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `${(amount / 1_000).toFixed(1)}K`;
  return amount.toLocaleString();
}

/**
 * getSideClass — color-code the A/D acquisition side.
 * Uses transactionAcquiredDisposed as the authoritative signal.
 */
function getSideClass(tx: InsiderTxRaw): string {
  const side = tx.transactionAcquiredDisposed?.toUpperCase();
  if (side === "A") return COLOR_ACQUIRE;
  if (side === "D") return COLOR_DISPOSE;
  return COLOR_NEUTRAL;
}

/**
 * getSideLabel — show concise direction for the transaction code column.
 *
 * WHY show transactionCode (not just A/D): The SEC code communicates the
 * mechanism (P = open-market purchase vs A = award vs M = derivative exercise).
 * An open-market purchase "P" is a stronger buy signal than an award "A"
 * because it reflects voluntary capital commitment.
 */
function getSideLabel(tx: InsiderTxRaw): string {
  const code = tx.transactionCode?.toUpperCase() ?? "—";
  return code;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InsiderTransactionsTable({ instrumentId }: InsiderTransactionsTableProps) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);

  // ── Fetch insider transactions ─────────────────────────────────────────────
  // WHY staleTime 600_000: SEC form 4 filings are published within 2 business
  // days of the transaction. A 10-minute stale window avoids thrashing the API
  // on page navigation while remaining fresh enough to catch filing bursts.
  const { data, isLoading } = useQuery({
    queryKey: ["insider-transactions", instrumentId],
    queryFn: () => gateway.getInsiderTransactions(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 600_000,
  });

  // ── Parse dict-by-index → sorted array ─────────────────────────────────────
  // WHY Object.values(): EODHD serializes the transactions array as a JSON object
  // with string indices ("0", "1", "2"…). Object.values() extracts them in insertion
  // order (V8 sorts integer-keyed properties numerically), giving us the transactions
  // in the original EODHD order (usually chronological).
  const rawDict =
    (data?.records?.[0]?.data as Record<string, InsiderTxRaw> | undefined) ?? {};
  const transactions: InsiderTxRaw[] = Object.values(rawDict)
    .filter((tx): tx is InsiderTxRaw => typeof tx === "object" && tx !== null)
    .sort((a, b) => {
      // Sort descending by transactionDate — most recent first.
      // WHY fallback to empty string: null dates sort to the end.
      const da = a.transactionDate ?? "";
      const db = b.transactionDate ?? "";
      return db.localeCompare(da);
    })
    .slice(0, 10); // Cap at 10 rows per WHY comment above

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            INSIDER ACTIVITY
          </span>
        </div>
        <div className="px-2 py-1 space-y-1">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[18px] rounded-[2px]" />
          ))}
        </div>
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (transactions.length === 0) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            INSIDER ACTIVITY
          </span>
        </div>
        <div className="px-2 py-2 text-[11px] font-mono text-muted-foreground">
          No insider transactions on record
        </div>
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          INSIDER ACTIVITY
        </span>
        <span className="text-[9px] font-mono text-muted-foreground/60 ml-auto">
          {transactions.length} records
        </span>
      </div>

      {/* ── Column headers ───────────────────────────────────────────────── */}
      {/* WHY sticky header inside overflow div: users scroll through 10 rows;
          the column labels help orient them without leaving the section. */}
      <div className="grid grid-cols-[1fr_28px_56px_52px] gap-x-2 px-2 py-0.5 border-b border-border/40 bg-muted/20">
        <span className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60">OWNER</span>
        <span className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60 text-center">TYPE</span>
        <span className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60 text-right">SHARES</span>
        <span className="text-[9px] uppercase tracking-[0.06em] text-muted-foreground/60 text-right">DATE</span>
      </div>

      {/* ── Transaction rows ─────────────────────────────────────────────── */}
      {transactions.map((tx, i) => {
        const sideClass = getSideClass(tx);
        const sideLabel = getSideLabel(tx);

        return (
          <div
            key={i}
            className="grid grid-cols-[1fr_28px_56px_52px] gap-x-2 px-2 items-center h-[22px] border-b border-border/20 last:border-0 hover:bg-muted/50 transition-colors"
          >
            {/* Owner name — truncated to avoid overflow in narrow column */}
            <span
              className="text-[10px] font-mono text-foreground truncate"
              title={tx.ownerName ?? undefined}
            >
              {tx.ownerName ?? "—"}
            </span>

            {/* Transaction type code — colored by A/D direction */}
            <span className={`text-[10px] font-mono text-center ${sideClass}`}>
              {sideLabel}
            </span>

            {/* Share count — right-aligned tabular nums */}
            <span className={`text-[10px] font-mono tabular-nums text-right ${sideClass}`}>
              {formatTxShares(tx.transactionAmount)}
            </span>

            {/* Transaction date */}
            <span className="text-[10px] font-mono text-muted-foreground text-right tabular-nums">
              {formatTxDate(tx.transactionDate)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
