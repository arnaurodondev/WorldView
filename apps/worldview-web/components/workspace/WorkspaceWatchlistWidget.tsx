/**
 * components/workspace/WorkspaceWatchlistWidget.tsx — Live watchlist ticker table
 *
 * WHY THIS EXISTS: Day traders need live price monitoring in the workspace alongside
 * their chart and screener. This widget fetches the user's first watchlist and shows
 * live bid prices with 30-second auto-refresh — enough freshness without hammering S9.
 *
 * WHY 4 COLUMNS ONLY: In a workspace panel (~400px wide), 4 columns (Ticker/Price/
 * Change%/MktCap) is the maximum readable density. More columns would require
 * horizontal scrolling, which breaks the glanceability mandate for terminal UIs.
 *
 * WHO USES IT: WorkspacePanelContainer when panel.type === "watchlist"
 * DATA SOURCE: GET /v1/watchlists + POST /v1/quotes/batch (S9 gateway)
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel widgets, §0.2 22px row height, §0.1 typography
 */

"use client";
// WHY "use client": uses TanStack Query (browser-only data fetching and caching)

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

// ── Formatting helpers ─────────────────────────────────────────────────────────

/** Format a percentage change with sign and 2 decimal places */
function formatPct(val: number | null | undefined): string {
  if (val == null) return "—";
  const pct = val * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

/** Color class for a price change — green for positive, red for negative */
function changeColor(val: number | null | undefined): string {
  if (val == null) return "text-muted-foreground";
  if (val > 0) return "text-positive";
  if (val < 0) return "text-negative";
  return "text-muted-foreground";
}

// ── Component ──────────────────────────────────────────────────────────────────

export function WorkspaceWatchlistWidget() {
  const { accessToken } = useAuth();

  // Step 1: Fetch watchlists to get the ticker list
  const { data: watchlists, isLoading: wlLoading } = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    // WHY 30s: watchlist membership changes infrequently — 30s is more than fresh enough
    staleTime: 30_000,
  });

  const firstWatchlist = watchlists?.[0];

  // Step 2: Fetch the members of the active watchlist via the dedicated endpoint.
  // WHY NOT firstWatchlist?.members: getWatchlists() returns members:[] (list
  // endpoint intentionally omits members for performance). We must call
  // /watchlists/{id}/members to get the actual ticker list; otherwise all
  // instrument_ids are empty and the quotes query never fires.
  const { data: membersData, isLoading: membersLoading } = useQuery({
    queryKey: ["workspace-watchlist-members", firstWatchlist?.watchlist_id],
    queryFn: () =>
      createGateway(accessToken).getWatchlistMembers(
        firstWatchlist!.watchlist_id,
      ),
    enabled: !!accessToken && !!firstWatchlist?.watchlist_id,
    staleTime: 30_000,
  });

  // WHY instrument_id (not entity_id): POST /v1/quotes/batch expects instrument_ids.
  const members = membersData ?? [];
  const instrumentIds: string[] = members
    .map((m) => m.instrument_id)
    .filter((id): id is string => id !== null);

  // Step 3: Fetch live quotes for instrument IDs
  const { data: quotesResp, isLoading: quotesLoading } = useQuery({
    queryKey: ["workspace-batch-quotes", instrumentIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(instrumentIds),
    enabled: !!accessToken && instrumentIds.length > 0,
    // WHY staleTime 0 + refetchInterval 30000: prices must always be treated as
    // potentially stale. We accept 30s intervals to balance freshness vs API load.
    staleTime: 0,
    refetchInterval: 30_000,
  });

  const isLoading = wlLoading || membersLoading || quotesLoading;
  const quotes = quotesResp?.quotes ?? {};

  if (isLoading) {
    return (
      <div className="space-y-px">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-2 px-2 h-[22px]">
            <Skeleton className="h-2.5 w-10" style={{ animationDelay: `${i * 30}ms` }} />
            <Skeleton className="h-2.5 w-16 ml-auto" style={{ animationDelay: `${i * 30 + 15}ms` }} />
          </div>
        ))}
      </div>
    );
  }

  if (!firstWatchlist) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        No watchlist yet.{" "}
        <Link href="/portfolio" className="text-primary hover:text-primary/80">
          Create one →
        </Link>
      </p>
    );
  }

  if (!membersLoading && instrumentIds.length === 0) {
    return (
      <p className="px-2 py-1 text-[11px] text-muted-foreground">
        Watchlist is empty. Add symbols via Portfolio.
      </p>
    );
  }

  return (
    <div className="divide-y divide-border/30">
      {/* Section header (§0.9) */}
      <div className="flex h-6 items-center border-b border-border px-2">
        {/* WHY font-mono: ADR-F-15 — section labels use IBM Plex Mono */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          {firstWatchlist.name}
        </span>
      </div>

      {/* Column headers — §0.8 column header contract (3 cols: Ticker/Price/Chg%) */}
      <div className="flex items-center px-2 h-[22px] border-b border-border">
        <span className="w-10 text-left text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Ticker</span>
        <span className="flex-1 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Price</span>
        <span className="w-14 text-right text-[10px] uppercase tracking-[0.08em] text-muted-foreground">Chg%</span>
      </div>

      {/* Quote rows — 22px each */}
      {members.map((member) => {
        const q = member.instrument_id ? quotes[member.instrument_id] : undefined;
        const ticker = member.ticker ?? q?.ticker ?? member.entity_id.slice(0, 6).toUpperCase();
        const price = q?.price;
        const change = q?.change_pct;

        return (
          <Link
            key={member.entity_id}
            href={`/instruments/${member.entity_id}`}
            className="flex items-center px-2 h-[22px] hover:bg-muted/40 text-foreground"
          >
            {/* Ticker — monospace, left-aligned */}
            <span className="w-10 truncate font-mono text-[11px] tabular-nums font-medium text-foreground">
              {ticker}
            </span>
            {/* Price — right-aligned, monospace */}
            <span className="flex-1 text-right font-mono text-[11px] tabular-nums text-foreground">
              {price != null ? price.toFixed(2) : "—"}
            </span>
            {/* Change% — semantic color (positive/negative) */}
            <span className={cn("w-14 text-right font-mono text-[11px] tabular-nums", changeColor(change))}>
              {formatPct(change)}
            </span>
          </Link>
        );
      })}
    </div>
  );
}
