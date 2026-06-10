/**
 * components/portfolio/watchlists/WatchlistTable.tsx — Watchlist instruments table
 *
 * WHY EXTRACTED: WatchlistTable was an inner function inside WatchlistsTabPanel.tsx.
 * Extracting it keeps WatchlistsTabPanel under 400 lines and separates the table
 * rendering concern from the tab-bar + search-bar orchestration.
 *
 * WHY a table (not a flex list): financial terminal convention — fixed-width columns
 * for TICKER / NAME / PRICE / CHG% / CHG$ align perfectly across rows so analysts
 * can scan numbers vertically without eye-tracking across variable-width cells.
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
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  onRowClick: (entityId: string) => void;
  onDeleteMember: (entityId: string) => void;
  deletingEntityId: string | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistTable({
  watchlist,
  quotes,
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
      <table className="w-full border-collapse text-[11px]">
        <thead className="sticky top-0 bg-card z-10">
          <tr className="h-[22px] border-b border-border">
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
              TICKER
            </th>
            <th className="px-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground text-left font-normal">
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
            {/* Empty header for the delete button column */}
            <th className="w-8" />
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
