/**
 * components/portfolio/RecentActivityFeed.tsx — Unified activity stream (PLAN-0053 T-B-2-05)
 *
 * WHY THIS EXISTS: A trader returning to the platform after a few hours wants
 * a single chronological answer to "what happened on my account?". Today the
 * Transactions table answers half the question (executions) and the brokerage
 * sync card answers the other half (data freshness). Merging the two into one
 * timeline tells the full story in one glance — broker syncs interleaved with
 * the fills they pulled in.
 *
 * WHY 20 TX + 5 SYNC EVENTS:
 *   20 transactions ≈ a full day's worth of activity for an active retail
 *   trader. 5 sync events covers ~24h on the default 4-hour sync cadence.
 *   Bigger windows belong on the dedicated Transactions tab — this widget is
 *   a "recent" feed by design.
 *
 * WHY NO REACT-VIRTUAL FOR ~25 ROWS:
 *   The dependency exists in the bundle (used by SemanticHoldingsTable) but
 *   spinning up a virtualizer for ≤25 fixed rows is pure overhead — DOM
 *   measurement, ResizeObserver wiring, position-absolute children. A flat
 *   slice is faster AND keeps the component tree readable. We get the same
 *   net behaviour: smooth scroll, fixed footprint.
 *
 * WHO USES IT: portfolio/page.tsx — Holdings tab (mountable below cash card)
 * DATA SOURCES:
 *   - getTransactions(portfolioId, { limit: 20 })            — last 20 txs
 *   - getBrokerageConnections(portfolioId)                   — sync events
 * DESIGN REFERENCE: PLAN-0053 §T-B-2-05
 */

"use client";
// WHY "use client": uses useQuery, useMemo, and renders icons.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, DollarSign, RefreshCcw } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { formatRelativeTime, formatPrice, cn } from "@/lib/utils";
import type { Transaction, BrokerageConnection } from "@/types/api";

// ── Types ────────────────────────────────────────────────────────────────────

export interface RecentActivityFeedProps {
  /** Portfolio UUID. Component auto-hides when null/undefined (no portfolio). */
  portfolioId: string | null | undefined;
}

/**
 * FeedRow — discriminated union covering both surfaced activity types.
 *
 * WHY a tagged union (not two parallel arrays in the JSX): keeping the merge
 * + sort logic typed makes it obvious we sort by `timestamp` regardless of
 * row kind. A bug where a sync event got compared against a tx executed_at
 * with different formats would surface immediately at the type boundary.
 */
type FeedRow =
  | { kind: "tx"; timestamp: string; tx: Transaction }
  | { kind: "sync"; timestamp: string; conn: BrokerageConnection };

// Hard caps. Spec says 20 txs + 5 sync events. Defining them as named
// constants keeps the magic numbers out of the JSX and easy to tune.
const TX_LIMIT = 20;
const SYNC_LIMIT = 5;

// ── Component ────────────────────────────────────────────────────────────────

export function RecentActivityFeed({ portfolioId }: RecentActivityFeedProps) {
  const { accessToken } = useAuth();

  // ── Transactions (last 20) ──────────────────────────────────────────────
  // WHY shared queryKey shape with the Transactions tab: TanStack Query
  // dedupes inflight calls — the dashboard widget and the full-tab table
  // share the underlying response if both are mounted.
  const { data: txs, isLoading: txLoading } = useQuery({
    queryKey: ["activity-feed-transactions", portfolioId, TX_LIMIT],
    queryFn: () =>
      createGateway(accessToken).getTransactions(portfolioId!, {
        limit: TX_LIMIT,
        offset: 0,
      }),
    enabled: !!accessToken && !!portfolioId,
    // 60s — transactions only change on broker sync (every few hours), 1 min
    // is more than enough freshness without hammering S1.
    staleTime: 60_000,
  });

  // ── Brokerage sync events ──────────────────────────────────────────────
  // We approximate "sync events" as the per-connection last_synced_at field
  // — there is no per-event audit endpoint today and adding one is out of
  // scope for this widget. Each connection contributes at most ONE row
  // (its most recent sync) which keeps the feed clean.
  const { data: connections, isLoading: connLoading } = useQuery({
    queryKey: ["activity-feed-connections", portfolioId],
    queryFn: () => createGateway(accessToken).getBrokerageConnections(portfolioId!),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // ── Merge + sort by timestamp desc ─────────────────────────────────────
  const rows: FeedRow[] = useMemo(() => {
    const out: FeedRow[] = [];

    // Transactions
    for (const tx of txs?.transactions ?? []) {
      out.push({ kind: "tx", timestamp: tx.executed_at, tx });
    }

    // Sync events — only include connections that have actually synced.
    // WHY filter out null last_synced_at: an unsynced connection isn't an
    // "event" yet — there's no point cluttering the feed with "never synced"
    // rows.
    const synced = (connections ?? [])
      .filter((c) => !!c.last_synced_at)
      .slice()
      .sort(
        (a, b) =>
          Date.parse(b.last_synced_at!) - Date.parse(a.last_synced_at!),
      )
      .slice(0, SYNC_LIMIT);
    for (const conn of synced) {
      out.push({ kind: "sync", timestamp: conn.last_synced_at!, conn });
    }

    // Sort desc by ISO 8601 timestamp. String compare works for ISO UTC
    // because the format is lexicographically sortable.
    return out.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
  }, [txs, connections]);

  const isLoading = txLoading || connLoading;

  // ── Render ──────────────────────────────────────────────────────────────
  if (!portfolioId) return null;

  return (
    <div
      className="flex flex-col bg-background"
      data-testid="recent-activity-feed"
    >
      {/* Section header — matches the rest of the portfolio page chrome */}
      <div className="flex h-6 shrink-0 items-center border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          RECENT ACTIVITY
        </span>
      </div>

      {/* Body */}
      <div className="max-h-[340px] overflow-auto">
        {isLoading && (
          <div className="divide-y divide-border/30">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="flex h-7 items-center gap-2 px-2">
                <Skeleton className="h-3 w-3" />
                <Skeleton className="h-3 w-[40px]" />
                <Skeleton className="h-3 flex-1" />
                <Skeleton className="h-3 w-[60px]" />
              </div>
            ))}
          </div>
        )}

        {!isLoading && rows.length === 0 && (
          <div className="px-3 py-2">
            <InlineEmptyState message="No recent activity" />
          </div>
        )}

        {!isLoading && rows.length > 0 && (
          <div className="divide-y divide-border/30">
            {rows.map((row) =>
              row.kind === "tx" ? (
                <TxRow key={`tx-${row.tx.transaction_id}`} tx={row.tx} />
              ) : (
                <SyncRow
                  key={`sync-${row.conn.connection_id}-${row.timestamp}`}
                  conn={row.conn}
                  syncedAt={row.timestamp}
                />
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Row sub-components ───────────────────────────────────────────────────────

/**
 * TxRow — single transaction row.
 *
 * WHY discriminate icon by tx.type: BUY/SELL share a chart-arrow visual, but
 * DIVIDEND is conceptually a cash event — a $ icon reads correctly even when
 * the user can't see the BUY/SELL color. This is the same affordance pattern
 * used in the TransactionsTable badge.
 */
function TxRow({ tx }: { tx: Transaction }) {
  // Icon + colour pairing per type — explicit map (not a switch) keeps the
  // visual contract auditable in one place.
  const iconCfg = {
    BUY: { Icon: ArrowUp, color: "text-positive" },
    SELL: { Icon: ArrowDown, color: "text-negative" },
    DIVIDEND: { Icon: DollarSign, color: "text-primary" },
  } as const;
  const { Icon, color } = iconCfg[tx.type];

  // For DIVIDEND, qty/price are zero — total comes from the broker `amount`.
  const total =
    tx.type === "DIVIDEND"
      ? (tx.amount ?? 0)
      : tx.quantity * tx.price;

  return (
    <div
      className="flex h-7 items-center gap-2 px-2 transition-colors hover:bg-muted/30"
      // a11y: surface the row's full meaning to screen readers in one pass.
      aria-label={`${tx.type} ${tx.ticker || ""} ${tx.quantity || ""} at ${
        tx.price ? formatPrice(tx.price) : ""
      }`}
    >
      <Icon className={cn("h-3 w-3 shrink-0", color)} aria-hidden="true" />
      {/* WHY font-semibold (was font-bold): 700-weight at 11px causes blotchy subpixel
          rendering on dark themes — 600-weight is the maximum for terminal chrome text
          at small sizes (Bloomberg density rule) */}
      <span className="w-[44px] shrink-0 font-mono text-[11px] font-semibold tabular-nums text-foreground">
        {tx.ticker || "—"}
      </span>
      <span className="min-w-0 flex-1 truncate font-mono text-[10px] tabular-nums text-muted-foreground">
        {tx.type === "DIVIDEND"
          ? "Dividend"
          : `${tx.quantity.toLocaleString("en-US")} @ ${formatPrice(tx.price)}`}
      </span>
      <span className="shrink-0 font-mono text-[11px] tabular-nums text-foreground">
        {total > 0 ? formatPrice(total) : "—"}
      </span>
      <span className="w-[68px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {formatRelativeTime(tx.executed_at)}
      </span>
    </div>
  );
}

/**
 * SyncRow — broker-sync event row.
 *
 * WHY a distinct visual from tx rows: sync events are infrastructure, not
 * trades. The cog icon + muted label make them easy to skim past when the
 * user is hunting for executions but easy to find when troubleshooting a
 * stale-data problem.
 */
function SyncRow({
  conn,
  syncedAt,
}: {
  conn: BrokerageConnection;
  syncedAt: string;
}) {
  const broker = conn.brokerage_name ?? "Brokerage";
  return (
    <div
      className="flex h-7 items-center gap-2 bg-muted/10 px-2"
      aria-label={`${broker} synced ${formatRelativeTime(syncedAt)}`}
    >
      <RefreshCcw className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="w-[44px] shrink-0 font-mono text-[10px] uppercase tabular-nums text-muted-foreground">
        SYNC
      </span>
      <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
        {broker} — {conn.status}
      </span>
      <span className="w-[68px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {formatRelativeTime(syncedAt)}
      </span>
    </div>
  );
}
