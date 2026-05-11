/**
 * components/instrument/OverviewInsiderStrip.tsx — compact insider activity
 * panel for the Overview tab (5 most-recent transactions)
 *
 * WHY THIS EXISTS: The Overview tab's bottom row was previously a 50/50 split
 * of TopNews + EntityGraph. TopNews is empty for most demo entities (the
 * entity-article link table is sparse) and the EntityGraph has only 3 edges
 * for AAPL (data-sparse seed). Result: the bottom of the Overview tab looks
 * dead. Insider transactions ARE rich (5+ records seeded for AAPL) and are a
 * Bloomberg/Finviz/Yahoo staple — every analyst scans recent insider activity
 * before committing to a position. Adding an Insider strip alongside TopNews
 * doubles the bottom-zone density without adding new endpoints.
 *
 * WHY 5 ROWS (not 10): the Overview is a scan surface, not a research surface.
 * 5 rows × 22px = 110px — fits naturally next to a 110px news panel. Analysts
 * who want the full insider history click through to FundamentalsTab where
 * the InsiderTransactionsTable renders the full paginated list.
 *
 * WHY THE FUNDAMENTALS TAB ALREADY HAS InsiderTransactionsTable: that
 * component is paginated, filterable, and 30+ rows tall. This component is a
 * scannable preview — they intentionally serve different scan vs research
 * use-cases. No deduplication concern.
 *
 * WHY DERIVED FROM /v1/fundamentals/{id}/insider-transactions (not /v1/insider):
 * S9 returns insider transactions as fundamental-record snapshots. The schema
 * is `records[].data` where data is a string-keyed map of transactions. We
 * unfurl the map and sort by transactionDate descending.
 *
 * WHO USES IT: OverviewLayout (bottom row, sibling to InstrumentTopNews)
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrument_id}/insider-transactions
 * DESIGN REFERENCE: Finviz "Insider Trading", Yahoo Finance "Insider Transactions"
 */

"use client";
// WHY "use client": uses TanStack Query for data fetch.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import type { FundamentalsRecord } from "@/types/api";

// ── Local types — shape of the unwrapped insider-transactions payload ────────
// WHY local interface (not shared): the EODHD insider transaction shape is
// stable but proprietary. Keeping it local avoids leaking the EODHD-specific
// camelCase keys (transactionDate, ownerName, transactionCode) into the
// shared types layer where they would collide with our snake_case canon.
interface InsiderTx {
  /** Owner's display name (e.g. "Timothy D Cook"). */
  readonly ownerName: string | null;
  /** SEC transaction code: "S" sale, "P" purchase, "M" exercise, "G" gift, etc. */
  readonly transactionCode: string | null;
  /** ISO date "YYYY-MM-DD". Used for sort + display. */
  readonly transactionDate: string | null;
  /** Number of shares in the transaction. */
  readonly transactionAmount: number | null;
  /** Per-share price at transaction. */
  readonly transactionPrice: number | null;
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewInsiderStripProps {
  /** Instrument market_data_id (the S3 fundamentals routes use this id). */
  readonly instrumentId: string;
}

// ── Helper: SEC transaction-code → human label + color ────────────────────────
// WHY map (not switch): adding a new code = one-line edit. Switch would be 3
// lines per branch. The codes follow SEC Form 4 conventions.
const TX_CODE_DISPLAY: Record<string, { label: string; colorClass: string }> = {
  // Bullish (insider bought): positive green
  P: { label: "BUY", colorClass: "text-positive" },
  // Bearish (insider sold): negative red
  S: { label: "SELL", colorClass: "text-negative" },
  // Stock-option exercise: neutral amber (not directional sentiment)
  M: { label: "EXERCISE", colorClass: "text-warning" },
  // Gift / award / RSU vesting: neutral muted
  G: { label: "GIFT", colorClass: "text-muted-foreground" },
  A: { label: "GRANT", colorClass: "text-muted-foreground" },
  F: { label: "TAX", colorClass: "text-muted-foreground" },
};

function txDisplay(code: string | null): { label: string; colorClass: string } {
  if (!code) return { label: "—", colorClass: "text-muted-foreground" };
  // WHY uppercase: some seeds store lowercase ("s") even though SEC uses upper.
  const upper = code.toUpperCase();
  return TX_CODE_DISPLAY[upper] ?? { label: upper, colorClass: "text-muted-foreground" };
}

// ── Helper: format currency-ish numbers compactly ─────────────────────────────
// WHY local helper (not formatPrice from lib/format): the lib formatter prints
// trailing decimals always (e.g. "$254.23"). For shares we want short integers
// like "64.9K" or "1.2M" without dollar signs. Local implementation keeps the
// row width predictable.
function formatShares(n: number | null): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OverviewInsiderStrip({ instrumentId }: OverviewInsiderStripProps) {
  const { accessToken } = useAuth();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["insider-transactions", instrumentId],
    queryFn: () => createGateway(accessToken).getInsiderTransactions(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    // WHY 10min: insider transactions are filed with the SEC, then ingested by
    // S3 in a daily batch. They don't change within a single trading session.
    staleTime: 10 * 60_000,
  });

  // ── Unwrap the records[].data map into a flat InsiderTx[] ─────────────────
  // The EODHD shape is `records[0].data = { "0": {...tx}, "1": {...tx}, ... }`.
  // We unwrap, sort by transactionDate descending, and slice to top 5.
  const transactions = useMemo<InsiderTx[]>(() => {
    if (!data?.records || data.records.length === 0) return [];
    // WHY collect from ALL records (not just first): some adapters split insider
    // transactions across multiple snapshot records by period. Iterating all is
    // safer than assuming a single record. The map-based shape can have any
    // string keys; we ignore non-numeric keys.
    const all: InsiderTx[] = [];
    for (const rec of data.records as FundamentalsRecord[]) {
      const map = rec.data as Record<string, unknown>;
      if (!map || typeof map !== "object") continue;
      for (const key of Object.keys(map)) {
        const tx = map[key];
        if (!tx || typeof tx !== "object") continue;
        // WHY casting via Partial: the upstream shape isn't guaranteed.
        // A defensive cast + null-safe access prevents runtime crashes if the
        // EODHD snapshot ever omits a field.
        const t = tx as Partial<InsiderTx>;
        all.push({
          ownerName: t.ownerName ?? null,
          transactionCode: t.transactionCode ?? null,
          transactionDate: t.transactionDate ?? null,
          transactionAmount:
            typeof t.transactionAmount === "number" ? t.transactionAmount : null,
          transactionPrice:
            typeof t.transactionPrice === "number" ? t.transactionPrice : null,
        });
      }
    }
    // WHY sort descending (most-recent first): standard SEC Form 4 chronological
    // analyst-scan order. `null` dates sink to the bottom.
    all.sort((a, b) => {
      if (!a.transactionDate) return 1;
      if (!b.transactionDate) return -1;
      return b.transactionDate.localeCompare(a.transactionDate);
    });
    return all.slice(0, 5);
  }, [data?.records]);

  return (
    <div>
      {/* ── Section header ────────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          INSIDER ACTIVITY
        </span>
      </div>

      {/* ── Loading state ─────────────────────────────────────────────────── */}
      {/* WHY 5 skeleton rows matching live data: keeps the panel height stable
          on first paint, no jump when the data arrives. */}
      {isLoading && (
        <>
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center h-[22px] px-2 gap-2 border-b border-border/30 last:border-0"
            >
              <Skeleton className="h-3 w-12 shrink-0" />
              <Skeleton className="h-3 flex-1" />
              <Skeleton className="h-3 w-16 shrink-0" />
            </div>
          ))}
        </>
      )}

      {/* ── Error state ───────────────────────────────────────────────────── */}
      {isError && !isLoading && (
        <InlineEmptyState
          message="Insider data unavailable."
          className="px-2 py-1.5 text-[11px]"
        />
      )}

      {/* ── Empty state ───────────────────────────────────────────────────── */}
      {!isLoading && !isError && transactions.length === 0 && (
        <InlineEmptyState
          message="No recent insider transactions."
          className="px-2 py-1.5 text-[11px]"
        />
      )}

      {/* ── Rows ──────────────────────────────────────────────────────────── */}
      {!isLoading && !isError && transactions.length > 0 && (
        <>
          {transactions.map((tx, i) => {
            const display = txDisplay(tx.transactionCode);
            // WHY value display as shares × price: matches Finviz's "Cost"
            // column (shares × price = total $ moved). Compact format keeps
            // the row scannable.
            const value =
              tx.transactionAmount != null && tx.transactionPrice != null
                ? tx.transactionAmount * tx.transactionPrice
                : null;
            return (
              <div
                key={`${tx.ownerName ?? "anon"}-${tx.transactionDate ?? i}-${i}`}
                className="flex items-center h-[22px] px-2 gap-2 border-b border-border/30 last:border-0 hover:bg-muted/30"
              >
                {/* Date — fixed-width tabular for vertical alignment */}
                <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0 w-[60px]">
                  {tx.transactionDate ?? "—"}
                </span>

                {/* SEC code badge — color-coded BUY/SELL/etc. */}
                <span
                  className={`shrink-0 rounded-[2px] border border-border/40 px-1 font-mono text-[9px] uppercase ${display.colorClass}`}
                >
                  {display.label}
                </span>

                {/* Owner name — truncates if long; takes remaining space */}
                <span className="text-[11px] text-foreground truncate flex-1">
                  {tx.ownerName ?? "Unknown"}
                </span>

                {/* Shares + dollar-value (right-aligned) */}
                <span className="font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
                  {formatShares(tx.transactionAmount)}
                  {value != null ? ` · $${formatShares(value)}` : ""}
                </span>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
