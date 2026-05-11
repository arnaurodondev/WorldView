/**
 * app/(app)/watchlists/hub-columns.ts — ColumnDef array for the Watchlists hub page
 *
 * WHY THIS EXISTS: Extracted from WatchlistsHubPage so the column definitions
 * can be unit-tested in isolation. The columns contain no closures over mutable
 * state so they are safe to define as a static constant.
 *
 * WHO USES IT: app/(app)/watchlists/page.tsx → DataTable primitive.
 * DATA SOURCE: gateway.getWatchlists() → Watchlist[] (S1 list endpoint).
 * DESIGN REFERENCE: PLAN-0059 I-1.
 */

import type { ColumnDef } from "@tanstack/react-table";
import type { Watchlist } from "@/types/api";

// ── Helpers (exported for tests) ──────────────────────────────────────────────

/**
 * formatRelativeTime — formats an ISO-8601 timestamp as a human-relative string.
 * "2h ago" / "3d ago" / "Apr 14".
 *
 * WHY relative (not absolute): watchlist users scan for recently-updated lists.
 * A relative label answers "did I touch this today?" faster than reading a date.
 */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.floor((now - then) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  if (sec < 7 * 86400) return `${Math.floor(sec / 86400)}d ago`;
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

// ── Column definitions ────────────────────────────────────────────────────────

/**
 * watchlistHubColumns — 4-column ColumnDef array for the Watchlists hub table.
 * Columns: Name | Members | Updated | Created.
 */
export const watchlistHubColumns: ColumnDef<Watchlist>[] = [
  {
    id: "name",
    accessorKey: "name",
    header: "Name",
    size: 280,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] text-foreground truncate">
        {row.original.name}
      </span>
    ),
  },
  {
    id: "member_count",
    accessorKey: "member_count",
    header: "Members",
    size: 100,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
        {row.original.member_count}
      </span>
    ),
  },
  {
    id: "updated_at",
    accessorKey: "updated_at",
    header: "Updated",
    size: 120,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
        {formatRelativeTime(row.original.updated_at)}
      </span>
    ),
  },
  {
    id: "created_at",
    accessorKey: "created_at",
    header: "Created",
    size: 120,
    cell: ({ row }) => (
      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
        {formatRelativeTime(row.original.created_at)}
      </span>
    ),
  },
];
