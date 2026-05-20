/**
 * components/shell/WatchlistPanel.tsx — Sidebar watchlist with live prices
 *
 * WHY THIS EXISTS: Institutional traders check their watchlist constantly during
 * market hours. Embedding it in the sidebar means it's always visible without
 * navigating away from whatever page the trader is on — identical to Bloomberg's
 * persistent monitor panel on the left rail.
 *
 * WHY live quotes (30s refetch): Sidebar prices are reference, not trading inputs.
 * 30s freshness is sufficient for a trader checking whether a watchlist name
 * has moved since they last looked — they'll open the instrument detail for
 * tick-level precision.
 *
 * WHO USES IT: components/shell/CollapsibleSidebar.tsx (expanded state only)
 * DATA SOURCE: S9 GET /v1/watchlists → first watchlist members →
 *              POST /v1/quotes/batch (entity IDs)
 * DESIGN REFERENCE: PRD-0031 §4.3 Sidebar WatchlistPanel
 */

"use client";
// WHY "use client": uses useQuery (TanStack, client-only), useRouter (navigation),
// useState for the watchlist dropdown, and live data (30s refresh).

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { priceChangeClass, formatPercentDirect, cn } from "@/lib/utils";
import type { WatchlistMember } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

/** Max symbols shown in the sidebar watchlist — more → "+N more →" link */
const MAX_ROWS = 10;

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistPanel() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY selectedWatchlistId state: the dropdown lets the user switch which
  // watchlist is pinned to the sidebar without navigating to the portfolio page.
  // null means "use the first watchlist" (default on load).
  const [selectedWatchlistId, setSelectedWatchlistId] = useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // WHY dropdownRef + buttonRef: the dropdown renders at a fixed position (see below)
  // to escape the sidebar's overflow-hidden ancestors. We track two elements for
  // click-outside detection: the trigger button wrapper and the floating list itself.
  const dropdownRef = useRef<HTMLDivElement>(null);   // trigger button container
  const dropdownListRef = useRef<HTMLDivElement>(null); // fixed-position dropdown list

  // WHY { top, right } state: we compute the dropdown's fixed position from the
  // button's bounding rect at the moment the user clicks open. This is recalculated
  // on every open so that it stays correct after sidebar resize or window scroll.
  const [dropdownPos, setDropdownPos] = useState<{ top: number; right: number } | null>(null);

  // WHY two-ref check in click-outside: the dropdown list is position:fixed and
  // therefore NOT a DOM descendant of dropdownRef — clicking inside the list would
  // be treated as "outside the trigger" and immediately close the dropdown.
  const handleClickOutside = useCallback((e: MouseEvent) => {
    const target = e.target as Node;
    const insideTrigger = dropdownRef.current?.contains(target) ?? false;
    const insideList = dropdownListRef.current?.contains(target) ?? false;
    if (!insideTrigger && !insideList) setDropdownOpen(false);
  }, []);

  useEffect(() => {
    if (!dropdownOpen) return;
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [dropdownOpen, handleClickOutside]);

  // Compute the fixed position of the dropdown when the user opens it.
  // WHY not absolute: the sidebar <aside> has overflow-hidden (needed for width
  // animation). An absolutely-positioned child is clipped by every overflow-hidden
  // ancestor — making parts of the dropdown invisible and unclickable. Fixed
  // positioning escapes all overflow-hidden ancestors and is relative to the viewport.
  const openDropdown = useCallback(() => {
    if (dropdownRef.current) {
      const rect = dropdownRef.current.getBoundingClientRect();
      setDropdownPos({
        top: rect.bottom + 2,                          // 2px gap below the button
        right: window.innerWidth - rect.right,         // right-aligned to the button
      });
    }
    setDropdownOpen(true);
  }, []);

  // Fetch the user's watchlists — all of them (needed for the dropdown switcher)
  // WHY staleTime 30s: watchlist membership changes infrequently (user-driven);
  // 30s prevents a refetch on every page navigation without hiding new additions.
  const { data: watchlistsData } = useQuery({
    queryKey: ["watchlists-sidebar"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 30_000,
  });

  // Resolve active watchlist: use selected if present, otherwise fall back to first
  const activeWatchlist =
    watchlistsData?.find((wl) => wl.watchlist_id === selectedWatchlistId) ??
    watchlistsData?.[0];
  const members: WatchlistMember[] = activeWatchlist?.members ?? [];
  const memberIds = members.map((m) => m.entity_id);

  // Fetch live batch quotes for watchlist member entity IDs
  // WHY refetchInterval 30_000 + staleTime 0: prices should always be fresh
  // (no cache aging), but we cap the network cost at one call per 30 seconds.
  const { data: quotesData } = useQuery({
    queryKey: ["watchlist-sidebar-quotes", memberIds],
    queryFn: () => createGateway(accessToken).getBatchQuotes(memberIds),
    enabled: memberIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });

  const quotes = quotesData?.quotes ?? {};
  const displayMembers = members.slice(0, MAX_ROWS);
  const extraCount = Math.max(0, members.length - MAX_ROWS);

  return (
    <div className="flex flex-col overflow-hidden">
      {/* ── Section header ────────────────────────────────────────────────── */}
      {/* WHY h-6 border-b border-t: §0.9 section header pattern — 24px height,
       * bordered top and bottom to clearly separate from nav items above. */}
      <div className="flex h-6 shrink-0 items-center justify-between border-b border-border border-t border-t-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          WATCHLIST
        </span>
        {/* Watchlist dropdown switcher — shows all watchlists so the trader can
            switch which one is pinned to the sidebar without leaving the current page.
            WHY relative on wrapper: anchors the absolute-positioned dropdown. */}
        {activeWatchlist && (
          <div className="relative" ref={dropdownRef}>
            <button
              // WHY openDropdown (not inline toggle): we must compute the fixed position
              // from the button's bounding rect before setting dropdownOpen=true.
              onClick={() => dropdownOpen ? setDropdownOpen(false) : openDropdown()}
              className="text-[10px] font-mono text-muted-foreground hover:text-foreground transition-colors duration-0"
              aria-label={`Switch watchlist (current: ${activeWatchlist.name})`}
              aria-expanded={dropdownOpen}
            >
              {activeWatchlist.name} ▾
            </button>

            {/* Dropdown list — rendered at fixed position to escape overflow-hidden sidebar.
                WHY position:fixed via inline style: Tailwind's `fixed` class would work but
                we need dynamic top/right values computed at runtime from getBoundingClientRect.
                WHY max-h-[240px] overflow-y-auto: users may have many watchlists; capping
                at 240px (~10 rows) keeps the dropdown within the viewport while allowing scroll. */}
            {dropdownOpen && watchlistsData && watchlistsData.length > 0 && dropdownPos && (
              <div
                ref={dropdownListRef}
                style={{
                  position: "fixed",
                  top: dropdownPos.top,
                  right: dropdownPos.right,
                  zIndex: 9999,      // above all sidebar elements including z-50 drag handle
                }}
                className="min-w-[160px] max-h-[240px] overflow-y-auto border border-border bg-card "
              >
                {watchlistsData.map((wl) => (
                  <button
                    key={wl.watchlist_id}
                    onClick={() => {
                      setSelectedWatchlistId(wl.watchlist_id);
                      setDropdownOpen(false);
                    }}
                    className={cn(
                      "w-full px-2 py-1 text-left text-[11px] hover:bg-muted/40 transition-colors duration-0",
                      activeWatchlist.watchlist_id === wl.watchlist_id
                        ? "text-primary font-medium"
                        : "text-foreground",
                    )}
                  >
                    {wl.name}
                  </button>
                ))}
                {/* Manage link — navigates to full watchlist management in Portfolio */}
                <button
                  onClick={() => { setDropdownOpen(false); router.push("/portfolio?tab=watchlists"); }}
                  className="w-full border-t border-border px-2 py-1 text-left text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-0"
                >
                  Manage watchlists →
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Symbol rows ───────────────────────────────────────────────────── */}
      {/* WHY divide-y divide-border/30: lightweight row separation without the
       * visual weight of a full border-border row divider. /30 keeps the separator
       * nearly invisible but still provides the row boundary cue. */}
      <div className="overflow-y-auto divide-y divide-border/30">
        {displayMembers.length === 0 ? (
          // ── Empty state: short inline text per §0.5 ────────────────────────
          <p className="px-2 py-1 text-[11px] text-muted-foreground">
            Add symbols in Portfolio → Watchlists
          </p>
        ) : (
          displayMembers.map((member) => {
            const quote = quotes[member.entity_id];
            return (
              // WHY h-[22px]: §0.2 data table row height — 22px compact row standard.
              // WHY cursor-pointer + hover:bg-muted/40: row is clickable — navigates
              // to the instrument detail page.
              <div
                key={member.entity_id}
                className="flex h-[22px] items-center cursor-pointer px-2 hover:bg-muted/40"
                // PRD-0089 F2 step 11 (§6.6): ticker-first URL. ticker can be
                // null for `resolution=pending` rows; fall back to the UUID
                // and let the middleware resolve.
                onClick={() =>
                  router.push(
                    `/instruments/${member.ticker || member.instrument_id || member.entity_id}`,
                  )
                }
                aria-label={`${member.ticker ?? member.entity_id} — view instrument detail`}
              >
                {/* Ticker — 40px fixed, mono for column alignment */}
                <span className="w-[40px] shrink-0 font-mono text-[11px] tabular-nums text-foreground truncate">
                  {member.ticker ?? member.entity_id.slice(0, 6)}
                </span>
                {/* Price — right-aligned, mono; "—" when quote not yet loaded */}
                <span className="flex-1 text-right font-mono text-[11px] tabular-nums text-foreground">
                  {quote != null ? quote.price.toFixed(2) : "—"}
                </span>
                {/* Change% — colored by sign per §0.4 Color Discipline */}
                <span
                  className={`w-[44px] shrink-0 text-right font-mono text-[11px] tabular-nums ${
                    quote != null
                      ? priceChangeClass(quote.change_pct)
                      : "text-muted-foreground"
                  }`}
                >
                  {quote != null ? formatPercentDirect(quote.change_pct) : "—"}
                </span>
              </div>
            );
          })
        )}

        {/* ── Overflow link — "+N more →" ───────────────────────────────── */}
        {extraCount > 0 && (
          <button
            onClick={() => router.push("/portfolio?tab=watchlists")}
            className="w-full px-2 py-0.5 text-left text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-0"
          >
            +{extraCount} more →
          </button>
        )}
      </div>
    </div>
  );
}
