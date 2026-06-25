/**
 * components/watchlist/WatchlistDetailPane.tsx — Right pane of the watchlists workspace
 *
 * WHY THIS EXISTS
 * ---------------
 * The legacy /watchlists page was a 3-row hub table floating in ~92% empty black.
 * This pane is the "workspace" half of the new master-detail layout: when the
 * user selects a watchlist in the left rail, this pane fills the available width
 * with a real, live snapshot of that list — a stats strip (members / weighted
 * 1d return / active alerts / top mover), the compact WatchlistInsightsPanel, and
 * a dense LIVE member table (price, day change, sector, news).
 *
 * DATA SOURCE: `GET /v1/watchlists/{id}/insights` via gateway.getWatchlistInsights().
 * This is the SAME endpoint that fixes the MEMBERS=0 bug — it returns the real
 * `members_count` plus a `movers[]` array carrying live quotes the hub list
 * endpoint never provides. See WatchlistMemberRows.tsx for the full root-cause note.
 *
 * WHO USES IT: app/(app)/watchlists/page.tsx (master-detail composition).
 *
 * NAVIGATION: the header carries an "Open" affordance that routes to the full
 * /watchlists/[id] detail page (rename / delete / per-member remove live there);
 * this pane is the at-a-glance preview, not the management surface.
 */

"use client";

import { useRouter } from "next/navigation";
import { ArrowUpRight, Bell } from "lucide-react";
import { useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { WatchlistInsightsPanel } from "@/components/watchlist/WatchlistInsightsPanel";
import { WatchlistMemberRows } from "@/components/watchlist/WatchlistMemberRows";
import { cn, formatPercentDirect, priceChangeClass } from "@/lib/utils";
import type { Watchlist } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface WatchlistDetailPaneProps {
  /** The watchlist selected in the left rail. */
  watchlist: Watchlist;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistDetailPane({ watchlist }: WatchlistDetailPaneProps) {
  const router = useRouter();
  const watchlistId = watchlist.watchlist_id;

  // Insights drive the whole pane: real member count + live movers + weighted
  // return + alert count. staleTime/refetch mirror the WatchlistInsightsPanel
  // (60s "dashboard pulse") so both share the same cache slot and never diverge.
  const { data, isLoading, isError, refetch } = useAuthedQuery({
    queryKey: qk.watchlists.insights(watchlistId),
    queryFn: (gw) => gw.getWatchlistInsights(watchlistId),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  return (
    <section className="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
      {/* ── Pane header ─────────────────────────────────────────────────────
          Watchlist name + a stats strip + an "Open" button that deep-links to
          the management page. h-9 (taller than the 28px list-header) gives the
          stats room without crowding. */}
      <header className="flex h-9 shrink-0 items-center gap-3 border-b border-border px-3">
        <h2 className="truncate font-mono text-[12px] uppercase tracking-[0.08em] text-foreground">
          {watchlist.name}
        </h2>

        {/* Live stats strip — only meaningful once insights resolve. */}
        {data && (
          <div className="flex items-center gap-3">
            <Stat label="Members" value={String(data.members_count)} />
            <Stat
              label="1D"
              value={formatPercentDirect(data.weighted_return_1d)}
              valueClass={priceChangeClass(data.weighted_return_1d)}
            />
            {data.alerts_count > 0 && (
              <span className="flex items-center gap-1 font-mono text-[10px] text-warning">
                <Bell className="h-2.5 w-2.5" strokeWidth={2} aria-hidden />
                {data.alerts_count}
              </span>
            )}
          </div>
        )}

        <div className="ml-auto">
          <Button
            variant="outline"
            density="compact"
            onClick={() => router.push(`/watchlists/${watchlistId}`)}
          >
            Open <ArrowUpRight className="h-3 w-3" strokeWidth={1.5} />
          </Button>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────────
          Three branches: loading skeleton, error retry, and the live content. */}
      {isLoading ? (
        <div className="space-y-1 p-3">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-6" style={{ animationDelay: `${i * 30}ms` }} />
          ))}
        </div>
      ) : isError ? (
        <div className="flex flex-col items-start gap-2 p-3">
          <InlineEmptyState message="Watchlist snapshot failed to load — check connection." />
          <Button variant="outline" density="compact" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      ) : data && data.members_count === 0 ? (
        // Genuinely-empty watchlist — guide the user to add instruments. This is
        // NOT the MEMBERS=0 bug (which was every list reading 0); here the count
        // is authoritative because it comes from the insights endpoint.
        <div className="flex flex-col items-start gap-2 p-3">
          <InlineEmptyState message="This watchlist has no instruments yet. Add them from any instrument page or the screener." />
          <Button
            variant="outline"
            density="compact"
            onClick={() => router.push(`/watchlists/${watchlistId}`)}
          >
            Manage watchlist
          </Button>
        </div>
      ) : data ? (
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Compact insights card (top mover / top news / weighted return).
              Padded so it doesn't butt against the table grid below. */}
          <div className="shrink-0 p-2">
            <WatchlistInsightsPanel watchlistId={watchlistId} />
          </div>

          {/* The live member grid fills the remaining height. */}
          <WatchlistMemberRows movers={data.movers} />
        </div>
      ) : null}
    </section>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

/** A single label/value pair in the header stats strip. */
function Stat({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground/70">
        {label}
      </span>
      <span className={cn("font-mono text-[11px] tabular-nums text-foreground", valueClass)}>
        {value}
      </span>
    </span>
  );
}
