/**
 * app/(app)/watchlists/page.tsx — Watchlists hub (index)
 *
 * PLAN-0059 I-1: replaces the legacy redirect with a real index hub. Lists every
 * watchlist with name, member count, last-updated, and a "Create new" affordance.
 * Clicking a row navigates to /watchlists/[id] for the detail view.
 *
 * WHY a hub (not a tab inside /portfolio): the watchlists feature is
 * cross-cutting (alerts, dashboard movers, screener saved sets) — not
 * portfolio-bound. PRD-0031 §I-1 calls this out as IA correctness.
 *
 * Auth: gated by /(app)/layout.tsx which redirects to /login when no token.
 *
 * Data: TanStack Query against `gateway.getWatchlists()` (S1 list endpoint;
 * doesn't include member arrays — those load only on detail view).
 */

"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Eye, ListChecks } from "lucide-react";
import { useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import {
  DataTable,
  type DataTableContextMenuItem,
} from "@/components/ui/data-table";
import type { Watchlist } from "@/types/api";
import type { ColumnDef } from "@tanstack/react-table";
import { cn } from "@/lib/utils";

// Lazy-imported create dialog — keeps the hub bundle small for users who
// only browse without creating.
import dynamic from "next/dynamic";
const CreateWatchlistDialog = dynamic(
  () =>
    import("@/components/watchlists/CreateWatchlistDialog").then(
      (m) => m.CreateWatchlistDialog,
    ),
  { ssr: false },
);

// ── Helpers ────────────────────────────────────────────────────────────────

function formatRelativeTime(iso: string): string {
  // Formats "2026-04-30T12:00:00Z" → "2h ago" / "3d ago" / "Apr 14".
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

// ── Page ───────────────────────────────────────────────────────────────────

export default function WatchlistsHubPage() {
  const router = useRouter();
  const [createOpen, setCreateOpen] = useState(false);

  // Use the authed-query wrapper so we don't need to repeat enabled-on-token
  // boilerplate. The query factory ties this to the canonical query key tree.
  // queryFn receives the memoised gateway from the provider (PLAN-0059-C C-3).
  const { data, isLoading, isError, refetch } = useAuthedQuery({
    queryKey: qk.watchlists.list(),
    queryFn: (gw) => gw.getWatchlists(),
    staleTime: 30_000,
  });

  const watchlists = data ?? [];

  // Define columns with TanStack-style accessor configs so the DataTable's
  // multi-sort and copy-as-TSV both work out of the box.
  const columns = useMemo<ColumnDef<Watchlist>[]>(
    () => [
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
    ],
    [],
  );

  const contextMenu = useMemo<DataTableContextMenuItem<Watchlist>[]>(
    () => [
      {
        id: "view",
        label: "View members",
        icon: <Eye className="h-3 w-3" />,
        shortcut: "↵",
        onClick: (wl) => router.push(`/watchlists/${wl.watchlist_id}`),
      },
    ],
    [router],
  );

  // ── Render branches ──────────────────────────────────────────────────

  if (isLoading) {
    return (
      <PageShell onCreate={() => setCreateOpen(true)} count={null}>
        <div className="space-y-1 p-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[22px]" style={{ animationDelay: `${i * 30}ms` }} />
          ))}
        </div>
      </PageShell>
    );
  }

  if (isError) {
    return (
      <PageShell onCreate={() => setCreateOpen(true)} count={null}>
        <div className="flex flex-col items-start gap-2 p-4">
          <InlineEmptyState message="Watchlists failed to load — check connection." />
          <Button variant="outline" density="compact" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </PageShell>
    );
  }

  if (watchlists.length === 0) {
    // QA-iter1: align with the rest of the dashboard's empty-state convention
    // (left-aligned InlineEmptyState + small inline CTA). Previous centred
    // 32px-icon block read as a consumer-app pattern, not Bloomberg.
    return (
      <>
        <PageShell onCreate={() => setCreateOpen(true)} count={0}>
          <div className="flex flex-col items-start gap-2 p-4">
            <InlineEmptyState message="No watchlists yet. Group instruments to track them across dashboard, alerts, and the screener." />
            <Button density="compact" onClick={() => setCreateOpen(true)}>
              <Plus className="h-3 w-3" /> Create watchlist
            </Button>
          </div>
        </PageShell>
        {createOpen && (
          <CreateWatchlistDialog
            open={createOpen}
            onOpenChange={setCreateOpen}
            onCreated={(wl) => router.push(`/watchlists/${wl.watchlist_id}`)}
          />
        )}
      </>
    );
  }

  return (
    <>
      <PageShell onCreate={() => setCreateOpen(true)} count={watchlists.length}>
        <div className="flex flex-1 flex-col overflow-hidden">
          <DataTable<Watchlist>
            columns={columns}
            data={watchlists}
            getRowId={(wl) => wl.watchlist_id}
            density="compact"
            ariaLabel="Watchlists"
            onRowClick={(wl) => router.push(`/watchlists/${wl.watchlist_id}`)}
            contextMenu={contextMenu}
          />
        </div>
      </PageShell>
      {createOpen && (
        <CreateWatchlistDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
          onCreated={(wl) => router.push(`/watchlists/${wl.watchlist_id}`)}
        />
      )}
    </>
  );
}

// ── Layout shell ───────────────────────────────────────────────────────────

function PageShell({
  children,
  onCreate,
  count,
}: {
  children: React.ReactNode;
  onCreate: () => void;
  count: number | null;
}) {
  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Section header — matches the institutional terminal density. */}
      <div className="flex h-7 shrink-0 items-center gap-2 border-b border-border px-3">
        <ListChecks className="h-3 w-3 text-muted-foreground" aria-hidden />
        <h1 className={cn("font-mono text-[11px] uppercase tracking-[0.08em] text-foreground")}>
          Watchlists
        </h1>
        {count !== null && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
            {count}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <Button density="compact" onClick={onCreate}>
            <Plus className="h-3 w-3" /> New
          </Button>
        </div>
      </div>
      {children}
    </div>
  );
}
