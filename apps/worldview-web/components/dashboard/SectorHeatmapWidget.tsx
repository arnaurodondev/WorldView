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
import { useQuery } from "@tanstack/react-query";
import { qk } from "@/lib/query/keys";
import { useRouter } from "next/navigation";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
// Round 3 (item 4): panel-level empty/error states use the shared EmptyState
// primitive (§15.12) with named dashboard.* copy keys.
import { EmptyState } from "@/components/primitives/EmptyState";
// Round 4 (item 1): error state gains a Retry action wired to refetch() —
// Round 3 named the state but left the trader with no recovery path.
import { WidgetErrorState } from "@/components/dashboard/WidgetErrorState";
import { LayoutGrid } from "lucide-react";
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
 * TILE_HEIGHT_PX — fixed tile height. 40px keeps tiles compact while still
 * fitting both label and % change on two lines at 10px/9px font sizes.
 */
const TILE_HEIGHT_PX = 40;

// NOTE (Round 3): the old GAP_PX flex-basis constant was removed — both the
// loaded treemap (FR-1.7) and the loading skeleton now use the same CSS-grid
// container (`gap-0.5` = 2px), so no manual gap subtraction is needed.

/**
 * colorClassFor — map a % change to a Tailwind opacity-step utility class
 * using a PROPORTIONAL scale derived from the current payload's data range.
 *
 * WHY proportional (Round 1 foundation fix, replaces the fixed ±0.5/1/2%
 * thresholds): on a quiet session where every sector moves <0.5%, the fixed
 * scale rendered ALL tiles at the faintest /10 tint — the heatmap conveyed
 * zero relative information. Conversely on a violent day (±4% everywhere)
 * every tile saturated at /40. Normalising each tile's magnitude against the
 * session's MAX |change| guarantees the strongest sector always renders at
 * full intensity and the rest scale relative to it — "intensity ≈ relative
 * magnitude *today*", which is what sector-rotation scanning actually needs.
 *
 * Steps (ratio = |x| / maxAbs of the current payload):
 *   ratio < 0.25 → /10
 *   ratio < 0.50 → /20
 *   ratio < 0.75 → /30
 *   ratio ≥ 0.75 → /40   (saturated tier — the day's leaders)
 *
 * WHY still 4 discrete steps (not a continuous opacity style): Tailwind's JIT
 * scans source for full class names. `bg-positive/${n}` would not be detected
 * at build time and the class would be purged from the final CSS bundle —
 * the explicit string literals below are load-bearing.
 *
 * @param changePct  the sector's % change (null = no data → muted tile)
 * @param maxAbs     max |change_pct| across the CURRENT payload (≤0 treated
 *                   as "no range" → faintest tint, avoids divide-by-zero)
 */
function colorClassFor(changePct: number | null, maxAbs: number): string {
  if (changePct === null) return "bg-muted/30";
  const positive = changePct >= 0;
  // WHY guard maxAbs <= 0: an all-zero payload (every sector flat) has no
  // range to normalise against — everything gets the faintest tint.
  const ratio = maxAbs > 0 ? Math.abs(changePct) / maxAbs : 0;
  if (ratio < 0.25) return positive ? "bg-positive/10" : "bg-negative/10";
  if (ratio < 0.5) return positive ? "bg-positive/20" : "bg-negative/20";
  if (ratio < 0.75) return positive ? "bg-positive/30" : "bg-negative/30";
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
    // Round 4 (item 1): refetch + isFetching drive the error-state Retry
    // button (label flips to "Retrying…" while the re-fetch is in flight).
    refetch: refetchHeatmap,
    isFetching: isHeatmapFetching,
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
  // FIX F-1 (2026-06-05): previously this widget spawned N parallel useQueries
  // — one /v1/companies/{id}/overview per mover. With 50 movers in the
  // popover that's 50 sequential gateway round-trips just to read GICS sector.
  // The batch endpoint runs the legs in parallel server-side; the FE makes
  // exactly one HTTP request and gets back a `{ <uuid>: CompanyOverview | null }`
  // map.
  // WHY staleTime 10min: sectors change rarely; aggressive caching kills
  // re-fetches on every popover open.
  const moverIds = useMemo(
    () => movers.map((m) => m.instrument_id).filter(Boolean),
    [movers],
  );
  const { data: overviewsMap } = useQuery({
    queryKey: qk.instruments.overviewsBatch(moverIds),
    queryFn: () =>
      createGateway(accessToken).getCompanyOverviewsBatch(moverIds),
    enabled: !!accessToken && moverIds.length > 0,
    staleTime: 600_000,
  });
  const overviewByid = useMemo(() => overviewsMap ?? {}, [overviewsMap]);

  // ── Group movers by sector for popover display ──────────────────────────
  // WHY useMemo: the grouping iterates N movers × map look-ups; recomputing
  // on every render (e.g. on each popover open/close) would be wasteful.
  const moversBySector = useMemo(() => {
    const map = new Map<string, Mover[]>();
    movers.forEach((mover) => {
      const overview = overviewByid[mover.instrument_id];
      const sector = overview?.instrument?.gics_sector;
      if (!sector) return;
      const list = map.get(sector) ?? [];
      list.push(mover);
      map.set(sector, list);
    });
    return map;
  }, [movers, overviewByid]);

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

  // ── Data range for the proportional color scale ──────────────────────────
  // Round 1 foundation fix: tile color intensity is normalised against the
  // CURRENT payload's max |change| (see colorClassFor). Computed once per
  // payload here (not per tile) so all tiles share the same reference range.
  // WHY useMemo: a scan over ≤13 sectors is cheap, but recomputing on every
  // popover open/close re-render is pointless churn.
  const maxAbsChange = useMemo(() => {
    const sectors = heatmap?.sectors ?? [];
    return sectors.reduce(
      (acc, s) => Math.max(acc, Math.abs(s.change_pct ?? 0)),
      0,
    );
  }, [heatmap]);

  return (
    // WHY flex flex-col h-full: fills the grid cell so the wrap container can
    // expand to multiple tile rows when many sectors are present.
    // WHY overflow-hidden: any sub-pixel rounding from `flex-basis: calc(...)`
    // on the inner tiles is clipped at the widget border instead of bleeding
    // into adjacent grid cells (B-2-03 fix).
    // Round 4 (item 2): role="region" + aria-label landmark — see
    // MarketSnapshotWidget for the SR-navigation rationale.
    <div
      className="flex h-full flex-col overflow-hidden bg-background"
      role="region"
      aria-label="Sector performance"
    >

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
                // Round 3 (item 5): hover gets a bg (not just text-color) per
                // the bg-muted hover convention, and keyboard focus shows the
                // ring token. text-[9px] is allowed here — period toggles are
                // chrome labels, not financial data values (§15.9).
                className={cn(
                  "px-1.5 font-mono text-[9px] uppercase transition-colors",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  period === p
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
                aria-pressed={period === p}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Loading state — shape-matched grid of grey tiles ─────────────── */}
      {/* Round 3 (item 3): the skeleton now uses the SAME CSS-grid container
          (auto-fit / minmax(48px, 1fr) / gap-0.5) as the loaded treemap — the
          previous flex-wrap + flexBasis approximation wrapped differently at
          some widths, producing a visible re-layout when tiles arrived.
          11 placeholders ≈ the typical GICS sector count (matches 2 rows). */}
      {isHeatmapLoading && (
        <div
          className="grid gap-0.5 content-start px-0.5 py-0"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(48px, 1fr))" }}
        >
          {Array.from({ length: 11 }).map((_, i) => (
            <Skeleton
              key={i}
              className="min-h-[40px]"
              style={{
                height: `${TILE_HEIGHT_PX}px`,
                animationDelay: `${i * 40}ms`,
              }}
            />
          ))}
        </div>
      )}

      {/* ── Error state ──────────────────────────────────────────────────── */}
      {/* WHY separate from "no data": API/network failure ≠ empty result. A
          trader needs to triage these differently — a feed outage requires
          ops attention; an empty list might be expected pre-market.
          Round 3 (item 4): shared EmptyState primitive + named copy key. */}
      {/* Round 4 (item 1): WidgetErrorState adds the Retry → refetch() wiring
          the Round-3 EmptyState lacked. Same copy key + icon, so the named
          state (and any text-matching tests) are unchanged. */}
      {isHeatmapError && (
        <WidgetErrorState
          copyKey="dashboard.sector-error"
          icon={LayoutGrid}
          onRetry={() => void refetchHeatmap()}
          retrying={isHeatmapFetching}
        />
      )}

      {/* ── Empty state ──────────────────────────────────────────────────── */}
      {!isHeatmapLoading && !isHeatmapError && sectorTiles.length === 0 && (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            condition="empty-no-data"
            copyKey="dashboard.no-sector-data"
            icon={LayoutGrid}
          />
        </div>
      )}

      {/* ── Treemap tile container ───────────────────────────────────────── */}
      {!isHeatmapLoading && sectorTiles.length > 0 && (
        // `auto-fit` + `minmax(48px, 1fr)`: at ~344px widget width, this fits
        // ~7 tiles per row → 2 rows for 13 sectors (staying within the 130px
        // Row 2 height budget). Previously 120px forced 2 tiles/row → 7 rows →
        // widget height expanded to 312px, bloating the entire Row 2.
        // WHY gap-0.5 (2px): tight enough for the Bloomberg dense-grid look.
        <div
          className="grid gap-0.5 content-start px-0.5 py-0"
          style={{ gridTemplateColumns: "repeat(auto-fit, minmax(48px, 1fr))" }}
        >
          {sectorTiles.map(({ sector, weight }) => (
            <SectorTile
              key={sector.name}
              sector={sector}
              weight={weight}
              relatedMovers={moversBySector.get(sector.name) ?? []}
              // Round 1: the payload-wide max |change| drives the proportional
              // color scale — every tile normalises against the same range.
              maxAbsChange={maxAbsChange}
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
  maxAbsChange,
}: {
  sector: HeatmapSector;
  weight: number;
  relatedMovers: Mover[];
  /** Max |change_pct| across the whole payload — drives the proportional color scale. */
  maxAbsChange: number;
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

  // ── Hover tooltip (Round 1 foundation) ────────────────────────────────────
  // WHY native title= (not shadcn <Tooltip>): the tile button is already the
  // PopoverTrigger (click drill-down). Nesting a Radix Tooltip trigger inside
  // a Radix Popover trigger on the same node requires ref-merging gymnastics
  // and double asChild composition for marginal visual gain — the native
  // browser tooltip carries the same information with zero extra DOM.
  // WHY top mover may be absent: the heatmap API itself does NOT return a
  // per-sector top mover (backend gap) — we derive it client-side by joining
  // the top-movers list against per-instrument GICS sectors. While those
  // queries resolve (or when no mover in the top-20 belongs to this sector),
  // the tooltip truthfully shows sector + % only.
  const fmtPct =
    changePct === null
      ? "no data"
      : `${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`;
  const tooltip =
    topMovers.length > 0
      ? `${sector.name} ${fmtPct} · Top: ${topMovers[0].ticker}`
      : `${sector.name} ${fmtPct}`;

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
          // Round 1: hover tooltip — sector name, % change, top mover ticker
          // (when the client-side sector join has resolved; see WHY above).
          title={tooltip}
          className={cn(
            // Base layout: vertical stack, centred horizontally, vertically
            // centred on a fixed-height tile.
            "flex min-h-[40px] flex-col items-center justify-center gap-0 px-1",
            // Color encoding: bg-positive/N or bg-negative/N at 4 PROPORTIONAL
            // steps normalised against the payload's max |change| (Round 1).
            colorClassFor(changePct, maxAbsChange),
            // Foreground colour: kept neutral so the *background* tint carries
            // the direction signal — readable on every magnitude step.
            "text-foreground",
            // Border + hover: faint outline to separate adjacent same-colour
            // tiles; brighter ring on hover signals the tile is interactive.
            "rounded-[2px] border border-border/40 transition-colors hover:border-border",
            // Round 3 (item 5): focus → focus-visible so the ring only shows
            // for keyboard navigation (mouse clicks don't leave a lingering
            // ring on the tile that just opened a popover). ring-ring is the
            // canonical --ring token (focus rings match primary by design).
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
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
          <span className="w-full truncate text-center font-mono text-[10px] font-semibold uppercase tabular-nums">
            {abbreviation}
          </span>
          {/* Bottom line — % change. Round 3 (item 1, §15.9): bumped from 9px
              to 10px — a sector % change is a FINANCIAL DATA VALUE and the
              design system sets a hard 10px floor for those (9px is reserved
              for timestamps/counts/category labels). Hierarchy vs the 10px
              semibold label above is preserved via weight, not size. */}
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
              // ADR-F-12: prefer entity_id for navigation; fall back to
              // instrument_id since S9's overview endpoint accepts either.
              const navId = mover.entity_id ?? mover.instrument_id;
              return (
                <button
                  key={mover.instrument_id}
                  onClick={() => router.push(`/instruments/${navId}`)}
                  // Round 3 (item 5): focus-visible ring for keyboard nav
                  // inside the drill-down popover (inset — rows are flush).
                  className="flex w-full items-center gap-2 px-1 py-1 text-left transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring"
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
