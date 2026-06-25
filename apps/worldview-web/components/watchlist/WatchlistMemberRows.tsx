/**
 * components/watchlist/WatchlistMemberRows.tsx — Live, dense member table for a watchlist
 *
 * WHY THIS EXISTS
 * ---------------
 * The old /watchlists detail surface rendered members through a 4-column
 * DataTable (Ticker | Name | Status | Added) with NO live market data — a flat,
 * static list that looked like a stub next to the shell sidebar (which DOES show
 * live prices). This component is the finance-grade replacement: it renders each
 * member as a dense terminal row carrying the LIVE numbers a trader scans for —
 * price, day-change %, sector, a 24h-news count and an alert dot.
 *
 * WHERE THE DATA COMES FROM (the MEMBERS=0 root cause)
 * ----------------------------------------------------
 * The hub list endpoint (`GET /v1/watchlists`) intentionally returns metadata
 * ONLY — no members, no counts. That is why the legacy hub showed MEMBERS=0 for
 * every list even though the sidebar (which fetches `/watchlists/{id}/members`)
 * showed real members. We therefore drive BOTH the count AND the live rows off
 * the per-watchlist insights endpoint (`GET /v1/watchlists/{id}/insights`), which
 * the gateway composes server-side from quotes + sectors + news + alerts. One
 * round-trip gives us `members_count` plus a `movers[]` array with live
 * price/change_pct/sector/news — exactly the rich payload this table needs.
 *
 * WHO USES IT: components/watchlist/WatchlistDetailPane.tsx (the right pane of
 * the master-detail workspace on app/(app)/watchlists/page.tsx).
 *
 * DESIGN: Terminal Dark density — 24px rows, 11px mono numerics, tabular-nums,
 * semantic positive/negative color tokens (see docs/ui/DESIGN_SYSTEM.md).
 */

"use client";

import { useRouter } from "next/navigation";
import { Bell } from "lucide-react";
import { cn, formatPrice, formatPercentDirect, priceChangeClass } from "@/lib/utils";
import type { WatchlistMoverEnriched } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

export interface WatchlistMemberRowsProps {
  /** Live, enriched member rows from the insights endpoint. */
  movers: WatchlistMoverEnriched[];
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WatchlistMemberRows({ movers }: WatchlistMemberRowsProps) {
  const router = useRouter();

  // Sort by absolute day-change descending so the most price-active names sit at
  // the top — that is what a trader wants to see first when scanning a list.
  // We copy before sorting (Array.prototype.sort mutates) to avoid surprising
  // the caller's memoised array identity.
  const sorted = [...movers].sort((a, b) => {
    const da = a.change_pct == null ? -1 : Math.abs(a.change_pct);
    const db = b.change_pct == null ? -1 : Math.abs(b.change_pct);
    return db - da;
  });

  return (
    <div className="flex flex-1 flex-col overflow-auto" role="table" aria-label="Watchlist members">
      {/* Column header — sticky so the labels stay visible while scrolling a
          long list. Mono uppercase micro-labels are the terminal convention. */}
      <div
        role="row"
        className="sticky top-0 z-10 flex h-6 shrink-0 items-center gap-2 border-b border-border bg-background px-3 font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground/70"
      >
        <span className="w-16" role="columnheader">Ticker</span>
        <span className="flex-1 truncate" role="columnheader">Name</span>
        <span className="hidden w-36 truncate md:inline" role="columnheader">Sector</span>
        <span className="w-20 text-right" role="columnheader">Price</span>
        <span className="w-20 text-right" role="columnheader">Day</span>
        <span className="w-12 text-right" role="columnheader" title="Articles in the last 24h">News</span>
      </div>

      {/* Data rows */}
      {sorted.map((m) => {
        // The instrument route accepts entity_id when resolved, else the
        // instrument_id — mirrors the legacy members-columns onRowClick target.
        const target = m.entity_id || m.instrument_id || "";
        return (
          <button
            key={m.instrument_id}
            type="button"
            role="row"
            onClick={() => target && router.push(`/instruments/${target}`)}
            className={cn(
              "flex h-6 shrink-0 items-center gap-2 border-b border-border/40 px-3 text-left",
              "transition-colors hover:bg-muted/10 focus:bg-muted/15 focus:outline-none",
            )}
          >
            {/* Ticker — primary accent, the trader's anchor for each row. */}
            <span className="w-16 truncate font-mono text-[11px] tabular-nums text-primary" role="cell">
              {m.ticker}
            </span>

            {/* Name — secondary; truncates so long company names never wrap. */}
            <span className="flex-1 truncate text-[11px] text-foreground" role="cell" title={m.name}>
              {m.name}
            </span>

            {/* Sector — hidden on narrow viewports to protect the numeric cols. */}
            <span
              className="hidden w-36 truncate font-mono text-[10px] text-muted-foreground md:inline"
              role="cell"
              title={m.sector ?? undefined}
            >
              {m.sector ?? "—"}
            </span>

            {/* Price — right-aligned tabular numerics so decimals line up. */}
            <span className="w-20 text-right font-mono text-[11px] tabular-nums text-foreground" role="cell">
              {formatPrice(m.price)}
            </span>

            {/* Day change % — semantic green/red via priceChangeClass. */}
            <span
              className={cn(
                "w-20 text-right font-mono text-[11px] tabular-nums",
                priceChangeClass(m.change_pct),
              )}
              role="cell"
            >
              {formatPercentDirect(m.change_pct)}
            </span>

            {/* News count + alert dot — at-a-glance "is something happening
                here?" signal. The alert dot only renders when there is a
                pending alert for this member's entity. */}
            <span className="flex w-12 items-center justify-end gap-1 font-mono text-[10px] tabular-nums text-muted-foreground" role="cell">
              {m.has_active_alert && (
                <Bell
                  className="h-2.5 w-2.5 text-warning"
                  strokeWidth={2}
                  aria-label="Active alert"
                />
              )}
              {m.news_count_24h > 0 ? m.news_count_24h : "·"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
