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
 * WHO USES IT: app/(app)/portfolio/page.tsx — Watchlist tab content
 * DATA SOURCE: getWatchlists() → per-tab getBatchQuotes() via parent
 * DESIGN REFERENCE: PRD-0031 §8.5 Watchlists Tab, Wave 4
 */

"use client";
// WHY "use client": uses useState for active tab, search state, and async mutations.

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
// WHY lucide-react icons: search magnifier + X clear + Loader2 spinner match the
// terminal icon set used everywhere else in the app (consistent visual language).
import { Search, X, Loader2 } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import { formatPrice, formatPercent, priceChangeClass } from "@/lib/utils";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
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
}: {
  member: WatchlistMember;
  quote?: { price: number; change: number; change_pct: number };
  onRowClick: (entityId: string) => void;
}) {
  return (
    <tr
      className="h-[22px] hover:bg-muted/40 cursor-pointer transition-colors"
      onClick={() => onRowClick(member.entity_id)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onRowClick(member.entity_id);
        }
      }}
    >
      {/* Ticker */}
      <td className="px-2 font-mono text-[11px] tabular-nums text-primary font-medium">
        {member.ticker ?? "—"}
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
    </tr>
  );
}

// ── WatchlistTable ─────────────────────────────────────────────────────────────

function WatchlistTable({
  watchlist,
  quotes,
  onRowClick,
}: {
  watchlist: Watchlist;
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  onRowClick: (entityId: string) => void;
}) {
  const members = watchlist.members;

  if (members.length === 0) {
    return <InlineEmptyState message="Search above to add your first symbol." />;
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
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── AddSymbolBar ───────────────────────────────────────────────────────────────
// WHY separate sub-component: keeps WatchlistsTabPanel from growing too large and
// makes the search/add logic self-contained (easier to test independently).

function AddSymbolBar({
  watchlistId,
  onAdded,
}: {
  watchlistId: string;
  onAdded: () => void;
}) {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();

  // ── Search input state ────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);

  // WHY debounced query: avoid hammering S9 on every keystroke; 300ms delay is
  // enough for fast typists to finish a 3-letter ticker (e.g., "AAP" → "AAPL").
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(searchQuery.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // ── Click-outside detection for dropdown ─────────────────────────────────
  // WHY useRef + document listener: clicking outside the search bar + dropdown
  // should close the dropdown without requiring the user to press Escape.
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

  // ── Instrument search query ───────────────────────────────────────────────
  // WHY enabled when debouncedQuery.length >= 1: single-char queries (e.g., "A")
  // still return useful results (AAPL, AMZN) and the latency is acceptable.
  const { data: searchResults, isFetching: searchFetching } = useQuery({
    queryKey: ["watchlist-instrument-search", debouncedQuery],
    queryFn: () => createGateway(accessToken).searchInstruments(debouncedQuery, 8),
    enabled: !!accessToken && debouncedQuery.length >= 1,
    staleTime: 30_000,
  });

  // ── Add-member mutation ───────────────────────────────────────────────────
  // WHY useMutation: addWatchlistMember is a write operation (POST) — it should
  // not be a query. useMutation gives us isPending, onSuccess, onError states.
  const addMutation = useMutation({
    mutationFn: (entityId: string) =>
      createGateway(accessToken).addWatchlistMember(watchlistId, entityId),
    onSuccess: () => {
      // Invalidate watchlists so the table re-renders with the new member
      // WHY invalidateQueries (not setQueryData): the gateway re-fetches the full
      // watchlist after adding a member, so the cache would still be stale. Invalidating
      // forces a re-fetch from S1 and guarantees the UI shows the latest member_count.
      queryClient.invalidateQueries({ queryKey: ["watchlists"] });
      setSearchQuery("");
      setDebouncedQuery("");
      setShowDropdown(false);
      onAdded();
    },
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
    // WHY relative: dropdown is absolutely positioned below the search bar.
    // WHY border-b: consistent separation from the watchlist table above/below.
    <div ref={containerRef} className="relative border-b border-border px-2 py-1.5">

      {/* ── Search input ────────────────────────────────────────────────── */}
      <div className="flex h-7 items-center gap-1.5 rounded-[2px] border border-border bg-background px-2">
        {/* WHY Search icon: Bloomberg convention — search field always has a magnifier */}
        <Search className="h-3 w-3 shrink-0 text-muted-foreground" />

        <input
          value={searchQuery}
          onChange={handleInputChange}
          onFocus={() => {
            // Re-show dropdown if there's an active query
            if (searchQuery.length > 0) setShowDropdown(true);
          }}
          placeholder="Add ticker or company…"
          // WHY font-mono: ticker input should render in a monospace font so the
          // user's typed ticker aligns with the ticker column below.
          className="flex-1 bg-transparent font-mono text-[11px] text-foreground outline-none placeholder:text-muted-foreground/60"
          // WHY aria-label: screen readers should announce this as "instrument search"
          aria-label="Search to add instrument"
          aria-autocomplete="list"
          aria-expanded={showDropdown && hasResults}
        />

        {/* Spinner while fetching */}
        {searchFetching && (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground" />
        )}

        {/* Clear button — only shown when there's a query and not loading */}
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

      {/* ── Results dropdown ─────────────────────────────────────────────── */}
      {/* WHY z-50: dropdown must overlay the watchlist table rows below.
          WHY shadow-md: subtle depth cue distinguishes the floating dropdown
          from the underlying table content. */}
      {showDropdown && (hasResults || (debouncedQuery.length > 0 && !searchFetching)) && (
        <div
          role="listbox"
          aria-label="Search results"
          className="absolute left-2 right-2 top-full z-50 mt-0.5 overflow-hidden rounded-[2px] border border-border bg-card shadow-md"
        >
          {!hasResults && debouncedQuery.length > 0 ? (
            // Empty results state — shown after debounce + fetch completes
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
                {/* Ticker — monospace, primary color (amber) for visual weight */}
                <span className="w-[48px] shrink-0 font-mono text-[11px] font-medium text-primary">
                  {result.ticker}
                </span>

                {/* Company name — may be synthesised as "TICKER (EXCHANGE)" since S3
                    does not return full names. We show what we have. */}
                <span className="min-w-0 flex-1 truncate text-[11px] text-foreground">
                  {result.name}
                </span>

                {/* Exchange badge */}
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {result.exchange}
                </span>
              </button>
            ))
          )}

          {/* ── Add-member error state ────────────────────────────────── */}
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

// ── WatchlistsTabPanel ─────────────────────────────────────────────────────────

export function WatchlistsTabPanel({
  watchlists,
  quotes,
  isLoading,
}: WatchlistsTabPanelProps) {
  const router = useRouter();

  // WHY local tab state: the selected watchlist is UI state, not URL state.
  // Switching watchlists doesn't change the URL — it's a view filter within the tab.
  const [activeWatchlistId, setActiveWatchlistId] = useState<string | null>(
    watchlists[0]?.watchlist_id ?? null,
  );

  function handleRowClick(entityId: string) {
    router.push(`/instruments/${encodeURIComponent(entityId)}`);
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-24 text-[11px] text-muted-foreground">
        Loading watchlists…
      </div>
    );
  }

  if (watchlists.length === 0) {
    return (
      <InlineEmptyState message="No watchlists yet. Create one to start monitoring symbols." />
    );
  }

  const activeWatchlist =
    watchlists.find((w) => w.watchlist_id === activeWatchlistId) ??
    watchlists[0];

  return (
    <div className="flex flex-col">
      {/* ── Watchlist tab bar ────────────────────────────────────────────── */}
      {/* WHY custom tab bar (not shadcn Tabs): the outer portfolio page already
          uses shadcn Tabs, and nesting Radix Tabs inside Tabs causes keyboard
          navigation conflicts. A simple flex button bar is semantically correct
          for nested tab groups. */}
      <div className="flex h-9 items-center gap-0 border-b border-border overflow-x-auto shrink-0">
        {watchlists.map((wl) => (
          <button
            key={wl.watchlist_id}
            role="tab"
            aria-selected={wl.watchlist_id === activeWatchlist.watchlist_id}
            onClick={() => setActiveWatchlistId(wl.watchlist_id)}
            className={cn(
              "h-full px-3 text-[11px] font-mono border-b-2 transition-colors whitespace-nowrap shrink-0",
              wl.watchlist_id === activeWatchlist.watchlist_id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {wl.name}
          </button>
        ))}

        {/* Member count badge */}
        <span className="ml-auto px-2 font-mono text-[10px] tabular-nums text-muted-foreground shrink-0">
          {activeWatchlist.member_count} symbols
        </span>
      </div>

      {/* ── Search bar to add instruments ─────────────────────────────── */}
      {/* WHY AddSymbolBar above the table: Bloomberg convention — search/add
          actions appear above the data list they affect. The empty state message
          "Search above to add your first symbol" also points upward. */}
      <AddSymbolBar
        watchlistId={activeWatchlist.watchlist_id}
        onAdded={() => {
          // No-op callback — query invalidation handles the re-render.
          // Kept as a prop so parent can react if needed in future.
        }}
      />

      {/* ── Active watchlist table ─────────────────────────────────────── */}
      <WatchlistTable
        watchlist={activeWatchlist}
        quotes={quotes}
        onRowClick={handleRowClick}
      />
    </div>
  );
}
