/**
 * components/portfolio/WatchlistsTabPanel.tsx — Multi-watchlist panel orchestrator
 *
 * WHY THIS EXISTS: Traders maintain multiple watchlists (e.g., "Earnings Watch",
 * "Tech Long Ideas", "Shorts"). A single combined view obscures which thesis each
 * instrument belongs to. Tab per watchlist preserves that mental model.
 *
 * WHY shadcn Tabs (not custom): Radix Tabs handles keyboard navigation (arrow keys),
 * focus management, and aria-selected — all required for professional finance UX
 * where power users prefer keyboard over mouse.
 *
 * WHY search-to-add: traders discover instruments in the screener or news, then
 * want to add them to a watchlist immediately. An inline search bar in the watchlist
 * eliminates the round-trip to another page.
 *
 * WHY delete member on hover only: showing a delete button on every row adds visual
 * noise. Revealing it on hover follows the Bloomberg convention: destructive actions
 * are discoverable but not prominent during the primary read workflow.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Watchlist tab content
 * DATA SOURCE: getWatchlists() → per-tab getBatchQuotes() via parent
 * DESIGN REFERENCE: PLAN-0044 Wave 1
 *
 * SUB-COMPONENTS (extracted for PLAN-0089 D-3, each ≤350 lines):
 *   - watchlists/WatchlistTabBar.tsx   — tab bar + inline create/rename inputs
 *   - watchlists/AddSymbolBar.tsx      — search + add instrument bar
 *   - watchlists/WatchlistTable.tsx    — instruments table with sticky header
 *   - watchlists/WatchlistMemberRow.tsx — single instrument row with delete button
 */

"use client";
// WHY "use client": uses useState for active tab, creating state, and async mutations.

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { Button } from "@/components/ui/button";
import type { Watchlist, WatchlistMember } from "@/types/api";
import { WatchlistTabBar } from "./watchlists/WatchlistTabBar";
import { AddSymbolBar } from "./watchlists/AddSymbolBar";
import { WatchlistTable } from "./watchlists/WatchlistTable";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WatchlistsTabPanelProps {
  watchlists: Watchlist[];
  /** Live quotes keyed by instrument_id (from getBatchQuotes for all watchlist members) */
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  isLoading: boolean;
}

// ── WatchlistsTabPanel ─────────────────────────────────────────────────────────

export function WatchlistsTabPanel({
  watchlists,
  quotes,
  isLoading,
}: WatchlistsTabPanelProps) {
  const router = useRouter();
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  const [activeWatchlistId, setActiveWatchlistId] = useState<string | null>(
    watchlists[0]?.watchlist_id ?? null,
  );

  // WHY creating state: toggles an inline input form in the tab bar instead of opening
  // a separate modal — keeps the interaction lightweight and in-context.
  const [creating, setCreating] = useState(false);

  // WHY renamingWatchlistId: tracks which tab (if any) is in inline-rename edit mode.
  // null means none are being renamed. The rename input is rendered in-place over the tab label.
  const [renamingWatchlistId, setRenamingWatchlistId] = useState<string | null>(null);

  // WHY track which entity is being deleted: shows a per-row spinner only on the
  // affected row, not a global loading state that would block the whole table.
  const [deletingEntityId, setDeletingEntityId] = useState<string | null>(null);

  // ── Delete member mutation ──────────────────────────────────────────────────
  const deleteMemberMutation = useMutation({
    mutationFn: ({ watchlistId, entityId }: { watchlistId: string; entityId: string }) =>
      createGateway(accessToken).removeWatchlistMember(watchlistId, entityId),
    onMutate: ({ entityId }) => {
      setDeletingEntityId(entityId);
    },
    onSettled: () => {
      setDeletingEntityId(null);
    },
    onSuccess: (_, vars) => {
      // PLAN-0046 / T-46-2-03: invalidate BOTH the watchlists list (for
      // member_count) AND the per-watchlist members query so the row
      // disappears immediately after delete.
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      queryClient.invalidateQueries({
        queryKey: ["watchlist-members", vars.watchlistId],
      });
    },
  });

  // ── Create watchlist mutation ──────────────────────────────────────────────
  const createMutation = useMutation({
    mutationFn: (name: string) => createGateway(accessToken).createWatchlist(name),
    onSuccess: (newWatchlist) => {
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      // Switch to the newly created watchlist immediately
      setActiveWatchlistId(newWatchlist.watchlist_id);
      setCreating(false);
    },
  });

  // ── Delete watchlist mutation ──────────────────────────────────────────────
  const deleteWatchlistMutation = useMutation({
    mutationFn: (watchlistId: string) => createGateway(accessToken).deleteWatchlist(watchlistId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      // If the deleted watchlist was active, fall back to another one
      if (activeWatchlistId === deletedId) {
        const remaining = watchlists.filter((w) => w.watchlist_id !== deletedId);
        setActiveWatchlistId(remaining[0]?.watchlist_id ?? null);
      }
    },
  });

  // ── Rename watchlist mutation ──────────────────────────────────────────────
  const renameMutation = useMutation({
    mutationFn: ({ watchlistId, newName }: { watchlistId: string; newName: string }) =>
      createGateway(accessToken).renameWatchlist(watchlistId, newName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      setRenamingWatchlistId(null);
    },
    onError: () => {
      // Keep the input visible so the user can retry or cancel
    },
  });

  function handleRowClick(id: string) {
    // PRD-0089 F2 step 11 (§6.6): `id` is ticker-first (the row component
    // prefers ticker over UUID). encodeURIComponent guards against unusual
    // chars (BRK.B passes through unmodified; the middleware handles dot-form
    // tickers). Falls through to UUID resolution at the middleware layer if
    // the ticker is null on a pending-resolution row.
    router.push(`/instruments/${encodeURIComponent(id)}`);
  }

  function handleDeleteMember(entityId: string) {
    if (!activeWatchlist) return;
    deleteMemberMutation.mutate({ watchlistId: activeWatchlist.watchlist_id, entityId });
  }

  function handleDeleteWatchlist(watchlistId: string) {
    // WHY window.confirm: cheap destructive-action guard without requiring a full
    // modal. Acceptable for watchlist deletion since the data can be recreated.
    if (!window.confirm("Delete this watchlist? This cannot be undone.")) return;
    deleteWatchlistMutation.mutate(watchlistId);
  }

  // ── All hooks must run before any early return (rules-of-hooks) ──────────
  // WHY hoisted above the `isLoading`/empty-state branches: React requires
  // identical hook order on every render. We compute the active watchlist
  // meta and fire the dependent useQuery/useMemo BEFORE the conditional
  // returns so the hook count never changes.
  const activeWatchlistMeta =
    watchlists.find((w) => w.watchlist_id === activeWatchlistId) ??
    watchlists[0];

  // ── Lazy member fetch for the active tab (PLAN-0046 / T-46-2-03) ─────────────
  // WHY lazy (only the active tab): a user can have many watchlists; fetching
  // every tab's members upfront would multiply round-trips with no UI benefit
  // since only one tab is ever visible at a time. The query key includes the
  // watchlist_id so each tab gets its own cache entry — switching back to a
  // previously visited tab is instant.
  //
  // WHY enabled gate: avoid triggering a fetch before we know which tab is
  // active or before the auth token is ready.
  const activeWatchlistId_safe = activeWatchlistMeta?.watchlist_id ?? null;
  const { data: activeMembers, isLoading: membersLoading } = useQuery({
    queryKey: ["watchlist-members", activeWatchlistId_safe],
    queryFn: () =>
      createGateway(accessToken).getWatchlistMembers(activeWatchlistId_safe!),
    enabled: !!accessToken && !!activeWatchlistId_safe,
    // WHY 30s staleTime: matches the rest of the watchlist surface; live
    // quotes refresh every 30s, member list rarely changes between adds.
    staleTime: 30_000,
  });

  // WHY useMemo: keeps the merged object reference stable so downstream hooks
  // (member-id list, quote query key) don't churn each render. The original
  // un-memoised version triggered the react-hooks/exhaustive-deps warning.
  const activeWatchlist = useMemo(
    () =>
      activeWatchlistMeta
        ? {
            ...activeWatchlistMeta,
            members: activeMembers ?? activeWatchlistMeta.members,
            member_count: (activeMembers ?? activeWatchlistMeta.members).length,
          }
        : undefined,
    [activeWatchlistMeta, activeMembers],
  );

  // ── Quotes for the active watchlist's members (PLAN-0046 / T-46-2-03) ─────
  // WHY here (not in parent): the parent's `quotes` prop was previously fed
  // by an upstream `watchlistInstrumentIds` derived from `watchlists.members`.
  // Now that `getWatchlists()` no longer carries members, the parent's pipe
  // returns empty. Fetching live quotes for the active tab here keeps the
  // change local to the panel and avoids a wider refactor of the page.
  const activeInstrumentIds = useMemo(
    () =>
      (activeWatchlist?.members ?? [])
        .map((m: WatchlistMember) => m.instrument_id)
        .filter((id): id is string => id !== null),
    [activeWatchlist],
  );
  const { data: localQuotesResp } = useQuery({
    queryKey: ["watchlist-active-quotes", activeWatchlist?.watchlist_id, activeInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(activeInstrumentIds),
    enabled: activeInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });
  // WHY merge with parent `quotes`: keep backward-compat with any quotes the
  // parent might still pass (e.g. from holdings shared across views) while
  // preferring our freshly fetched values for the active watchlist members.
  const mergedQuotes = useMemo(
    () => ({ ...quotes, ...(localQuotesResp?.quotes ?? {}) }),
    [quotes, localQuotesResp],
  );

  // ── Early returns AFTER all hooks ────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-24 text-[11px] text-muted-foreground">
        Loading watchlists…
      </div>
    );
  }

  if (watchlists.length === 0 && !creating) {
    // T-B-2-05: empty-state guard rendered BEFORE the tab bar so the panel
    // doesn't show a bare set of tab chrome with no content underneath
    // (the "void above tabs" bug, F-P-008). Centred flex column keeps the
    // message + CTA visually balanced inside the panel.
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-4">
        <InlineEmptyState message="No watchlists yet." />
        {/* WHY shadcn Button (not raw <button>): matches the rest of the app
            so size + spacing + focus ring stay consistent with portfolio CTAs. */}
        <Button
          size="sm"
          variant="outline"
          onClick={() => setCreating(true)}
          className="gap-1"
        >
          <Plus className="h-3 w-3" aria-hidden="true" />
          Create watchlist
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col bg-background">
      {/* ── Watchlist tab bar ────────────────────────────────────────────── */}
      <WatchlistTabBar
        watchlists={watchlists}
        activeWatchlistId={activeWatchlist?.watchlist_id ?? null}
        creating={creating}
        createIsPending={createMutation.isPending}
        renamingWatchlistId={renamingWatchlistId}
        renameMutationIsPending={renameMutation.isPending}
        deleteWatchlistMutationIsPending={deleteWatchlistMutation.isPending}
        activeWatchlistMemberCount={activeWatchlist?.member_count}
        onSelectWatchlist={setActiveWatchlistId}
        onStartCreate={() => setCreating(true)}
        onCancelCreate={() => setCreating(false)}
        onConfirmCreate={(name) => createMutation.mutate(name)}
        onStartRename={(id) => setRenamingWatchlistId(id)}
        onConfirmRename={(watchlistId, newName) =>
          renameMutation.mutate({ watchlistId, newName })
        }
        onCancelRename={() => setRenamingWatchlistId(null)}
        onDeleteWatchlist={handleDeleteWatchlist}
      />

      {/* ── Search bar to add instruments ─────────────────────────────── */}
      {activeWatchlist && (
        <AddSymbolBar
          watchlistId={activeWatchlist.watchlist_id}
          onAdded={() => {
            // No-op callback — query invalidation handles the re-render.
          }}
        />
      )}

      {/* ── Active watchlist table ─────────────────────────────────────── */}
      {/* WHY membersLoading guard: while the GET /members request is in flight
          (PLAN-0046 T-46-2-03) the merged `members` array could briefly be []
          and the table would flash the "Search above…" empty state. Showing a
          subtle loading row instead avoids the misleading flicker. */}
      {activeWatchlist && membersLoading && !activeMembers ? (
        <div className="flex items-center justify-center h-12 text-[11px] text-muted-foreground">
          Loading members…
        </div>
      ) : (
        activeWatchlist && (
          <WatchlistTable
            watchlist={activeWatchlist}
            quotes={mergedQuotes}
            onRowClick={handleRowClick}
            onDeleteMember={handleDeleteMember}
            deletingEntityId={deletingEntityId}
          />
        )
      )}
    </div>
  );
}
