/**
 * components/portfolio/watchlists/WatchlistTable.tsx — Watchlist instruments table
 *
 * WHY EXTRACTED: WatchlistTable was an inner function inside WatchlistsTabPanel.tsx.
 * Extracting it keeps WatchlistsTabPanel under 400 lines and separates the table
 * rendering concern from the tab-bar + search-bar orchestration.
 *
 * WHY a table (not a flex list): financial terminal convention — fixed-width columns
 * align perfectly across rows so analysts can scan numbers vertically without
 * eye-tracking across variable-width cells.
 *
 * 2026-06-10 density pass (user verdict: the watchlist tab "feels empty"):
 *   - Group header row: "{name} · N TICKERS" accent header above the table so
 *     the active list is identifiable without looking back at the tab bar.
 *   - SPARK column: 5-day close sparkline per row (batch sparklines endpoint,
 *     fetched once per watchlist in WatchlistsTabPanel).
 *   - VOL column: latest session volume from the live quote (nullable on the
 *     dev quote feed → "—", never a fabricated figure).
 *   - Open-instrument affordance: explicit ↗ button per row (the whole row
 *     already navigates; the icon makes the affordance discoverable).
 *   - 52-WEEK POSITION mini-bar: DEFERRED — 52w high/low is not available
 *     from the batch quote or sparkline endpoints; deriving it would need a
 *     per-member fundamentals call (N round-trips — not "cheap" per brief).
 *
 * WHO USES IT: WatchlistsTabPanel — never directly by pages.
 */

"use client";
// WHY "use client": renders WatchlistMemberRow which uses client-side useState.

// R3 polish (DS §15.12): shared EmptyState primitive replaces
// InlineEmptyState for the no-tickers state — icon gives instant category.
import { EmptyState } from "@/components/primitives/EmptyState";
// ListPlus = "add to a list" category icon — points at the AddSymbolBar above.
import { ListPlus } from "lucide-react";
import type { Watchlist } from "@/types/api";
import { WatchlistMemberRow } from "./WatchlistMemberRow";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WatchlistTableProps {
  watchlist: Watchlist;
  /** Live quotes keyed by instrument_id. volume optional (see panel docs). */
  quotes: Record<
    string,
    { price: number; change: number; change_pct: number; volume?: number | null }
  >;
  /**
   * 5-day close arrays keyed by instrument_id (batch sparklines endpoint).
   * Optional — undefined while loading / on error → rows render the dotted
   * "no data" line via the Sparkline primitive (never a blank cell).
   */
  series?: Record<string, number[]>;
  onRowClick: (entityId: string) => void;
  onDeleteMember: (entityId: string) => void;
  deletingEntityId: string | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistTable({
  watchlist,
  quotes,
  series,
  onRowClick,
  onDeleteMember,
  deletingEntityId,
}: WatchlistTableProps) {
  const members = watchlist.members;

  if (members.length === 0) {
    // WHY centered wrapper (B-5): an inline empty state rendered raw collapsed
    // to a tiny element at the top of a tall container, leaving most of the
    // tab pane visually empty. py-8 + flex-centering puts the message in the
    // optical center of the empty area.
    // R3 polish (DS §15.12): migrated onto the shared EmptyState primitive —
    // named "no watchlist tickers" state; copy lives in
    // lib/copy/empty-states.ts (portfolio.watchlist-no-tickers) and still
    // points at the AddSymbolBar rendered directly above this table.
    return (
      <div
        data-testid="watchlist-empty-state"
        className="flex flex-1 items-center justify-center py-8"
      >
        <EmptyState
          condition="empty-cold-start"
          copyKey="portfolio.watchlist-no-tickers"
          icon={ListPlus}
        />
      </div>
    );
  }

  return (
    <div className="overflow-auto">
      {/* ── Group header (2026-06-10 density pass): name + member count.
          22px accent-header convention — identifies the active list inline
          so the user never has to glance back at the tab bar. */}
      <div
        data-testid="watchlist-group-header"
        className="flex h-[22px] items-center justify-between border-b border-border bg-card px-2"
      >
        <span className="truncate text-[10px] uppercase tracking-[0.06em] text-muted-foreground" title={watchlist.name}>
          {watchlist.name}
        </span>
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
          {members.length} ticker{members.length === 1 ? "" : "s"}
        </span>
      </div>

      <table className="w-full border-collapse text-[11px]">
        <thead className="sticky top-0 bg-card z-10">
          <tr className="h-[22px] border-b border-border">
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              TICKER
            </th>
            {/* NAME is the flex column — no width cap (2026-06-10 truncation
                fix); it absorbs whatever the fixed numeric columns leave. */}
            <th className="w-auto px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              NAME
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              PRICE
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              CHG%
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              CHG$
            </th>
            {/* SPARK — 5-day mini-trend (density pass). Centered to bin the
                SVG with its label, same convention as the holdings table. */}
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-center font-normal">
              5D
            </th>
            {/* VOL — latest session volume from the quote (nullable). */}
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-right font-normal">
              VOL
            </th>
            {/* Empty header for the open + delete action buttons column */}
            <th className="w-14" />
          </tr>
        </thead>

        <tbody className="divide-y divide-border/30">
          {members.map((m) => {
            const quote = m.instrument_id ? quotes[m.instrument_id] : undefined;
            return (
              <WatchlistMemberRow
                key={m.entity_id}
                member={m}
                quote={quote}
                // 5-day closes for this row's sparkline (undefined → dotted
                // no-data line inside the Sparkline primitive).
                sparkline={
                  m.instrument_id ? series?.[m.instrument_id] : undefined
                }
                onRowClick={onRowClick}
                onDelete={onDeleteMember}
                isDeleting={deletingEntityId === m.entity_id}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
