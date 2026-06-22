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
 *              POST /v1/quotes/batch (entity IDs) +
 *              POST /v1/ohlcv/batch (Sparkline data per FU-4.1 / C-13)
 * DESIGN REFERENCE: PRD-0089 W1 §4.5 WatchlistPanel updates
 */

"use client";
// WHY "use client": uses useQuery (TanStack, client-only), useRouter (navigation),
// useState for the watchlist dropdown, and live data (30s refresh).

import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { priceChangeClass, cn } from "@/lib/utils";
// 2026-06-19 wrap fix: formatChangePct bounds extreme % moves so they fit the
// fixed 44px %-change slot in this narrow sidebar row (replaces formatPercentDirect,
// which used an unbounded toFixed(2); see docs/audits/2026-06-19-winners-losers-wrap.md).
import { formatChangePct } from "@/lib/format";
// PRD-0089 W1 §4.5 — Sparkline column uses the F1 primitive (3-state trend per FU-5.6).
import { Sparkline } from "@/components/primitives/Sparkline";
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

  // WHY separate members query: getWatchlists() intentionally returns members:[]
  // for performance (list endpoint skips member fetch). We must call the dedicated
  // /watchlists/{id}/members endpoint to get the actual ticker list. Without this,
  // the quotes query is always disabled (memberIds=[]) and all prices show "—".
  const { data: membersData } = useQuery({
    queryKey: ["watchlist-sidebar-members", activeWatchlist?.watchlist_id],
    queryFn: () =>
      createGateway(accessToken).getWatchlistMembers(
        activeWatchlist!.watchlist_id,
      ),
    enabled: !!accessToken && !!activeWatchlist?.watchlist_id,
    staleTime: 30_000,
  });
  const members: WatchlistMember[] = membersData ?? [];

  // WHY instrument_id (not entity_id): POST /v1/quotes/batch accepts instrument_ids;
  // entity_id maps to the knowledge-graph node which is a different UUID space.
  const memberIds = members
    .map((m) => m.instrument_id)
    .filter((id): id is string => id !== null);

  // Fetch live batch quotes for watchlist member instrument IDs
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

  // ── Sparkline data (PRD-0089 W1 §4.5 / C-13 / FU-4.1) ──────────────────
  // WHY POST /v1/ohlcv/batch (not intraday): the intraday endpoint was an
  // interim design choice. C-13 locks the sparkline source to getBatchOhlcvBars
  // with 5m timeframe and 78 bars (≈ 6.5h = one trading session). This gives
  // accurate intraday trend without a separate dedicated endpoint.
  // WHY instrument_id (not ticker): ohlcv/batch requires instrument UUIDs.
  // WHY 60s staleTime + 60s refetch: sparkline trend direction doesn't need
  // 30s price refresh granularity; 60s keeps server load reasonable for a
  // sidebar widget that's always visible during market hours.
  const { data: ohlcvData } = useQuery({
    // WHY inline key (not qk.instruments.ohlcvBatch): the plan says to share
    // qk.instruments.ohlcvBatch once it exists in the key factory. We define
    // the watchlist-scoped key here for now so the query is easily identifiable
    // in DevTools without conflicting with other batch queries.
    queryKey: ["watchlist-sidebar-sparklines", [...memberIds].sort()],
    queryFn: () =>
      createGateway(accessToken).getBatchOhlcvBars({
        instrument_ids: memberIds,
        timeframe: "5m",
        limit: 78, // 78 × 5m = 390 min ≈ 6.5h (one full trading session)
      }),
    enabled: memberIds.length > 0 && !!accessToken,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  // Build a map from instrument_id → close price array for Sparkline primitive.
  // WHY close prices: sparkline represents intraday trend; close-of-period is
  // the canonical value for each 5-minute bar.
  const sparklineData: Record<string, number[]> = {};
  for (const result of ohlcvData?.results ?? []) {
    sparklineData[result.instrument_id] = result.bars.map((b) => b.close);
  }

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
                className="min-w-[160px] max-h-[240px] overflow-y-auto border border-border bg-card shadow-md"
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
                {/* Manage link — navigates to the new first-class /watchlists page (C-09).
                    WHY /watchlists (not /portfolio?tab=watchlists): FU-4.2 lock. */}
                <button
                  onClick={() => { setDropdownOpen(false); router.push("/watchlists"); }}
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
      {/*
       * WHY data-table-grid: the F1 `data-table-grid` attribute triggers the
       * `--row-h: 20px` CSS custom property from globals.css, locking every
       * descendant row to exactly 20px. Without this attribute, custom h-[22px]
       * classes drift from the F1 row-height token (C-01 fix).
       * WHY divide-y divide-border/30: lightweight row separation without the
       * visual weight of a full border-border row divider. /30 keeps the separator
       * nearly invisible but still provides the row boundary cue.
       */}
      <div data-table-grid className="overflow-y-auto divide-y divide-border/30">
        {displayMembers.length === 0 ? (
          // ── Empty state: short inline text per §0.5 ────────────────────────
          // WHY updated link target (/watchlists not /portfolio?tab=watchlists):
          // C-09 / FU-4.2 — the watchlists route is now a first-class page.
          <p className="px-2 py-1 text-[11px] text-muted-foreground">
            Add symbols in{" "}
            <button
              onClick={() => router.push("/watchlists")}
              className="text-primary hover:underline"
            >
              Watchlists
            </button>
          </p>
        ) : (
          displayMembers.map((member) => {
            const quote = quotes[member.instrument_id ?? ""];
            // WHY sparklinePoints from sparklineData: the Sparkline primitive needs
            // a number[] of close prices. Empty array → Sparkline renders a flat
            // dashed line (the "no data" state defined in the primitive).
            const sparklinePoints = sparklineData[member.instrument_id ?? ""] ?? [];

            return (
              /*
               * WHY h-[20px] (was h-[22px]):
               * The data-table-grid attribute sets --row-h=20px; we must keep
               * explicit h-[20px] here to match the token. F1 C-01 locks watchlist
               * rows to 20px (same as data table rows) for visual consistency with
               * the Holdings table and screener rows elsewhere.
               *
               * WHY click to /instruments/${member.ticker}:
               * C-08 / F2 lock — all instrument navigation uses ticker symbols, not
               * entity_ids. entity_id is a knowledge-graph concept; the instrument
               * detail page routes by ticker (e.g. /instruments/AAPL).
               */
              <div
                key={member.entity_id}
                className="flex h-[20px] min-w-0 items-center cursor-pointer overflow-hidden px-2 hover:bg-muted/40"
                onClick={() => {
                  // WHY ?? member.entity_id: graceful fallback when ticker is missing.
                  // In practice all watchlist members have tickers, but the type
                  // allows null for imported entities without a market ticker.
                  router.push(`/instruments/${member.ticker ?? member.entity_id}`);
                }}
                aria-label={`${member.ticker ?? member.entity_id} — view instrument detail`}
              >
                {/* Ticker — 44px fixed, mono for column alignment (plan §4.5) */}
                <span className="w-[44px] shrink-0 overflow-hidden whitespace-nowrap font-mono text-[11px] tabular-nums text-foreground truncate">
                  {member.ticker ?? member.entity_id.slice(0, 6)}
                </span>
                {/* Price — flex-1 right-aligned, mono; "—" when quote not yet loaded.
                    min-w-0 lets the flex price column shrink instead of pushing
                    the %-change slot off the row edge. */}
                <span className="min-w-0 flex-1 whitespace-nowrap text-right font-mono text-[11px] tabular-nums text-foreground">
                  {quote != null ? quote.price.toFixed(2) : "—"}
                </span>
                {/* Change% — 44px, colored by sign per design token §0.4.
                    formatChangePct bounds extreme moves so the string fits 44px. */}
                <span
                  className={`w-[44px] shrink-0 whitespace-nowrap text-right font-mono text-[11px] tabular-nums ${
                    quote != null
                      ? priceChangeClass(quote.change_pct)
                      : "text-muted-foreground"
                  }`}
                >
                  {quote != null ? formatChangePct(quote.change_pct) : "—"}
                </span>
                {/*
                 * Sparkline column — 40×16 trend-tinted SVG (F1 primitive).
                 * WHY trend="auto": the Sparkline primitive computes direction from
                 * first-vs-last delta with a ±0.1% deadband. This is the FU-5.6
                 * 3-state (positive/negative/flat) locked decision.
                 * WHY 40×16: plan §4.5 fixed dimensions for all watchlist sparklines.
                 * WHY no aria-label here: the parent div already has a full aria-label.
                 */}
                <div className="ml-1 shrink-0 flex items-center">
                  <Sparkline
                    data={sparklinePoints}
                    width={40}
                    height={16}
                    trend="auto"
                  />
                </div>
              </div>
            );
          })
        )}

        {/* ── Overflow link — "+N more →" ─────────────────────────────────
            WHY /watchlists (not /portfolio?tab=watchlists): C-09 / FU-4.2 lock.
            The watchlists management page is now a first-class route. */}
        {extraCount > 0 && (
          <button
            onClick={() => router.push("/watchlists")}
            className="w-full px-2 py-0.5 text-left text-[10px] text-muted-foreground hover:text-foreground transition-colors duration-0"
          >
            +{extraCount} more →
          </button>
        )}
      </div>
    </div>
  );
}
