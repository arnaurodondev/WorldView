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

import { InlineEmptyState } from "@/components/data/InlineEmptyState";
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
    // WHY centered wrapper (B-5): InlineEmptyState rendered raw collapsed to a
    // tiny inline element at the top of a tall container, leaving most of the
    // tab pane visually empty. py-8 + flex-centering puts the message in the
    // optical center of the empty area.
    return (
      <div className="flex flex-1 items-center justify-center py-8">
        {/* R1 sprint copy: leads with the value proposition ("track them
            here") and keeps the actionable hint pointing at the AddSymbolBar
            rendered directly above this table. */}
        <InlineEmptyState message="Add tickers to track them here — search above to add your first symbol." />
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
