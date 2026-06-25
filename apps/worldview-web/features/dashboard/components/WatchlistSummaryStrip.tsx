// Server Component — no hooks, no browser APIs, no event handlers, no interactive shadcn imports.
// Pure data display: formats and renders WatchlistInsights props as static JSX.
// Do not re-add "use client" without checking all of the above.

/**
 * features/dashboard/components/WatchlistSummaryStrip.tsx
 *
 * Single-row header (22px) showing equal-weighted return, sector
 * concentration mini-bar, and pending-alerts total — rendered above the
 * gainers/losers split inside the Watchlist Movers widget.
 *
 * WHY EXTRACTED (PLAN-0059 E-5): originally inline in
 * `WatchlistMoversWidget.tsx`. Splitting it out shrinks the widget orchestrator.
 *
 * WHY a single 22px strip (not three): the dashboard cell is height-bounded
 * (Row 2 = 130px). Stacking three header strips eats data rows. One strip
 * with three logical zones gives the user the same information density as
 * Bloomberg's account summary line.
 *
 * Sector mini-bar visual: a flex row of fills proportional to sector.weight.
 * Top-3 sectors get distinct hsl(var(--positive/warning/primary)) tints so
 * the user can tell at a glance whether their watchlist is concentrated in
 * one bucket. A 4th+ sector shows muted ("Other") to keep the strip readable.
 */

import { Bell } from "lucide-react";
import { cn } from "@/lib/utils";
import type { WatchlistInsights } from "@/types/api";

export interface WatchlistSummaryStripProps {
  insights: WatchlistInsights;
}

export function WatchlistSummaryStrip({ insights }: WatchlistSummaryStripProps) {
  const wr = insights.weighted_return_1d;
  const wrColor =
    wr == null
      ? "text-muted-foreground"
      : wr > 0.005
        ? "text-positive"
        : wr < -0.005
          ? "text-negative"
          : "text-muted-foreground";

  // Top-3 sectors get colour; everything else collapses into "Other" so the
  // mini-bar stays scannable even on diverse 20+ symbol watchlists.
  const top3 = insights.sectors.slice(0, 3);
  const otherWeight = insights.sectors.slice(3).reduce((s, x) => s + x.weight, 0);
  // Slot colours for the top-3 buckets — chosen for legibility on the dark
  // panel background, not by sector identity (sectors aren't colour-coded
  // canonically anywhere in the design system).
  // Round 3 (item 2, §15.11): semantic Tailwind utilities replace the
  // arbitrary-value bg-[hsl(var(--token))] forms — the hsl(var()) spelling is
  // reserved for canvas/SVG/raw-CSS contexts; JSX backgrounds use the mapped
  // utilities so the no-off-palette arch gate can reason about them.
  const slotColors = ["bg-primary", "bg-warning", "bg-positive"] as const;

  return (
    <div
      className="flex h-[22px] shrink-0 items-center gap-2 border-b border-border/30 px-2"
      aria-label="Watchlist summary"
    >
      {/* Equal-weighted return slot */}
      <span className="flex shrink-0 items-center gap-1 font-mono text-[10px] tabular-nums">
        <span className="text-muted-foreground">RET</span>
        <span className={wrColor}>
          {wr == null ? "—" : `${wr >= 0 ? "+" : ""}${wr.toFixed(2)}%`}
        </span>
      </span>

      {/* Members count */}
      <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
        · {insights.members_count} {insights.members_count === 1 ? "name" : "names"}
      </span>

      {/* Sector concentration mini-bar — flex-1 so it fills the remaining slot. */}
      <div
        className="flex h-2 flex-1 overflow-hidden rounded-[2px] bg-muted/40"
        aria-label="Sector concentration"
        title={top3.map((s) => `${s.sector} ${(s.weight * 100).toFixed(0)}%`).join(", ")}
      >
        {top3.map((s, i) => (
          <span
            key={s.sector}
            className={cn("h-full", slotColors[i])}
            style={{ width: `${s.weight * 100}%` }}
          />
        ))}
        {otherWeight > 0 && (
          <span
            className="h-full bg-muted-foreground/40"
            style={{ width: `${otherWeight * 100}%` }}
          />
        )}
      </div>

      {/* Pending-alerts counter — only shown when > 0 to keep the strip
          quiet on calm days. */}
      {insights.alerts_count > 0 && (
        <span className="flex shrink-0 items-center gap-0.5 font-mono text-[10px] tabular-nums text-destructive">
          <Bell className="h-3 w-3" aria-hidden="true" />
          <span>{insights.alerts_count}</span>
        </span>
      )}
    </div>
  );
}
