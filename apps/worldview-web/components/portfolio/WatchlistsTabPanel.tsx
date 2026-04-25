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
// WHY "use client": uses useState for active tab, useRouter for row navigation.

import { useState } from "react";
import { useRouter } from "next/navigation";
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

      {/* ── Active watchlist table ─────────────────────────────────────── */}
      <WatchlistTable
        watchlist={activeWatchlist}
        quotes={quotes}
        onRowClick={handleRowClick}
      />
    </div>
  );
}
