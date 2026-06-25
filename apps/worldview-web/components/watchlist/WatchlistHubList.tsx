/**
 * components/watchlist/WatchlistHubList.tsx — Left rail of the watchlists workspace
 *
 * WHY THIS EXISTS
 * ---------------
 * The legacy hub rendered a static 4-column table whose "Members" column was
 * hard-wired to 0 (the list endpoint never returns members). This component is
 * the master rail of the new master-detail layout: a vertical list of selectable
 * watchlist rows, each enriched with the REAL member count and a live weighted
 * 1-day return — both pulled from the per-watchlist insights endpoint, the same
 * source that fixes the MEMBERS=0 bug.
 *
 * WHY per-row insights queries (and why it's cheap):
 *  - Each row mounts a `useAuthedQuery` against `qk.watchlists.insights(id)`.
 *  - That is the SAME cache key the detail pane uses, so selecting a row reuses
 *    the row's already-fetched data instead of issuing a second request.
 *  - TanStack de-dupes concurrent requests for the same key, and the 60s
 *    staleTime means a hub with N lists makes at most N requests per minute —
 *    acceptable for a workspace surface (vs. the old "0 for everyone" lie).
 *
 * WHO USES IT: app/(app)/watchlists/page.tsx.
 *
 * DESIGN: Terminal Dark — 28px rows, selected row gets a left accent bar +
 * subtle bg, mirroring the shell sidebar's active-item treatment.
 */

"use client";

import { useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { cn, formatPercentDirect, priceChangeClass } from "@/lib/utils";
import { formatRelativeTime } from "@/app/(app)/watchlists/hub-columns";
import type { Watchlist } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface WatchlistHubListProps {
  watchlists: Watchlist[];
  /** Currently-selected watchlist id (drives the detail pane). */
  selectedId: string | null;
  onSelect: (watchlist: Watchlist) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistHubList({
  watchlists,
  selectedId,
  onSelect,
}: WatchlistHubListProps) {
  return (
    <nav
      className="flex w-full flex-col overflow-auto"
      aria-label="Watchlists"
    >
      {watchlists.map((wl) => (
        <WatchlistHubRow
          key={wl.watchlist_id}
          watchlist={wl}
          selected={wl.watchlist_id === selectedId}
          onSelect={() => onSelect(wl)}
        />
      ))}
    </nav>
  );
}

// ── Row ────────────────────────────────────────────────────────────────────────

function WatchlistHubRow({
  watchlist,
  selected,
  onSelect,
}: {
  watchlist: Watchlist;
  selected: boolean;
  onSelect: () => void;
}) {
  const watchlistId = watchlist.watchlist_id;

  // Per-row insights — gives the REAL member count + weighted return. Shares the
  // detail pane's cache key so no duplicate fetch when this row is selected.
  const { data } = useAuthedQuery({
    queryKey: qk.watchlists.insights(watchlistId),
    queryFn: (gw) => gw.getWatchlistInsights(watchlistId),
    staleTime: 60_000,
  });

  // Until insights resolve we show the relative-updated time as the secondary
  // line; once they arrive we surface the live member count + 1d return.
  const memberCount = data?.members_count;
  const weighted = data?.weighted_return_1d ?? null;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={cn(
        // Two-line row: name on top, meta below. 44px gives room for both lines
        // at terminal density without feeling cramped.
        "flex h-11 w-full shrink-0 flex-col justify-center gap-0.5 border-b border-border/40 px-3 text-left transition-colors",
        "border-l-2", // reserve the accent-bar width so selecting doesn't shift text
        selected
          ? "border-l-primary bg-muted/15"
          : "border-l-transparent hover:bg-muted/10 focus:bg-muted/10 focus:outline-none",
      )}
    >
      {/* Name line */}
      <span className="truncate font-mono text-[11px] text-foreground">
        {watchlist.name}
      </span>

      {/* Meta line — member count + live 1d return (or fallback timestamp). */}
      <span className="flex items-center gap-2 font-mono text-[9px] tabular-nums text-muted-foreground">
        <span>
          {memberCount == null ? "—" : memberCount} {memberCount === 1 ? "member" : "members"}
        </span>
        {weighted != null ? (
          <span className={priceChangeClass(weighted)}>
            {formatPercentDirect(weighted)}
          </span>
        ) : (
          <span className="text-muted-foreground/60">
            {formatRelativeTime(watchlist.updated_at)}
          </span>
        )}
      </span>
    </button>
  );
}
