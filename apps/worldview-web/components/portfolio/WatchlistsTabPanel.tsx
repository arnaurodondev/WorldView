/**
 * components/portfolio/WatchlistsTabPanel.tsx — Multi-watchlist panel with live prices
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
 */

"use client";
// WHY "use client": uses useState for active tab, search state, create mode, and async mutations.

import { useState, useRef, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, X, Loader2, Trash2, Plus, MoreHorizontal, Pencil } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Watchlist, WatchlistMember } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WatchlistsTabPanelProps {
  watchlists: Watchlist[];
  /** Live quotes keyed by instrument_id (from getBatchQuotes for all watchlist members) */
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  isLoading: boolean;
}

// ── WatchlistMemberRow ─────────────────────────────────────────────────────────

function WatchlistMemberRow({
  member,
  quote,
  onRowClick,
  onDelete,
  isDeleting,
}: {
  member: WatchlistMember;
  quote?: { price: number; change: number; change_pct: number };
  onRowClick: (entityId: string) => void;
  onDelete: (entityId: string) => void;
  isDeleting: boolean;
}) {
  return (
    // WHY group/row: enables the delete button to be hidden by default and revealed
    // only on row hover, keeping the table uncluttered during the primary read flow.
    <tr
      className="h-[22px] hover:bg-muted/40 cursor-pointer transition-colors group/row"
      onClick={() => onRowClick(member.entity_id)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onRowClick(member.entity_id);
        }
      }}
    >
      {/* Ticker — F-010 (QA 2026-04-28): when the local instrument cache
          had no match at add-time the backend reports resolution=pending.
          We show the dash placeholder PLUS a small "resolving…" badge so
          the user understands the row will auto-fill once the instrument
          syncs. WHY badge inline (not separate cell): keeps the table
          density tight; the badge sits in the otherwise-empty ticker
          column. */}
      <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
        {member.ticker ?? (
          <span className="inline-flex items-center gap-1">
            <span className="text-muted-foreground">—</span>
            {member.resolution === "pending" && (
              <span
                className="rounded-[2px] border border-warning/60 bg-warning/10 px-1 py-px text-[8px] uppercase tracking-[0.06em] text-warning"
                aria-label="Resolving instrument metadata"
              >
                resolving…
              </span>
            )}
          </span>
        )}
      </td>

      {/* Name */}
      <td className="px-2 text-[11px] text-foreground max-w-[180px] truncate">
        {member.name}
      </td>

      {/* Price */}
      <td className="px-2 font-mono text-[11px] tabular-nums text-foreground text-right">
        {quote ? formatPrice(quote.price) : "—"}
      </td>

      {/* Change% — colored */}
      <td
        className={cn(
          "px-2 font-mono text-[11px] tabular-nums text-right",
          quote ? priceChangeClass(quote.change_pct) : "text-muted-foreground",
        )}
      >
        {quote ? formatPercent(quote.change_pct / 100) : "—"}
      </td>

      {/* Change$ */}
      <td
        className={cn(
          "px-2 font-mono text-[11px] tabular-nums text-right",
          quote ? priceChangeClass(quote.change) : "text-muted-foreground",
        )}
      >
        {quote ? (quote.change >= 0 ? "+" : "") + formatPrice(quote.change) : "—"}
      </td>

      {/* Delete button — hidden at rest, revealed on row hover.
          WHY stopPropagation: prevent the delete click from also navigating to
          the instrument detail page (the row's onClick handler). */}
      <td className="w-8 px-1 text-right">
        <button
          aria-label={`Remove ${member.ticker ?? member.name} from watchlist`}
          disabled={isDeleting}
          onClick={(e) => {
            e.stopPropagation();
            onDelete(member.entity_id);
          }}
          className={cn(
            "opacity-0 group-hover/row:opacity-100 transition-opacity",
            "h-5 w-5 flex items-center justify-center rounded-[2px]",
            "text-muted-foreground hover:text-negative hover:bg-negative/10",
            isDeleting && "opacity-50 cursor-not-allowed",
          )}
        >
          {isDeleting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Trash2 className="h-3 w-3" />
          )}
        </button>
      </td>
    </tr>
  );
}

// ── WatchlistTable ─────────────────────────────────────────────────────────────

function WatchlistTable({
  watchlist,
  quotes,
  onRowClick,
  onDeleteMember,
  deletingEntityId,
}: {
  watchlist: Watchlist;
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  onRowClick: (entityId: string) => void;
  onDeleteMember: (entityId: string) => void;
  deletingEntityId: string | null;
}) {
  const members = watchlist.members;

  if (members.length === 0) {
    // WHY centered wrapper (B-5): InlineEmptyState rendered raw collapsed to a
    // tiny inline element at the top of a tall container, leaving most of the
    // tab pane visually empty. py-8 + flex-centering puts the message in the
    // optical center of the empty area.
    return (
      <div className="flex flex-1 items-center justify-center py-8">
        <InlineEmptyState message="Search above to add your first symbol." />
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

// ── AddSymbolBar ───────────────────────────────────────────────────────────────

function AddSymbolBar({
  watchlistId,
  onAdded,
}: {
  watchlistId: string;
  onAdded: () => void;
}) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  const [searchQuery, setSearchQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);

  // WHY debounced query: avoid hammering S9 on every keystroke; 300ms delay is
  // enough for fast typists to finish a 3-letter ticker (e.g., "AAP" → "AAPL").
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  const { data: searchResults, isFetching: searchFetching } = useQuery({
    queryKey: ["watchlist-fundamentals-search", debouncedQuery],
    // WHY searchFundamentals (B-3): the watchlist endpoint needs the REAL KG
    // entity_id. searchInstruments falls back to instrument_id and the add
    // silently fails. The screener joins through S7 KG so it returns the real
    // entity_id directly — same shape, correct ID.
    queryFn: () => createGateway(accessToken).searchFundamentals(debouncedQuery, 8),
    enabled: !!accessToken && debouncedQuery.length >= 1,
    staleTime: 30_000,
  });

  const addMutation = useMutation({
    mutationFn: (entityId: string) =>
      createGateway(accessToken).addWatchlistMember(watchlistId, entityId),
    onSuccess: () => {
      // PLAN-0046 / T-46-2-03: invalidate the per-watchlist members query so
      // the just-added row is fetched and rendered, AND the list query so the
      // tab badge member count refreshes.
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      queryClient.invalidateQueries({
        queryKey: ["watchlist-members", watchlistId],
      });
      setSearchQuery("");
      setDebouncedQuery("");
      setShowDropdown(false);
      onAdded();
    },
    // WHY surface error: previously the mutation failed silently when the
    // backend rejected an unknown entity_id. The dropdown now shows the
    // server-side error message under the result list (rendered below).
  });

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSearchQuery(e.target.value);
    setShowDropdown(e.target.value.length > 0);
  }

  function handleClear() {
    setSearchQuery("");
    setDebouncedQuery("");
    setShowDropdown(false);
  }

  const results = searchResults?.results ?? [];
  const hasResults = results.length > 0;

  return (
    <div ref={containerRef} className="relative border-b border-border px-2 py-1.5">
      <div className="flex h-7 items-center gap-1.5 rounded-[2px] border border-border bg-background px-2">
        <Search className="h-3 w-3 shrink-0 text-muted-foreground" />

        <input
          value={searchQuery}
          onChange={handleInputChange}
          onFocus={() => {
            if (searchQuery.length > 0) setShowDropdown(true);
          }}
          placeholder="Add ticker or company…"
          className="flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground/60"
          aria-label="Search to add instrument"
          role="combobox"
          aria-autocomplete="list"
          aria-controls="watchlist-search-listbox"
          aria-expanded={showDropdown && hasResults}
        />

        {searchFetching && (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        )}

        {searchQuery && !searchFetching && (
          <button
            onClick={handleClear}
            aria-label="Clear search"
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      {showDropdown && (hasResults || (debouncedQuery.length > 0 && !searchFetching)) && (
        <div
          id="watchlist-search-listbox"
          role="listbox"
          aria-label="Search results"
          className="absolute left-2 right-2 top-full z-50 mt-0.5 overflow-hidden rounded-[2px] border border-border bg-card"
        >
          {!hasResults && debouncedQuery.length > 0 ? (
            <div className="px-3 py-2 text-[11px] text-muted-foreground">
              No instruments found for &quot;{debouncedQuery}&quot;
            </div>
          ) : (
            results.map((result) => (
              <button
                key={result.instrument_id}
                role="option"
                aria-selected={false}
                disabled={addMutation.isPending}
                onClick={() => addMutation.mutate(result.entity_id)}
                className={cn(
                  "flex w-full items-center gap-2 px-2 py-1.5 text-left transition-colors",
                  "hover:bg-muted/50 focus:bg-muted/50 focus:outline-none",
                  addMutation.isPending && "opacity-50 cursor-not-allowed",
                )}
              >
                <span className="w-[48px] shrink-0 font-mono text-[11px] font-medium text-primary">
                  {result.ticker}
                </span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-foreground">
                  {result.name}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {result.exchange}
                </span>
              </button>
            ))
          )}

          {addMutation.isError && (
            <div className="border-t border-border px-2 py-1 text-[10px] text-negative">
              Failed to add — check if already in watchlist.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── CreateWatchlistInput ───────────────────────────────────────────────────────

function CreateWatchlistInput({
  onCancel,
  onCreate,
}: {
  onCancel: () => void;
  onCreate: (name: string) => void;
}) {
  const [name, setName] = useState("");

  // WHY autoFocus via ref: the input should be focused immediately when the inline
  // create form appears, so the user can type the name without an extra click.
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && name.trim()) {
      onCreate(name.trim());
    } else if (e.key === "Escape") {
      onCancel();
    }
  }

  return (
    <div className="flex h-9 items-center gap-1 px-2">
      <input
        ref={inputRef}
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Watchlist name…"
        maxLength={64}
        className="h-6 flex-1 min-w-0 bg-background border border-border rounded-[2px] px-2 font-mono text-[11px] text-foreground outline-none focus:border-primary placeholder:text-muted-foreground/60"
        aria-label="New watchlist name"
      />
      <button
        disabled={!name.trim()}
        onClick={() => name.trim() && onCreate(name.trim())}
        className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
      >
        Create
      </button>
      <button
        onClick={onCancel}
        aria-label="Cancel"
        className="h-6 w-6 flex items-center justify-center text-muted-foreground hover:text-foreground shrink-0"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ── RenameTabInput ────────────────────────────────────────────────────────────
// WHY separate component: isolates the focused input state so that the parent
// tab bar doesn't re-render on every keystroke (only the rename cell does).

function RenameTabInput({
  currentName,
  isPending,
  onConfirm,
  onCancel,
}: {
  currentName: string;
  isPending: boolean;
  onConfirm: (newName: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(currentName);
  const inputRef = useRef<HTMLInputElement>(null);

  // WHY select-on-mount: pre-selects the existing name so the user can immediately
  // type a replacement without manually clearing it first.
  useEffect(() => {
    inputRef.current?.select();
  }, []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      onConfirm(value.trim());
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  }

  return (
    <div className="flex items-center h-full px-1">
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        // WHY blur-confirm: committing on blur means clicking elsewhere saves the rename
        // without needing Enter — matches standard spreadsheet/terminal editing conventions.
        // WHY isPending guard: disabled inputs can still fire blur in some browsers;
        // skip the confirm call when the mutation is already in-flight.
        onBlur={() => { if (!isPending) onConfirm(value.trim()); }}
        disabled={isPending}
        maxLength={64}
        className={cn(
          "h-6 w-[120px] bg-background border border-primary rounded-[2px] px-2",
          "font-mono text-[11px] text-foreground outline-none",
          isPending && "opacity-60 cursor-not-allowed",
        )}
        aria-label="Rename watchlist"
      />
      {isPending && <Loader2 className="ml-1 h-3 w-3 animate-spin text-muted-foreground shrink-0" />}
    </div>
  );
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

  function handleRowClick(entityId: string) {
    router.push(`/instruments/${encodeURIComponent(entityId)}`);
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
        .map((m) => m.instrument_id)
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
      <div className="flex flex-col items-center justify-center gap-3 py-8">
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
    <div className="flex flex-col">
      {/* ── Watchlist tab bar ────────────────────────────────────────────── */}
      {/* WHY custom tab bar (not shadcn Tabs): the outer portfolio page already
          uses shadcn Tabs, and nesting Radix Tabs inside Tabs causes keyboard
          navigation conflicts. */}
      {creating ? (
        // Inline create form replaces the tab bar while creating
        <div className="border-b border-border">
          <CreateWatchlistInput
            onCancel={() => setCreating(false)}
            onCreate={(name) => createMutation.mutate(name)}
          />
          {createMutation.isPending && (
            <div className="flex items-center gap-1 px-2 py-0.5 text-[10px] text-muted-foreground">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              Creating…
            </div>
          )}
        </div>
      ) : (
        <div className="flex h-9 items-center gap-0 border-b border-border overflow-x-auto shrink-0">
          {watchlists.map((wl) => (
            <div
              key={wl.watchlist_id}
              className={cn(
                "flex items-center gap-0.5 h-full border-b-2 shrink-0 group/tab",
                wl.watchlist_id === (activeWatchlist?.watchlist_id)
                  ? "border-primary"
                  : "border-transparent",
              )}
            >
              {/* WHY conditional render: when this tab is in rename mode, replace the
                  read-only label with an inline text input pre-filled with the current
                  name. Enter commits, Escape cancels. Blur also commits if a name was
                  typed (consistent with Bloomberg's in-place rename pattern). */}
              {renamingWatchlistId === wl.watchlist_id ? (
                <RenameTabInput
                  currentName={wl.name}
                  isPending={renameMutation.isPending}
                  onConfirm={(newName) => {
                    if (newName && newName !== wl.name) {
                      renameMutation.mutate({ watchlistId: wl.watchlist_id, newName });
                    } else {
                      setRenamingWatchlistId(null);
                    }
                  }}
                  onCancel={() => setRenamingWatchlistId(null)}
                />
              ) : (
                <button
                  role="tab"
                  aria-selected={wl.watchlist_id === activeWatchlist?.watchlist_id}
                  onClick={() => setActiveWatchlistId(wl.watchlist_id)}
                  className={cn(
                    "h-full px-3 text-[11px] font-mono transition-colors whitespace-nowrap",
                    wl.watchlist_id === activeWatchlist?.watchlist_id
                      ? "text-primary"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {wl.name}
                </button>
              )}

              {/* ··· dropdown for rename/delete — visible on tab hover, hidden during rename */}
              {renamingWatchlistId !== wl.watchlist_id && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      aria-label={`Options for ${wl.name}`}
                      className={cn(
                        "h-5 w-5 flex items-center justify-center rounded-[2px] mr-1",
                        "opacity-0 group-hover/tab:opacity-100 transition-opacity",
                        "text-muted-foreground hover:text-foreground hover:bg-muted/50",
                      )}
                      // WHY stopPropagation on mousedown: prevent the dropdown trigger from
                      // also activating the tab button and triggering an unintended tab switch.
                      onMouseDown={(e) => e.stopPropagation()}
                    >
                      <MoreHorizontal className="h-3 w-3" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="min-w-[120px]">
                    <DropdownMenuItem
                      className="text-[11px]"
                      onClick={() => {
                        setActiveWatchlistId(wl.watchlist_id);
                        setRenamingWatchlistId(wl.watchlist_id);
                      }}
                    >
                      <Pencil className="h-3 w-3 mr-1.5" />
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-[11px] text-negative focus:text-negative"
                      disabled={deleteWatchlistMutation.isPending}
                      onClick={() => handleDeleteWatchlist(wl.watchlist_id)}
                    >
                      <Trash2 className="h-3 w-3 mr-1.5" />
                      Delete watchlist
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          ))}

          {/* [+ New] button — always on the right side of the tab bar */}
          <button
            onClick={() => setCreating(true)}
            aria-label="Create new watchlist"
            className="ml-1 h-6 w-6 flex items-center justify-center rounded-[2px] text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors shrink-0"
            title="New watchlist"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>

          {/* Member count badge — shows count for the active watchlist */}
          {activeWatchlist && (
            <span className="ml-auto px-2 font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
              {activeWatchlist.member_count} symbols
            </span>
          )}
        </div>
      )}

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
