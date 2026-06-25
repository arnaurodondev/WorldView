/**
 * components/dashboard/MarketBreadthMini.tsx — sector-breadth mini panel
 *
 * WHY THIS EXISTS (W4 task 3, user report 2026-06-12): the user likes the
 * Market Clock but it wasted vertical space — so we slimmed the clock and
 * stacked a SECOND mini beneath it in the same dashboard column. This is that
 * second mini.
 *
 * WHAT IT SHOWS — "market breadth" derived from the 13 GICS sectors:
 *   - The count of sectors that are UP vs DOWN today (advancers / decliners).
 *   - A compact horizontal up/down bar (green/red proportional split) — the
 *     same visual idiom a Bloomberg breadth gauge uses.
 *   - The "% of sectors positive" headline number (mono numerics).
 *
 * WHY DERIVE FROM THE SECTOR/HEATMAP DATA (no new endpoint): the dashboard
 * already fetches `GET /v1/market/heatmap` for the SectorHeatmapWidget. There
 * is NO dedicated advancers/decliners endpoint in the S9 gateway (checked
 * docs/services/api-gateway.md — only `/v1/market/heatmap`, `/v1/market/
 * top-movers`, `/v1/market/tape`). Rather than invent a backend gap, we read
 * the SAME cached heatmap payload (identical TanStack query key + queryFn as
 * SectorHeatmapWidget) and compute breadth over its 13 sectors client-side.
 * That means this mini adds ZERO extra network requests — it's a pure
 * projection of data already on the page. "13 sectors, 9 up / 4 down" is an
 * honest, useful breadth read for a sector-level dashboard.
 *
 * (If a true advancers/decliners feed over the full equity universe is added
 * to S9 later, this component can swap its source without changing its shape.)
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx — stacked under MarketClockWidget
 * in the Row-2 col-2 column.
 * DATA SOURCE: S9 GET /v1/market/heatmap (shared cache, no extra fetch).
 */

"use client";
// WHY "use client": uses useQuery (TanStack) + useAuth for the bearer token.

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// Named empty/error states use the shared EmptyState primitive (§15.12) so the
// copy is registry-driven and consistent with the other dashboard widgets.
import { EmptyState } from "@/components/primitives/EmptyState";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Constants ─────────────────────────────────────────────────────────────────

/**
 * SHARED_HEATMAP_KEY — the EXACT TanStack query key SectorHeatmapWidget uses
 * for its 1D heatmap fetch (`["sector-heatmap-widget", "1D"]`). Reusing it here
 * means both widgets read the same cache entry — TanStack fires the underlying
 * `GET /v1/market/heatmap?period=1D` request only once for the whole page.
 *
 * WHY hard-code "1D" (not a selectable period): breadth is a "right now" market
 * read — advancers/decliners over a 1-month window is a different (and rarer)
 * question. Keeping it pinned to the daily session also guarantees the cache
 * hit against SectorHeatmapWidget's DEFAULT period (which is also "1D").
 */
const SHARED_HEATMAP_KEY = ["sector-heatmap-widget", "1D"] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketBreadthMini() {
  const { accessToken } = useAuth();

  // Read the shared heatmap cache. Because the queryKey + queryFn are identical
  // to SectorHeatmapWidget's 1D query, TanStack dedupes: whichever widget
  // mounts first triggers the fetch, the other reads the cached result.
  const {
    data: heatmap,
    isLoading,
    isError,
  } = useQuery({
    queryKey: SHARED_HEATMAP_KEY,
    queryFn: () => createGateway(accessToken).getMarketHeatmap("1D"),
    enabled: !!accessToken,
    // Same staleness window as SectorHeatmapWidget so the shared cache entry
    // doesn't get invalidated out from under the other consumer.
    staleTime: 300_000,
    refetchInterval: 300_000,
  });

  // ── Compute breadth over the sector list ────────────────────────────────────
  // WHY useMemo: the reduce runs over ≤13 sectors — cheap, but recomputing on
  // every parent re-render (the column also hosts the 1 Hz clock) is wasteful.
  const breadth = useMemo(() => {
    const sectors = heatmap?.sectors ?? [];
    let up = 0;
    let down = 0;
    let flat = 0;
    for (const s of sectors) {
      // null change_pct = no data for that sector today → counts as neither up
      // nor down (excluded from the ratio so it never skews the bar).
      if (s.change_pct == null) {
        flat += 1;
        continue;
      }
      if (s.change_pct > 0) up += 1;
      else if (s.change_pct < 0) down += 1;
      else flat += 1; // exactly 0.00% — rare, but truthfully "unchanged".
    }
    // total = sectors with a directional read (up + down). Flat/no-data sectors
    // are excluded from the percentage so "% positive" reflects the decisive
    // sectors only. Guard div-by-zero when every sector is flat/no-data.
    const decisive = up + down;
    const pctPositive = decisive > 0 ? (up / decisive) * 100 : 0;
    return { up, down, flat, decisive, pctPositive, total: sectors.length };
  }, [heatmap]);

  // ── Panel chrome (shared across all states) ────────────────────────────────
  const header = (
    <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        MARKET BREADTH
      </span>
      {/* Sector count caption — font-mono so it lines up if it ever changes. */}
      {breadth.total > 0 && (
        <span className="font-mono text-[9px] tabular-nums text-muted-foreground-dim">
          {breadth.total} sectors
        </span>
      )}
    </div>
  );

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div
        className="flex h-full flex-col border border-border/40 bg-background"
        role="region"
        aria-label="Market breadth"
      >
        {header}
        {/* A single skeleton bar mirroring the loaded breadth bar's height so
            the panel doesn't jump when data arrives. */}
        <div className="flex flex-1 flex-col justify-center gap-1 px-2">
          <div className="h-2.5 w-full animate-pulse rounded-[2px] bg-muted/40" />
          <div className="h-2.5 w-2/3 animate-pulse rounded-[2px] bg-muted/30" />
        </div>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div
        className="flex h-full flex-col border border-border/40 bg-background"
        role="region"
        aria-label="Market breadth"
      >
        {header}
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-no-data"
            copyKey="dashboard.breadth-error"
            icon={Activity}
          />
        </div>
      </div>
    );
  }

  // ── Empty state — heatmap returned zero sectors (or all no-data) ───────────
  if (breadth.total === 0 || breadth.decisive === 0) {
    return (
      <div
        className="flex h-full flex-col border border-border/40 bg-background"
        role="region"
        aria-label="Market breadth"
      >
        {header}
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-no-data"
            copyKey="dashboard.no-breadth-data"
            icon={Activity}
          />
        </div>
      </div>
    );
  }

  // ── Loaded state ───────────────────────────────────────────────────────────
  // Bar split: the up segment's width is `up / decisive`. We compute it as a
  // percentage so the two flex segments fill the bar exactly (no rounding gap).
  const upWidthPct = (breadth.up / breadth.decisive) * 100;

  return (
    <div
      className="flex h-full flex-col border border-border/40 bg-background"
      role="region"
      aria-label="Market breadth"
    >
      {header}

      {/* Body — centered column: headline %, the up/down bar, the counts. */}
      <div className="flex flex-1 flex-col justify-center gap-1 px-2">
        {/* Headline — "% of sectors positive". font-mono + tabular-nums per
            ADR-F-15. Color-coded: >50% positive reads teal, <50% reads red,
            exactly 50% stays neutral foreground. */}
        <div className="flex items-baseline justify-between">
          <span
            className={cn(
              "font-mono text-[16px] font-semibold tabular-nums",
              breadth.pctPositive > 50 && "text-positive",
              breadth.pctPositive < 50 && "text-negative",
              breadth.pctPositive === 50 && "text-foreground",
            )}
          >
            {breadth.pctPositive.toFixed(0)}%
          </span>
          <span className="font-mono text-[9px] uppercase tracking-[0.06em] text-muted-foreground-dim">
            positive
          </span>
        </div>

        {/* Up/down proportional bar — green advancers segment on the left,
            red decliners on the right. role="img" + aria-label gives screen
            readers the breakdown without reading two empty <div>s. */}
        <div
          className="flex h-2 w-full overflow-hidden rounded-[2px] border border-border/40"
          role="img"
          aria-label={`${breadth.up} sectors up, ${breadth.down} sectors down`}
        >
          <div
            className="h-full bg-positive"
            style={{ width: `${upWidthPct}%` }}
            data-testid="breadth-up-segment"
          />
          <div
            className="h-full flex-1 bg-negative"
            data-testid="breadth-down-segment"
          />
        </div>

        {/* Advancers / decliners counts — mono numerics, color-coded so the
            two numbers read as up vs down at a glance. */}
        <div className="flex items-center justify-between font-mono text-[10px] tabular-nums">
          <span className="text-positive">{breadth.up} up</span>
          {/* Flat/no-data caption only shown when non-zero — avoids "0 flat"
              noise on a fully-decisive session. */}
          {breadth.flat > 0 && (
            <span className="text-muted-foreground-dim">{breadth.flat} flat</span>
          )}
          <span className="text-negative">{breadth.down} down</span>
        </div>
      </div>
    </div>
  );
}
