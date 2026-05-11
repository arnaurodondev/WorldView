/**
 * components/portfolio/DividendYTDStrip.tsx — single-row dividend strip
 * (PLAN-0088 Wave E E-1; replaces DividendIncomeTimeline).
 *
 * REPLACES the previous ~470 px tall DividendIncomeTimeline (per-ticker
 * stacked bar chart of monthly dividends, always empty in demo data because
 * paper-traders have no DIVIDEND transactions and v1 broker schema doesn't
 * yet store dividend events). The audit (§1 row 6) flagged it as "D"
 * — pure wasted vertical real estate.
 *
 * REPLACEMENT: a 28 px row in the Public.com style:
 *
 *     DIVIDENDS YTD $X across N tickers · Forward yield -- · Next ex-date --
 *
 * Empty-state behaviour: when no DIVIDEND transactions exist the row reads
 *
 *     DIVIDENDS YTD $0 · Forward yield -- · Next ex-date --
 *
 * — graceful, single-line, never confused with a broken state.
 *
 * DATA SOURCE: GET /v1/transactions?portfolio_id=…  (filtered client-side
 * to TransactionType=DIVIDEND with executed_at in the current calendar
 * year). We deliberately reuse the existing transactions endpoint — no
 * new backend work — because dividend data ALREADY arrives via the
 * transactions stream when SnapTrade reports them; the previous timeline
 * just over-presented an underlying signal that fits in one row.
 *
 * Forward yield + Next ex-date are placeholders today (em-dash) — the
 * fundamentals dataset has these per-instrument but we'd need a portfolio-
 * level rollup endpoint, which is out of scope for Wave E. Keeping the
 * fields visible primes the user's expectation for when they DO populate.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx → HoldingsTab.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-1, audit §2 wireframe row R-6.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface DividendYTDStripProps {
  /** Portfolio UUID. Null/undefined skips the fetch (loading skeleton). */
  portfolioId: string | null | undefined;
}

// ── Component ────────────────────────────────────────────────────────────────

export function DividendYTDStrip({ portfolioId }: DividendYTDStripProps) {
  const { accessToken } = useAuth();

  // Pull the latest 200 transactions and filter to current-year DIVIDEND rows.
  // 200 is the practical upper bound on YTD dividend events even for a very
  // active broker-connected portfolio (SPY pays quarterly; 50 tickers × 4
  // payments = 200). Pagination is intentionally omitted — if a user needs
  // a richer view they go to the Transactions tab.
  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["dividends-ytd-strip", portfolioId],
    queryFn: () =>
      createGateway(accessToken!).getTransactions(portfolioId!, { limit: 200 }),
    staleTime: 60_000,
  });

  if (!portfolioId || isLoading) {
    return (
      <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex-1 px-3 flex items-center gap-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-3 w-14" />
          </div>
        ))}
      </div>
    );
  }

  // Reduce to YTD totals — sum of `amount` field across DIVIDEND rows whose
  // executed_at falls inside the current calendar year (UTC).
  const yearStart = new Date(Date.UTC(new Date().getUTCFullYear(), 0, 1));
  const dividendTxs = (data?.transactions ?? []).filter(
    (tx) =>
      tx.type === "DIVIDEND" &&
      // amount may be null for older rows (BP-263); skip those so we don't
      // count phantom $0 dividends.
      tx.amount != null &&
      new Date(tx.executed_at) >= yearStart,
  );
  const totalYtd = dividendTxs.reduce((s, tx) => s + (tx.amount ?? 0), 0);
  // Distinct tickers that paid us this year — useful "across N tickers"
  // caption. WHY Set on ticker (not instrument_id): tickers are user-
  // facing; instrument IDs aren't.
  const tickers = new Set(dividendTxs.map((tx) => tx.ticker).filter(Boolean));

  return (
    <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card font-mono text-[11px]">
      {/* YTD total + ticker count. Coloured `text-foreground` (white-ish)
          when non-zero so the eye latches onto a populated number; muted
          when $0 so the row reads as "no income yet" without alarm. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          DIV YTD
        </span>
        <span
          className={
            "tabular-nums " +
            (totalYtd > 0 ? "text-foreground" : "text-muted-foreground")
          }
        >
          {formatPrice(totalYtd)}
        </span>
        {tickers.size > 0 && (
          <span className="text-[10px] text-muted-foreground">
            across {tickers.size} {tickers.size === 1 ? "ticker" : "tickers"}
          </span>
        )}
      </div>

      {/* FORWARD YIELD — portfolio-weighted average dividend yield. Out of
          scope for Wave E (needs a per-instrument fundamentals rollup
          endpoint). Em-dash placeholder so the field shape is locked in. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          FWD YIELD
        </span>
        <span className="tabular-nums text-muted-foreground">—</span>
      </div>

      {/* NEXT EX-DATE — earliest upcoming ex-dividend date across holdings.
          Same scope-cut as forward yield. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          NEXT EX-DATE
        </span>
        <span className="tabular-nums text-muted-foreground">—</span>
      </div>
    </div>
  );
}
