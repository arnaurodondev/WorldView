/**
 * components/portfolio/HoldingInstrumentTxList.tsx — compact per-instrument
 * transaction list (PRD-0089 SA-B)
 *
 * WHY THIS EXISTS: The HoldingDetailPanel needs a quick-scan transaction history
 * for a single instrument (last N buys/sells/dividends). Rather than showing the
 * full paginated TransactionsTable (which is designed for an entire portfolio),
 * this component fetches all portfolio transactions and filters to the selected
 * instrument client-side.
 *
 * WHY client-side filter (not a dedicated per-instrument endpoint):
 *   1. The `/v1/transactions?portfolio_id=X` call is already cached by
 *      usePortfolioData (qk.portfolios.transactionsByPortfolio). Re-using that
 *      cached response costs zero network calls.
 *   2. Transaction counts are bounded (~100 rows from getTransactions default
 *      limit) — client-side filter is O(100) not O(N).
 *   3. Adding a per-instrument endpoint would require a new S1/S9 route for a
 *      convenience feature that is better served by cache reuse.
 *
 * DATA SOURCE: GET /v1/transactions?portfolio_id={portfolioId}&limit=100
 *   Filtered client-side to instrumentId.
 *
 * WHO USES IT: HoldingDetailPanel (section 5)
 * DESIGN REFERENCE: PRD-0089 SA-B §C
 */

"use client";
// WHY "use client": useQuery is a browser-only hook.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import type { TransactionsResponse, Transaction } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface HoldingInstrumentTxListProps {
  portfolioId: string;
  instrumentId: string;
  /** Max rows to display. Defaults to 5. */
  limit?: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Short date string for a transaction — shows "MMM DD" (e.g. "Jan 15").
 *
 * WHY no year: all transactions in the last 100 are typically within the
 * current year. Year would add clutter to the compact 3-column grid.
 * Exception: if year is different from current, we show "MMM DD YY".
 */
function fmtTxDate(isoString: string): string {
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (d.getFullYear() !== now.getFullYear()) {
    opts.year = "2-digit";
  }
  return d.toLocaleDateString("en-US", opts);
}

/**
 * Format transaction amount for display.
 *
 * WHY amount ?? quantity × price fallback: some transaction types (DEPOSIT,
 * FEE) report only `amount`. BUY/SELL transactions have both — we prefer
 * `amount` (broker-reported total) over `quantity × price` (reconstructed).
 * DIVIDEND rows typically only have `amount`.
 */
function fmtTxAmount(tx: Transaction): string {
  const val = tx.amount ?? tx.quantity * tx.price;
  if (!val) return "—";
  return `$${Math.abs(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HoldingInstrumentTxList({
  portfolioId,
  instrumentId,
  limit = 5,
}: HoldingInstrumentTxListProps) {
  const apiClient = useApiClient();

  // WHY qk.portfolios.holdingTx(portfolioId) — no instrumentId (Wave G QA
  // M-006): the underlying getTransactions request is identical across
  // every instrument (portfolio-wide list with limit=100); filtering is
  // done client-side in the useMemo below. Keying by portfolioId alone
  // means opening AAPL → MSFT → NVDA reuses one cache entry instead of
  // firing 3 identical S9 calls. The key still bakes in `limit: 100`
  // semantics that distinguish it from the portfolio-wide TransactionsTable.
  const { data, isLoading, isError } = useQuery<TransactionsResponse>({
    queryKey: qk.portfolios.holdingTx(portfolioId),
    queryFn: () => apiClient.getTransactions(portfolioId, { limit: 100 }),
    enabled: Boolean(portfolioId),
    staleTime: 60_000, // 1 min — transactions don't change sub-minute
  });

  // ── Filter + slice ────────────────────────────────────────────────────────
  const rows = useMemo(() => {
    if (!data?.transactions) return [];
    return data.transactions
      .filter((tx) => tx.instrument_id === instrumentId)
      // Newest first — traders want to see the most recent activity at the top.
      .sort(
        (a, b) =>
          new Date(b.executed_at).getTime() - new Date(a.executed_at).getTime(),
      )
      .slice(0, limit);
  }, [data, instrumentId, limit]);

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="px-3 py-2 space-y-px">
        {Array.from({ length: limit }).map((_, i) => (
          <div key={i} className="h-[20px] w-full animate-pulse rounded bg-muted" />
        ))}
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  // WHY explicit isError branch: without one, a failed fetch silently falls
  // through to the empty-state copy ("No transactions") which lies to the
  // user about whether the instrument has any history. Design §7 specifies
  // a dedicated error string for the transactions block.
  if (isError) {
    return (
      <div className="px-3 py-2 font-mono text-[11px] text-negative">
        Transactions unavailable
      </div>
    );
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  if (rows.length === 0) {
    return (
      <div className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
        No transactions
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    // WHY CSS grid (not <table>): table requires matching col groups and a
    // theaded/tbody semantic split. CSS grid is leaner for a compact 3-column
    // list, matches the HoldingLotsPanel aesthetic, and requires no extra DOM
    // elements for alignment.
    <div className="font-mono text-[11px]">
      {/* Column header row */}
      <div className="grid grid-cols-[80px_50px_1fr] gap-2 px-3 py-1 text-[9px] uppercase tracking-[0.08em] text-muted-foreground border-b border-border bg-muted/10">
        <div>DATE</div>
        <div>TYPE</div>
        <div className="text-right">AMOUNT</div>
      </div>

      {rows.map((tx) => (
        <div
          key={tx.transaction_id}
          className="grid grid-cols-[80px_50px_1fr] gap-2 px-3 h-[20px] items-center hover:bg-muted/20 border-b border-border/50"
        >
          {/* Date — compact, low-contrast for visual hierarchy */}
          <div className="tabular-nums text-muted-foreground">
            {fmtTxDate(tx.executed_at)}
          </div>

          {/* Type badge — using bg-muted/text-foreground to stay token-only.
              WHY no hardcoded colors: the design token set doesn't include a
              specific "BUY blue" or "SELL red" semantic token. Using bg-muted +
              foreground keeps the badge readable in both dark and light theme
              without locking in a specific hue. */}
          <div>
            <span
              className={cn(
                "inline-block px-1 py-px text-[9px] uppercase tracking-[0.05em] rounded-[2px]",
                // WHY per-type class variants: even without custom hue tokens we
                // can use the semantic text-positive / text-negative colours for
                // BUY (inflow, positive = adding value) and SELL (outflow, negative
                // = reducing the position), while DIV uses muted-foreground to
                // convey "neutral income" semantically.
                tx.type === "BUY"
                  ? "bg-muted text-positive"
                  : tx.type === "SELL"
                    ? "bg-muted text-negative"
                    : "bg-muted text-muted-foreground",
              )}
            >
              {tx.type}
            </span>
          </div>

          {/* Amount — right-aligned for column scanning.
              D6 remediation: broker-supplied `description` (when present) is
              rendered as a 9px subline beneath the amount. This is the
              human-readable explanation the broker attached to the fill
              (e.g. "AAPL US 06/20 175 C @ 2.15"). Truncated with a tooltip
              so long descriptions don't blow out the 440px panel width. */}
          <div className="text-right">
            <div className="font-mono tabular-nums text-[11px] text-foreground">
              {fmtTxAmount(tx)}
            </div>
            {tx.description && (
              // WHY slice(0, 500): defense-in-depth — server-side Pydantic
              // `max_length=500` is the source of truth; client-side slice
              // prevents DOM bloat from any unexpected backfill row.
              <div
                className="text-[9px] text-muted-foreground truncate max-w-[200px] ml-auto"
                title={(tx.description ?? "").slice(0, 500)}
              >
                {tx.description}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
