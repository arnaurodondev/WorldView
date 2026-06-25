/**
 * app/(app)/watchlists/page.tsx — Watchlists workspace (master-detail)
 *
 * WHAT CHANGED (and WHY)
 * ----------------------
 * The legacy page was a 3-row hub table floating in ~92% empty black, and every
 * row read "MEMBERS 0". Two problems:
 *
 *   1. MEMBERS=0 BUG — the hub fed off `getWatchlists()` (S1 `GET /v1/watchlists`),
 *      which returns watchlist METADATA ONLY (no members array). The gateway
 *      mapper then defaults `member_count` to the length of an empty array → 0
 *      for every list. Meanwhile the shell sidebar fetches the dedicated
 *      `/watchlists/{id}/members` (and we now use `/watchlists/{id}/insights`),
 *      which is why the sidebar showed live members while the hub showed zero.
 *
 *   2. DEAD SPACE — a 4-column, 3-row table used <8% of a finance terminal's
 *      screen. There was nothing to act on.
 *
 * THE REBUILD — a master-detail workspace:
 *   - LEFT RAIL (WatchlistHubList): every watchlist, each row enriched with its
 *     REAL member count + live weighted-1d return (from the insights endpoint).
 *   - RIGHT PANE (WatchlistDetailPane): the selected list's live snapshot —
 *     stats strip, insights card, and a dense member table with price / day
 *     change / sector / news. Fills the width like a real terminal surface.
 *
 * Create / rename / delete affordances are preserved (New button here; rename &
 * delete live on the deep /watchlists/[id] page reachable via the pane's "Open").
 *
 * Auth: gated by /(app)/layout.tsx which redirects to /login when no token.
 * Data: TanStack Query via `useAuthedQuery` against `gateway.getWatchlists()`.
 */

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, ListChecks } from "lucide-react";
import { useAuthedQuery } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { WatchlistHubList } from "@/components/watchlist/WatchlistHubList";
import { WatchlistDetailPane } from "@/components/watchlist/WatchlistDetailPane";
import { cn } from "@/lib/utils";

// Lazy-imported create dialog — keeps the workspace bundle small for users who
// only browse without creating.
import dynamic from "next/dynamic";
const CreateWatchlistDialog = dynamic(
  () =>
    import("@/components/watchlists/CreateWatchlistDialog").then(
      (m) => m.CreateWatchlistDialog,
    ),
  { ssr: false },
);

// ── Page ───────────────────────────────────────────────────────────────────

export default function WatchlistsHubPage() {
  const router = useRouter();
  const [createOpen, setCreateOpen] = useState(false);

  // Which watchlist's snapshot is shown in the right pane. null = none chosen
  // yet (we auto-select the first once the list loads — see the effect below).
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useAuthedQuery({
    queryKey: qk.watchlists.list(),
    queryFn: (gw) => gw.getWatchlists(),
    staleTime: 30_000,
  });

  const watchlists = data ?? [];

  // Auto-select the first watchlist once data arrives so the workspace is never
  // half-empty on entry. We only set it when nothing is selected OR the selected
  // id no longer exists (e.g. it was deleted on the detail page) — this keeps the
  // user's manual selection sticky across refetches.
  useEffect(() => {
    if (watchlists.length === 0) return;
    const stillExists = selectedId && watchlists.some((w) => w.watchlist_id === selectedId);
    if (!stillExists) {
      setSelectedId(watchlists[0]!.watchlist_id);
    }
  }, [watchlists, selectedId]);

  const selected = watchlists.find((w) => w.watchlist_id === selectedId) ?? null;

  // ── Render branches ──────────────────────────────────────────────────

  if (isLoading) {
    return (
      <PageShell onCreate={() => setCreateOpen(true)} count={null}>
        <div className="space-y-1 p-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[44px]" style={{ animationDelay: `${i * 30}ms` }} />
          ))}
        </div>
      </PageShell>
    );
  }

  if (isError) {
    return (
      <PageShell onCreate={() => setCreateOpen(true)} count={null}>
        <div className="flex flex-col items-start gap-2 p-3">
          <InlineEmptyState message="Watchlists failed to load — check connection." />
          <Button variant="outline" density="compact" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </PageShell>
    );
  }

  if (watchlists.length === 0) {
    return (
      <>
        <PageShell onCreate={() => setCreateOpen(true)} count={0}>
          <div className="flex flex-col items-start gap-2 p-3">
            <InlineEmptyState message="No watchlists yet. Group instruments to track them across dashboard, alerts, and the screener." />
            <Button density="compact" onClick={() => setCreateOpen(true)}>
              <Plus className="h-3 w-3" strokeWidth={1.5} /> Create watchlist
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
        {/* Master-detail body. The rail is a fixed-ish column; the pane flexes
            to fill ALL remaining width — that is what kills the old dead space. */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left rail — 18rem (≈288px) is wide enough for "EV & Clean Energy"
              names + the meta line without truncating the common cases. */}
          <aside className="flex w-72 shrink-0 flex-col overflow-hidden border-r border-border">
            <WatchlistHubList
              watchlists={watchlists}
              selectedId={selectedId}
              onSelect={(wl) => setSelectedId(wl.watchlist_id)}
            />
          </aside>

          {/* Right pane — live snapshot of the selected watchlist. */}
          {selected ? (
            <WatchlistDetailPane key={selected.watchlist_id} watchlist={selected} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-4">
              <InlineEmptyState message="Select a watchlist to view its members." />
            </div>
          )}
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
        <ListChecks className="h-3 w-3 text-muted-foreground" aria-hidden strokeWidth={1.5} />
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
            <Plus className="h-3 w-3" strokeWidth={1.5} /> New
          </Button>
        </div>
      </div>
      {children}
    </div>
  );
}
