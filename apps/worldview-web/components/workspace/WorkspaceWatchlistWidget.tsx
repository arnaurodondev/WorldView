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

  // Step 2: Extract entity IDs from the first watchlist's members array
  const firstWatchlist = watchlists?.[0];
  // WHY filter before map: members may arrive with an empty entity_id string at
  // runtime if the watchlist was seeded with incomplete data. Filtering here prevents
  // downstream quote lookups from using "" as a key (which silently returns undefined
  // from the quotes map and renders a blank row).
  const entityIds: string[] = (firstWatchlist?.members ?? [])
    .filter((m) => Boolean(m.entity_id))
    .map((m) => m.entity_id);

  // Step 3: Fetch live quotes for those entity IDs
  // WHY entity_ids as IDs: getBatchQuotes takes entity_ids (not instrument_ids)
  // and returns quotes keyed by entity_id (matching WatchlistPanel.tsx pattern).
  const { data: quotesResp, isLoading: quotesLoading } = useQuery({
    queryKey: ["batch-quotes", entityIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(entityIds),
    enabled: !!accessToken && entityIds.length > 0,
    // WHY staleTime 0 + refetchInterval 30000: prices must always be treated as
    // potentially stale. We accept 30s intervals to balance freshness vs API load.
    staleTime: 0,
    refetchInterval: 30_000,
  });

  const isLoading = wlLoading || quotesLoading;
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

  if (entityIds.length === 0) {
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
      {entityIds.map((entityId) => {
        const q = quotes[entityId];
        // WHY fallback ticker: if quote isn't loaded yet, show a derived ticker
        // from the entity_id (e.g. "entity-aapl" → "AAPL") rather than an empty cell.
        const ticker = q?.ticker ?? entityId.replace("entity-", "").toUpperCase();
        const price = q?.price;
        const change = q?.change_pct;

        return (
          // WHY Link (not div): clicking a watchlist row navigates to the instrument
          // detail page. Using a real <a> element (via Link) gives keyboard focus,
          // screen-reader semantics, and middle-click / open-in-new-tab behaviour for
          // free — impossible with a bare <div onClick>.
          // WHY h-[22px] py-0: §0.2 row height mandate. Vertical space is controlled
          // entirely by row height — py-0 is explicit to override any Tailwind base.
          <Link
            key={entityId}
            href={`/instruments/${entityId}`}
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
