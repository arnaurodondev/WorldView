"use client";

/**
 * features/dashboard/components/WatchlistMoverRow.tsx
 *
 * One row of [optional alert dot · ticker · name · optional news badge ·
 * price · change%] inside the Watchlist Movers widget's gainers/losers
 * columns.
 *
 * WHY EXTRACTED (PLAN-0059 E-5): the row was defined inline in
 * `WatchlistMoversWidget.tsx`. Moving it here makes the widget's render
 * tree easier to skim and lets future drill-down panels reuse the same
 * row shape (e.g. a per-portfolio movers panel).
 *
 * WHY h-7 (28px) instead of the dashboard's typical h-[22px]: spec calls
 * for a slightly taller row in this widget so the longer name column
 * (truncated) doesn't crowd the price+% on the right at col-span-5.
 * 28px = comfortable touch target while staying dense enough that 5+5
 * rows fit within Row 2's height budget.
 *
 * WHY text-[11px]: matches §0 Terminal Quality Rules data-text size.
 * Tabular-nums + font-mono on price and change% keeps columns aligned
 * across rows even when the digit count varies (e.g. $9.99 vs $192.50).
 */

import { Newspaper } from "lucide-react";
import { cn } from "@/lib/utils";
import type { WatchlistMover } from "../lib/movers";

export interface WatchlistMoverRowProps {
  mover: WatchlistMover;
  side: "gainer" | "loser";
  /**
   * F-QA-07 fix: gate the row-level enrichment badges (newspaper count + alert
   * dot) on period === "1D". The insights endpoint sources these from the
   * 24h news window and current pending alerts, both of which are 1D
   * semantics. Showing them next to a 1W or 1M change_pct would mislead
   * the user ("AAPL up 12% this month" with a "3" badge that's actually
   * 24h news count).
   */
  showEnrichmentBadges: boolean;
  onClick: () => void;
}

export function WatchlistMoverRow({
  mover,
  side,
  showEnrichmentBadges,
  onClick,
}: WatchlistMoverRowProps) {
  // Build the aria-label so SR users hear ticker + state badges in one pass
  // (instead of the dot + icon being unlabelled and silent).
  // F-QA-07: only enumerate badges when they're actually rendered.
  const badgeBits: string[] = [];
  if (showEnrichmentBadges && mover.hasActiveAlert) badgeBits.push("active alert");
  if (showEnrichmentBadges && mover.newsCount24h > 0) {
    badgeBits.push(`${mover.newsCount24h} recent news`);
  }
  const ariaLabel = `Open ${mover.ticker} instrument page${badgeBits.length ? `; ${badgeBits.join(", ")}` : ""}`;

  return (
    // WHY role="button" + tabIndex=0: rows are interactive but not <button>
    // elements (so we can layout-as-a-flex row with full bleed). Adding the
    // role + tab makes them accessible to keyboard + screen-reader users.
    <div
      className="flex h-7 cursor-pointer items-center gap-1.5 px-2 transition-colors hover:bg-muted/30"
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter") onClick();
      }}
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
    >
      {/* PLAN-0050 T-B-2-05: active-alert dot — 6px destructive when there
          is at least one pending alert tagged to this member's entity_id.
          F-QA-07: rendered ONLY on 1D period (the alert flag is a 1D snapshot
          from the insights endpoint). On 1W/1M we skip both the dot and its
          reserved slot — the row layout still aligns because every row in
          that period drops the slot uniformly. */}
      {showEnrichmentBadges &&
        (mover.hasActiveAlert ? (
          <span
            className="h-[6px] w-[6px] shrink-0 rounded-full bg-destructive"
            aria-hidden="true"
            title="Active alert"
          />
        ) : (
          // Reserve the slot so ticker columns align across rows even when
          // a row has no dot — otherwise the slot collapses and tickers
          // shift left by 8px on rows with alerts.
          <span className="h-[6px] w-[6px] shrink-0" aria-hidden="true" />
        ))}

      {/* Ticker — fixed slot for column alignment across rows */}
      {/* WHY font-semibold (was font-bold): 700-weight at 11px causes blotchy subpixel
          rendering on dark themes — 600-weight is the maximum for terminal chrome text
          at small sizes (Bloomberg density rule) */}
      <span className="w-[40px] shrink-0 font-mono text-[11px] font-semibold tabular-nums text-foreground">
        {mover.ticker}
      </span>

      {/* Name — flex-1 + truncate so long company names don't push price
          off the right edge. min-w-0 on the parent flex row is what
          actually allows truncate to work — flex children default to
          min-content width otherwise. */}
      <span className="min-w-0 flex-1 truncate text-[10px] text-muted-foreground">
        {mover.name}
      </span>

      {/* PLAN-0050 T-B-2-04: news-of-the-day icon with badge count.
          Renders only when news_count_24h > 0 AND showEnrichmentBadges.
          F-QA-07: gated on 1D — the count is from the 24h window. Tooltip
          shows the top-news title so users can decide whether to click
          before navigating. */}
      {showEnrichmentBadges && mover.newsCount24h > 0 && (
        <span
          className="flex shrink-0 items-center gap-0.5 text-warning"
          title={mover.topNewsTitle ?? `${mover.newsCount24h} recent`}
          aria-hidden="true"
        >
          <Newspaper className="h-3 w-3" />
          <span className="font-mono text-[9px] tabular-nums">
            {mover.newsCount24h > 9 ? "9+" : mover.newsCount24h}
          </span>
        </span>
      )}

      {/* Price — right-aligned in a fixed slot. Muted color because change%
          is the primary signal; price is supporting context. */}
      <span className="w-[52px] shrink-0 text-right font-mono text-[10px] tabular-nums text-muted-foreground">
        {mover.price != null ? `$${mover.price.toFixed(2)}` : "—"}
      </span>

      {/* Change % — right-aligned, colored by direction. The `side`
          parameter reflects which column we're in, which (combined with
          the partition logic above) is always consistent with the sign
          of changePct. */}
      <span
        className={cn(
          "w-[52px] shrink-0 text-right font-mono text-[11px] tabular-nums",
          side === "gainer" ? "text-positive" : "text-negative",
        )}
      >
        {mover.changePct != null
          ? `${mover.changePct >= 0 ? "+" : ""}${mover.changePct.toFixed(2)}%`
          : "—"}
      </span>
    </div>
  );
}
