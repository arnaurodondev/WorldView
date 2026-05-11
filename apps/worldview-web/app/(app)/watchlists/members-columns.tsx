/**
 * app/(app)/watchlists/members-columns.tsx — ColumnDef array for watchlist detail page
 *
 * WHY THIS EXISTS: Extracted from WatchlistDetailPage so the column definitions
 * can be unit-tested in isolation. The columns contain no closures over mutable
 * mutation state (removeMemberMut lives in the contextMenu, not the columns),
 * so they are safe to define as a static constant.
 *
 * WHO USES IT: app/(app)/watchlists/[id]/page.tsx → DataTable primitive.
 * DATA SOURCE: gateway.getWatchlist(id) → WatchlistMember[] (S1 detail endpoint).
 * DESIGN REFERENCE: PLAN-0059 I-1.
 */

import type { ColumnDef } from "@tanstack/react-table";
import type { WatchlistMember } from "@/types/api";

// ── Column definitions ────────────────────────────────────────────────────────

/**
 * watchlistMembersColumns — 4-column ColumnDef array for the watchlist detail table.
 * Columns: Ticker | Name | Status | Added.
 */
export const watchlistMembersColumns: ColumnDef<WatchlistMember>[] = [
  {
    id: "ticker",
    accessorKey: "ticker",
    header: "Ticker",
    size: 80,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-primary truncate">
        {row.original.ticker ?? "—"}
      </span>
    ),
  },
  {
    id: "name",
    accessorKey: "name",
    header: "Name",
    size: 240,
    cell: ({ row }) => (
      <span className="text-[11px] text-foreground truncate">
        {row.original.name}
      </span>
    ),
  },
  {
    id: "resolution",
    accessorKey: "resolution",
    header: "Status",
    size: 90,
    cell: ({ row }) => {
      const s = row.original.resolution ?? "resolved";
      if (s === "pending") {
        return (
          <span className="rounded-[2px] bg-warning/15 px-1 font-mono text-[10px] uppercase tracking-wider text-warning">
            resolving
          </span>
        );
      }
      return (
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          ok
        </span>
      );
    },
  },
  {
    id: "added_at",
    accessorKey: "added_at",
    header: "Added",
    size: 100,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
        {new Date(row.original.added_at).toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
          timeZone: "UTC",
        })}
      </span>
    ),
  },
];
