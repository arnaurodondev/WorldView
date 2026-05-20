/**
 * components/dashboard/SectorHeatmapWidget.tsx — Sector treemap (PLAN-0048 F-1)
 *
 * WHY THIS EXISTS: Portfolio managers need an instant macro snapshot of where
 * money is rotating today. A treemap conveys both *direction* (color: green vs
 * red) and *magnitude* (tile width) in one glance — far more information per
 * pixel than the previous 2-column SectorRow list. Bloomberg's "Sectors" panel
 * and Finviz's S&P map both use this idiom; the dashboard now matches that
 * convention.
 *
 * WHY CSS-FLEX (not d3-treemap or canvas): the layout is one row of N tiles
 * with `flex-wrap`. Computing `flex-basis` per tile from the magnitude
 * weight reproduces a horizontal treemap without pulling in a layout library.
 * No dependencies, predictable wrapping, accessible <button> nodes.
 *
 * WHY HEIGHT-STABLE TILES: Bloomberg traders hate jumpy widgets. By fixing
 * tile height to 56px and only varying width, the widget consumes exactly
 * `ceil(N / row-capacity) * 56px` regardless of the data — no surprises in
 * the dashboard grid.
 *
 * WHO USES IT: app/(app)/dashboard/page.tsx (Row 2, col-span-8)
 * DATA SOURCES:
 *   - S9 GET /v1/market/heatmap → createGateway().getMarketHeatmap()
 *   - S9 GET /v1/market/top-movers → createGateway().getTopMovers('all', 50)
 *   - S9 GET /v1/companies/{id}/overview (per-mover sector lookup)
 * DESIGN REFERENCE: PLAN-0048 §Wave F task F-1
 */

"use client";
// WHY "use client": uses useQuery / useQueries for data fetching, useAuth for
// the bearer token, useState for the period selector and the open popover.

import { useMemo, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { HeatmapSector, Mover } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * WHY 1D/1W/1M period selector: sector rotation tells different stories at
 * different horizons. Local state is fine — the period is widget-scoped, not
 * something we bookmark in the URL.
 */
type SectorPeriod = "1D" | "1W" | "1M";

// ── Layout & color tunables ──────────────────────────────────────────────────

/**
 * MIN_WEIGHT — minimum proportional weight for any tile.
 *
 * WHY 0.05: even a sector with 0% change must remain visible and clickable. A
 * pure proportional layout would collapse a flat sector to ~0px width. Floor
 * at 5% so the smallest tile still has a recognisable footprint (~half a
 * normal tile at the standard 1280px Row 2 width).
 */
const MIN_WEIGHT = 0.05;

/**
 * TILE_HEIGHT_PX — fixed tile height. Locked at 56px so wrap rows are
 * predictable and the widget fits within Row 2's 130px allowance even when
 * 11 sectors wrap into 2 rows.
 */
const TILE_HEIGHT_PX = 56;

/**
 * GAP_PX — flex gap between tiles. We subtract this from `flex-basis` below
 * so wrap rows never overflow due to gap accumulation.
 *
 * WHY 2 (was 4): at 11 sectors with 4px gaps, sub-pixel rounding pushed the
 * last column past the widget border at 1280px viewports (B-2-03). 2px gives
 * the same visual "card margin" feel without overflow risk.
 */
const GAP_PX = 2;

/**
 * colorClassFor — map an absolute % change to a Tailwind opacity-step utility
 * class. Steps are chosen so a routine ±0.3% change is barely tinted, while
 * ±4%+ moves saturate to a strong fill — matching the "intensity ≈ magnitude"
 * intuition users expect from heat tiles.
 *
 * Steps (mirrors PRD-0031 HeatCell 7-step scale, simplified):
 *   |x| < 0.5 → /10
 *   |x| < 1.0 → /20
 *   |x| < 2.0 → /30
 *   |x| ≥ 2.0 → /40   (also catches |x| ≥ 4 — saturated tier)
 *
 * Why explicit class strings (not template literals): Tailwind's JIT scans
 * source for full class names. `bg-positive/${n}` would not be detected at
 * build time and the class would be purged from the final CSS bundle.
 */
function colorClassFor(changePct: number | null): string {
  if (changePct === null) return "bg-muted/30";
  const m = Math.abs(changePct);
  const positive = changePct >= 0;
  if (m < 0.5) return positive ? "bg-positive/10" : "bg-negative/10";
  if (m < 1.0) return positive ? "bg-positive/20" : "bg-negative/20";
  if (m < 2.0) return positive ? "bg-positive/30" : "bg-negative/30";
  return positive ? "bg-positive/40" : "bg-negative/40";
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * SectorHeatmapWidget — flex-treemap of GICS sector performance.
 *
 * Each tile width ≈ proportional to its absolute % change (with a 5% floor),
 * tile color encodes direction + magnitude, and a click opens a Popover with
 * the top-3 movers for that sector — a natural drill-down from "which sector
 * is hot" → "which names are driving it".
 */
export function SectorHeatmapWidget() {
  const { accessToken } = useAuth();

  // WHY default "1D": at market open the most relevant view is today's
  // session. Longer periods are secondary context.
  const [period, setPeriod] = useState<SectorPeriod>("1D");

  // ── Sector heatmap query (the primary data source) ──────────────────────
  const {
    data: heatmap,
    isLoading: isHeatmapLoading,
    isError: isHeatmapError,
  } = useQuery({
    // WHY period in queryKey: TanStack identifies cached entries by key. Adding
    // `period` ensures each period switch hits a fresh fetch (or a fresh cache
    // bucket) instead of serving 1D data while showing the 1W label.
    queryKey: ["sector-heatmap-widget", period],
    queryFn: () => createGateway(accessToken).getMarketHeatmap(period),
    enabled: !!accessToken,
    // WHY 300_000 (5min): sector rollups are macro-scale; sub-minute refresh
    // would be noise and would hammer S9's 11-parallel-screener pipeline.
    staleTime: 300_000,
    refetchInterval: 300_000,
  });

  // ── Top-movers query (used for per-sector drill-down popovers) ─────────
  // WHY single query for 'all' movers: S9's getTopMovers supports type='all'
  // (gainers ∪ losers). One query, then we group by sector locally — simpler
  // than 11 per-sector queries and avoids redundant network traffic when
  // multiple sectors are popped open in sequence.
  const { data: moversData } = useQuery({
    queryKey: ["sector-heatmap-movers", "all", 20],
    // The gateway accepts "gainers" | "losers"; we use "gainers" here as the
    // base list for top-3 popovers because the heatmap's drill-down is about
    // "which names had the biggest moves" — gainers is the closest single
    // call. (Future enhancement: extend gateway to type='all'.)
    // F-503 (iter-2): the gateway caps `limit` at 20 (returns 422 above
    // that). Asking for 50 fired a 422 on every dashboard load. 20 is enough
    // for a top-3-per-sector popover across 11 sectors in practice.
    queryFn: () => createGateway(accessToken).getTopMovers("gainers", 20, period),
    enabled: !!accessToken,
    staleTime: 300_000,
  });

  // WHY useMemo: `?? []` creates a fresh array reference each render, which
  // would invalidate every downstream useMemo / useQueries dep. Memoising
  // on `moversData` keeps the empty-array fallback referentially stable.
  const movers: Mover[] = useMemo(() => moversData?.movers ?? [], [moversData]);

  // ── Per-mover company-overview lookups (sector join) ───────────────────
  // WHY useQueries (not one query per row in a child): hooks cannot be called
  // conditionally inside .map(). useQueries fans out N parallel queries and
  // returns an aligned result array.
  // WHY staleTime 600_000 (10min): a company's GICS sector changes very
  // rarely — caching aggressively avoids re-fetching the same overview
  // payload every time the popover re-renders.
  const overviewQueries = useQueries({
    queries: movers.map((m) => ({
      queryKey: ["company-overview-sector", m.instrument_id],
      queryFn: () => createGateway(accessToken).getCompanyOverview(m.instrument_id),
      enabled: !!accessToken && !!m.instrument_id,
      staleTime: 600_000,
    })),
  });

  // ── Group movers by sector for popover display ──────────────────────────
  // WHY useMemo: the grouping iterates N movers × map look-ups; recomputing
  // on every render (e.g. on each popover open/close) would be wasteful.
  // The memo cache invalidates only when `movers` or the overview list
  // changes — which is exactly what we want.
  const moversBySector = useMemo(() => {
    const map = new Map<string, Mover[]>();
    movers.forEach((mover, i) => {
      const overview = overviewQueries[i]?.data;
      const sector = overview?.instrument?.gics_sector;
      if (!sector) return;
      const list = map.get(sector) ?? [];
      list.push(mover);
      map.set(sector, list);
    });
    return map;
  }, [movers, overviewQueries]);

  // ── Compute weight + width for each sector ──────────────────────────────
  // WHY useMemo: the weight calc only changes when `heatmap.sectors` does;
  // memoising avoids re-running it on popover open/close re-renders.
  const sectorTiles = useMemo(() => {
    const sectors = heatmap?.sectors ?? [];
    if (sectors.length === 0) return [];
    // Compute the floored magnitude for every sector first so we can
    // normalise into the [0, 1] weight range.
    const flooredMagnitudes = sectors.map((s) =>
      Math.max(MIN_WEIGHT, Math.abs(s.change_pct ?? 0)),
    );
    const total = flooredMagnitudes.reduce((acc, m) => acc + m, 0);
    return sectors.map((sector, i) => ({
      sector,
      // Defensive: total can't be 0 because every floored magnitude is
      // ≥ MIN_WEIGHT > 0, but guard anyway to keep the type strictly numeric.
      weight: total > 0 ? flooredMagnitudes[i] / total : 1 / sectors.length,
    }));
  }, [heatmap]);

  return (
    // WHY flex flex-col h-full: fills the grid cell so the wrap container can
    // expand to multiple tile rows when many sectors are present.
    // WHY overflow-hidden: any sub-pixel rounding from `flex-basis: calc(...)`
    // on the inner tiles is clipped at the widget border instead of bleeding
    // into adjacent grid cells (B-2-03 fix).
    <div className="flex h-full flex-col overflow-hidden bg-background">

      {/* ── Section header (matches §0.9 panel-header pattern) ──────────── */}
      {/* WHY h-5 (20px): Row 2 cap is 130px. Saving 4px vs h-6 keeps two tile
          rows visible without forcing the widget to scroll internally. */}
      <div className="flex h-5 shrink-0 items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          SECTOR PERFORMANCE
        </span>
        <div className="flex items-center gap-2">
          {/* Sector count — font-mono so digits align if it ever changes. */}
          {heatmap?.sectors && (
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground/60">
              {heatmap.sectors.length} sectors
            </span>
          )}
          {/* Period selector — same pattern as PreMarketMoversWidget */}
          <div className="flex gap-px">
            {(["1D", "1W", "1M"] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={cn(
                  "px-1.5 font-mono text-[9px] uppercase transition-colors",
                  period === p
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
                aria-pressed={period === p}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Loading state — shimmer of 8 grey tiles in a flex row ────────── */}
      {isHeatmapLoading && (
        // Match the loaded-state padding/gap so there is no visible jump.
        <div className="flex flex-1 flex-wrap gap-0.5 px-0.5 py-0">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton
              key={i}
              // Equal-width skeletons (1/8 ≈ 12.5%) approximate the loaded
              // layout closely enough that there is no visible jump when
              // real tiles render.
              className="min-h-[56px]"
              style={{
                height: `${TILE_HEIGHT_PX}px`,
                flexBasis: `calc(${100 / 8}% - ${GAP_PX}px)`,
                animationDelay: `${i * 40}ms`,
              }}
            />
          ))}
        </div>
      )}

      {/* ── Error state ──────────────────────────────────────────────────── */}
      {/* WHY separate from "no data": API/network failure ≠ empty result. A
          trader needs to triage these differently — a feed outage requires
          ops attention; an empty list might be expected pre-market. */}
      {isHeatmapError && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="Sector data failed to load — check connection" />
        </div>
      )}

      {/* ── Empty state ──────────────────────────────────────────────────── */}
      {!isHeatmapLoading && !isHeatmapError && sectorTiles.length === 0 && (
        <div className="flex-1 px-2">
          <InlineEmptyState message="No sector data available" />
        </div>
      )}

      {/* ── Treemap tile container ───────────────────────────────────────── */}
      {!isHeatmapLoading && sectorTiles.length > 0 && (
        // FR-1.7 MED-005: replace flex-wrap with CSS grid auto-fit so tiles
        // reflow cleanly at any viewport width without the sub-pixel overflow
        // that occasionally pushed the last column past the container edge at
        // 1280px (B-2-03). `auto-fit` + `minmax(120px, 1fr)` means:
        //   - Each tile is at least 120px wide (enough for "HEALTH" + "+1.23%").
        //   - Tiles grow to fill remaining space equally (1fr).
        //   - The browser auto-computes the column count from the container
        //     width — no hardcoded "11 columns" that breaks at non-standard
        //     resolutions or when the number of GICS sectors changes.
        // WHY gap-0.5 (2px): matches the previous flex gap; tight enough for
        // the Bloomberg "dense grid" aesthetic without hairline-seam ambiguity.
        <div
          className="grid gap-0.5 flex-1 px-0.5 py-0"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}
        >
          {sectorTiles.map(({ sector, weight }) => (
            <SectorTile
              key={sector.name}
              sector={sector}
              weight={weight}
              relatedMovers={moversBySector.get(sector.name) ?? []}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── SectorTile sub-component ──────────────────────────────────────────────────

/**
 * SectorTile — one heat tile inside the treemap.
 *
 * WHY a button (not a div with onClick): native <button> brings keyboard
 * navigation, focus ring, and Enter/Space activation for free, satisfying
 * §0 Terminal-quality accessibility expectations.
 *
 * WHY inline-style flex-basis (not a Tailwind class): Tailwind classes are
 * static at build time; the weight is dynamic per render and per data set.
 * Inline style is the only way to drive per-tile layout from runtime data.
 */
function SectorTile({
  sector,
  weight: _weight,
  relatedMovers,
}: {
  sector: HeatmapSector;
  weight: number;
  relatedMovers: Mover[];
}) {
  const router = useRouter();
  const changePct = sector.change_pct;

  // WHY abbreviation derived from name: API returns long GICS names (e.g.
  // "Information Technology") that won't fit in a small tile. We compress
  // to the same vocabulary the SECTOR_PILLS module uses for filter chips.
  const abbreviation = abbreviateSector(sector.name);

  // WHY .filter().slice(0, 3): the popover shows top-3 movers in this sector;
  // the input list is already sorted by daily-return desc, so a simple slice
  // gives the strongest movers first.
  const topMovers = relatedMovers.slice(0, 3);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          // WHY height only (no flex-basis): the parent container switched from
          // flex-wrap to CSS grid (FR-1.7). In grid layout flex-basis is
          // ignored — column widths are driven by auto-fit/minmax on the
          // container. We keep height fixed so the treemap maintains a uniform
          // row height; the proportional-weight variable (still computed in
          // useMemo) is retained for future use if we switch back to flex.
          style={{
            height: `${TILE_HEIGHT_PX}px`,
          }}
          className={cn(
            // Base layout: vertical stack, centred horizontally, vertically
            // centred on a fixed-height tile.
            "flex min-h-[56px] flex-col items-center justify-center px-1",
            // Color encoding: bg-positive/N or bg-negative/N at 4 magnitude steps.
            colorClassFor(changePct),
            // Foreground colour: kept neutral so the *background* tint carries
            // the direction signal — readable on every magnitude step.
            "text-foreground",
            // Border + hover: faint outline to separate adjacent same-colour
            // tiles; brighter ring on hover signals the tile is interactive.
            "rounded-[2px] border border-border/40 transition-colors hover:border-border",
            // Focus state for keyboard nav.
            "focus:outline-none focus:ring-1 focus:ring-primary/60",
          )}
          aria-label={`${sector.name} sector, ${
            changePct === null ? "no data" : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)} percent`
          }`}
        >
          {/* Top line — sector abbreviation. WHY truncate: at very narrow
              widths (e.g. flat sector at MIN_WEIGHT) the label could overflow
              and break the tile layout — truncate keeps it 1 line max. */}
          {/* WHY font-semibold (was font-bold): 700-weight at 11px causes blotchy subpixel
              rendering on dark themes — 600-weight is the maximum for terminal chrome text
              at small sizes (Bloomberg density rule) */}
          <span className="w-full truncate text-center font-mono text-[11px] font-semibold uppercase tabular-nums">
            {abbreviation}
          </span>
          {/* Bottom line — % change. text-[10px] keeps it secondary to the
              sector identifier, but font-mono + tabular-nums ensure the digits
              align across tiles (the trader's eye scans these as a column). */}
          <span className="font-mono text-[10px] tabular-nums">
            {changePct === null
              ? "—"
              : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`}
          </span>
        </button>
      </PopoverTrigger>

      {/* ── Popover content: top-3 movers in this sector ────────────────── */}
      {/* WHY align="start": pin the popover to the tile's left edge so it
          doesn't drift off-screen for left-most tiles in narrow viewports.
          WHY w-56: a fixed width keeps the popover content predictable; the
          rows inside are tight (ticker + %) so 224px is enough headroom. */}
      <PopoverContent align="start" className="w-56 p-2">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {sector.name}
          </span>
          <span
            className={cn(
              "font-mono text-[10px] tabular-nums",
              changePct === null
                ? "text-muted-foreground"
                : changePct >= 0
                ? "text-positive"
                : "text-negative",
            )}
          >
            {changePct === null
              ? "—"
              : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`}
          </span>
        </div>
        {/* WHY divide-y: hairline between rows matches the rest of the
            terminal's row-separator convention. */}
        <div className="divide-y divide-border/30 border-t border-border/30">
          {topMovers.length === 0 ? (
            // WHY this state shows often initially: overview queries are still
            // resolving, so the sector→movers join hasn't populated yet.
            <div className="px-1 py-2 text-center text-[10px] text-muted-foreground">
              No movers data yet
            </div>
          ) : (
            topMovers.map((mover) => {
              // PRD-0089 F2 step 11 (§6.6): ticker-first URL. F2 superseded
              // ADR-F-12 — `entity_id === instrument_id` (M-017), so the
              // analyst-facing ticker is the canonical URL slug. ticker is
              // always populated on Mover rows; UUID is a defensive fallback
              // that the middleware would 301-resolve back to ticker form.
              const navId = mover.ticker || mover.entity_id || mover.instrument_id;
              return (
                <button
                  key={mover.instrument_id}
                  onClick={() => router.push(`/instruments/${navId}`)}
                  className="flex w-full items-center gap-2 px-1 py-1 text-left transition-colors hover:bg-muted/30"
                  aria-label={`Navigate to ${mover.ticker}`}
                >
                  <span className="w-[44px] shrink-0 font-mono text-[11px] tabular-nums text-foreground">
                    {mover.ticker}
                  </span>
                  <span className="flex-1 truncate text-[10px] text-muted-foreground">
                    {mover.name || ""}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 font-mono text-[10px] tabular-nums",
                      mover.change_pct >= 0 ? "text-positive" : "text-negative",
                    )}
                  >
                    {mover.change_pct >= 0 ? "+" : ""}
                    {mover.change_pct.toFixed(2)}%
                  </span>
                </button>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * abbreviateSector — compress GICS sector names to 4-7 chars for tile labels.
 *
 * WHY: GICS canonical names like "Information Technology" or "Consumer
 * Discretionary" don't fit in a narrow tile (especially for a flat sector
 * floored to MIN_WEIGHT width). The abbreviations match conventions used
 * across the worldview UI (and lib/sectors.ts pill labels for consistency).
 */
function abbreviateSector(name: string): string {
  // WHY title-case strings (not UPPER): the tile already has a CSS
  // `uppercase` class for visual presentation. Returning title-case keeps
  // the underlying DOM text matchable by tests / a11y tools (e.g.
  // `screen.getByText("Tech")`) while CSS handles the visual uppercase.
  const map: Record<string, string> = {
    "Information Technology": "Tech",
    "Health Care": "Health",
    "Consumer Discretionary": "Discr",
    "Consumer Staples": "Staple",
    "Communication Services": "Comm",
    Financials: "Fins",
    Industrials: "Indus",
    Materials: "Mat",
    "Real Estate": "REIT",
    Utilities: "Util",
    Energy: "Energy",
  };
  return map[name] ?? name.slice(0, 6);
}
