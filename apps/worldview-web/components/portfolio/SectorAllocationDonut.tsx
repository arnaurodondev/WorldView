/**
 * components/portfolio/SectorAllocationDonut.tsx — sector allocation donut
 * beside the portfolio KPI strip (R2 enhancement sprint).
 *
 * WHY THIS EXISTS: the 22px SectorAllocationBar (inside the Holdings tab)
 * answers "where is my money" only after scrolling into the tab. The donut
 * sits at page level — beside the KPI strip — so the sector mix is visible
 * the moment the page paints, on every tab. It is also INTERACTIVE: clicking
 * a slice (or its legend row) filters the holdings table to that sector;
 * clicking again (or dismissing the filter chip in the Holdings tab) clears.
 *
 * DATA SOURCE: GET /v1/portfolios/{id}/sector-breakdown — the fast S9
 * endpoint (31–86ms, 60s Valkey cache, aa8f95b2). WHY the endpoint (not a
 * client-side derivation from holdings): the server has complete market-data
 * access and returns `covered_pct` so we can flag partial pricing; the
 * client-side path could only price whatever quotes happened to be in the
 * batch response.
 *
 * WHY createGateway + useAuth (not useApiClient): this component mounts at
 * portfolio page level. The page's unit tests mock `@/lib/gateway` but do
 * NOT mount <ApiClientProvider>, so useApiClient would throw on render.
 * createGateway matches the pattern of the other page-level data components
 * (PerformanceChartPanel) and degrades to the error state under old mocks.
 *
 * WHY recharts: whitelisted for portfolio analytics (code-split to
 * /portfolio); already used by AnalyticsTab so there is no new bundle cost.
 *
 * WHY a FIXED-SIZE PieChart (not ResponsiveContainer): the donut is a small
 * fixed ornament (~64px) whose size never depends on viewport; fixed
 * width/height also renders deterministically in jsdom where
 * ResponsiveContainer measures 0×0 and silently draws nothing.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx (beside PortfolioKPIStrip).
 */

"use client";
// WHY "use client": useQuery, recharts (browser SVG), hover state.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { PieChart, Pie, Cell } from "recharts";

import { createGateway } from "@/lib/gateway";
import { formatCompactCurrency } from "@/lib/format";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { SectorBreakdownSegment } from "@/types/api";

// ── Display constants ─────────────────────────────────────────────────────────

/**
 * Max individually-listed sectors. Anything past the 8th is aggregated into
 * one "Other" slice. WHY 8: the legend renders 2 columns × 4 rows inside the
 * ~68px panel height; more rows would overflow the KPI-strip-height panel.
 */
const MAX_SEGMENTS = 8;

/**
 * Donut palette — Terminal Dark chart tokens via hsl(var(--…)).
 *
 * WHY a primary→blue→muted RAMP (not a rainbow): consistent with
 * SectorAllocationBar's opacity-ramp approach, and deliberately AVOIDS
 * --chart-positive / --chart-negative — green/red are reserved for P&L
 * direction in this app; a "red" sector slice would falsely read as a
 * losing sector. WHY hsl(var(--token) / alpha): Tailwind-3 CSS vars hold
 * space-separated HSL triples, so this is the canonical composition form
 * (same rationale as the R1 sparkline fix).
 */
const DONUT_COLORS = [
  "hsl(var(--primary))",
  "hsl(var(--primary) / 0.75)",
  "hsl(var(--primary) / 0.55)",
  "hsl(var(--primary) / 0.38)",
  "hsl(var(--chart-ma-slow))",
  "hsl(var(--chart-ma-slow) / 0.65)",
  "hsl(var(--chart-ma-slow) / 0.4)",
  "hsl(var(--muted-foreground) / 0.55)",
];

/** Aggregated tail slice color — intentionally the dimmest in the ramp. */
const OTHER_COLOR = "hsl(var(--muted-foreground) / 0.25)";

/** Label for the aggregated tail. Distinct from the backend's "Unknown". */
const OTHER_LABEL = "Other";

// ── Formatting helpers ────────────────────────────────────────────────────────

/**
 * fmtCompactUsd — "$1.23M" / "$58.3K" / "$842" compact money.
 * WHY compact (not formatPrice): the donut center hole is ~36px wide; a
 * full "$1,234,567.89" cannot fit. Compact magnitude is the terminal
 * convention for at-a-glance summary values.
 * Delegates to the shared formatter (architecture gate: no hand-built
 * currency strings — formatting lives in lib/format.ts only).
 * compactThreshold 1_000: compact from $1K up so 5-figure portfolios fit
 * the hole; maxDecimals 1 keeps "$100.0K" inside the ring at every step.
 */
function fmtCompactUsd(v: number): string {
  return formatCompactCurrency(v, "USD", { compactThreshold: 1_000, maxDecimals: 1 });
}

/** Weight as "42.1%" — segment.weight is a 0-1 fraction from S9. */
function fmtWeight(w: number): string {
  return `${(w * 100).toFixed(1)}%`;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface SectorAllocationDonutProps {
  /** Active portfolio UUID; null disables the query and renders the shell. */
  portfolioId: string | null;
  /** Currently active sector filter (page-level state, null = no filter). */
  selectedSector: string | null;
  /**
   * Toggle callback — called with the sector name to filter by, or null to
   * clear (clicking the already-selected sector clears, per the R2 spec).
   */
  onSelectSector: (sector: string | null) => void;
  /** Extra classes from the page layout (width / border / visibility). */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SectorAllocationDonut({
  portfolioId,
  selectedSector,
  onSelectSector,
  className,
}: SectorAllocationDonutProps) {
  const { accessToken } = useAuth();

  // Hovered sector (visual emphasis only — filtering is click-driven so a
  // stray mouse-over can't yank rows out of the table mid-read).
  const [hovered, setHovered] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.sectorBreakdown(portfolioId ?? ""),
    queryFn: () => createGateway(accessToken!).getSectorBreakdown(portfolioId!),
    enabled: Boolean(portfolioId && accessToken),
    // 60s matches the endpoint's Valkey TTL — refetching faster always hits
    // the server cache, so there's nothing to gain from a shorter window.
    staleTime: 60_000,
    retry: false,
  });

  // ── Build display segments: top-8 individually + aggregated "Other" ──────
  // Segments arrive sorted largest-first from S9, so a simple slice works.
  const rawSegments: SectorBreakdownSegment[] = data?.segments ?? [];
  const top = rawSegments.slice(0, MAX_SEGMENTS);
  const tail = rawSegments.slice(MAX_SEGMENTS);
  const segments =
    tail.length > 0
      ? [
          ...top,
          // Aggregate the tail — NOT clickable as a filter (it spans several
          // real sectors; filtering by "Other" would be ambiguous).
          {
            sector: OTHER_LABEL,
            weight: tail.reduce((s, t) => s + t.weight, 0),
            count: tail.reduce((s, t) => s + t.count, 0),
            market_value: tail.reduce((s, t) => s + t.market_value, 0),
          },
        ]
      : top;

  const totalValue = rawSegments.reduce((s, seg) => s + seg.market_value, 0);

  /** Toggle handler shared by slices and legend rows. */
  const handleSelect = (sector: string) => {
    if (sector === OTHER_LABEL) return; // aggregate slice is not filterable
    onSelectSector(sector === selectedSector ? null : sector);
  };

  /**
   * Slice/row opacity: when a sector is selected (or hovered) everything
   * else dims so the highlighted slice pops — standard donut affordance.
   */
  const emphasisFor = (sector: string): number => {
    const focus = hovered ?? selectedSector;
    if (focus == null) return 1;
    return sector === focus ? 1 : 0.35;
  };

  return (
    <div
      data-testid="sector-allocation-donut"
      // WHY bg-card: same chrome tone as the KPI strip it sits beside.
      className={cn(
        "flex items-center gap-2 bg-card px-2 py-1 overflow-hidden",
        className,
      )}
      aria-label="Sector allocation"
    >
      {isLoading ? (
        // Skeleton mirrors the populated layout (circle + legend block) so
        // there is zero layout shift when data lands.
        <>
          <Skeleton className="size-[56px] rounded-full shrink-0" />
          <div className="flex-1 space-y-1">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        </>
      ) : isError || segments.length === 0 ? (
        // Named state — NEVER fake an allocation. Error and genuinely-empty
        // portfolios share copy because the user action is the same (none).
        <div className="flex flex-1 items-center justify-center">
          <span
            data-testid="donut-empty-state"
            className="font-mono text-[10px] uppercase tracking-[0.06em] text-muted-foreground"
          >
            {isError ? "Sector data unavailable" : "No sector data yet"}
          </span>
        </div>
      ) : (
        <>
          {/* ── Donut (fixed 64px) with centered total ──────────────────── */}
          <div className="relative shrink-0" data-testid="donut-chart">
            <PieChart width={64} height={64}>
              <Pie
                data={segments}
                dataKey="market_value"
                nameKey="sector"
                cx="50%"
                cy="50%"
                // 21/30 ⇒ a 9px ring with a 42px hole — the hole must fit
                // the compact total label below.
                innerRadius={21}
                outerRadius={30}
                // WHY no animation: the donut redraws on every quote-cache
                // update; a 400ms sweep animation on each redraw is noise.
                isAnimationActive={false}
                strokeWidth={0}
                onClick={(_, idx) => handleSelect(segments[idx].sector)}
                onMouseEnter={(_, idx) => setHovered(segments[idx].sector)}
                onMouseLeave={() => setHovered(null)}
              >
                {segments.map((seg, i) => (
                  <Cell
                    key={seg.sector}
                    fill={
                      seg.sector === OTHER_LABEL
                        ? OTHER_COLOR
                        : DONUT_COLORS[i % DONUT_COLORS.length]
                    }
                    fillOpacity={emphasisFor(seg.sector)}
                    // Pointer cursor signals slices are clickable.
                    cursor={seg.sector === OTHER_LABEL ? "default" : "pointer"}
                  />
                ))}
              </Pie>
            </PieChart>
            {/* Center label — total market value of all priced holdings.
                Absolutely positioned over the SVG hole because recharts has
                no first-class "center label" primitive worth its weight. */}
            <span
              data-testid="donut-total"
              title={`Total allocated value: $${totalValue.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
              className="pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[9px] tabular-nums text-foreground"
            >
              {fmtCompactUsd(totalValue)}
            </span>
          </div>

          {/* ── Legend: 2-col grid — sector / weight% / value per row ───── */}
          <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-2 gap-y-0">
            {segments.map((seg, i) => {
              const isSelected = seg.sector === selectedSector;
              const isOther = seg.sector === OTHER_LABEL;
              return (
                <button
                  key={seg.sector}
                  type="button"
                  data-testid={`donut-legend-${seg.sector}`}
                  // Aggregate row is informational only (see handleSelect).
                  disabled={isOther}
                  onClick={() => handleSelect(seg.sector)}
                  onMouseEnter={() => setHovered(seg.sector)}
                  onMouseLeave={() => setHovered(null)}
                  // aria-pressed exposes toggle semantics to AT + tests.
                  aria-pressed={isSelected}
                  title={
                    isOther
                      ? `${seg.count} positions across ${tail.length} more sectors`
                      : `${seg.sector}: ${fmtWeight(seg.weight)} · $${seg.market_value.toLocaleString("en-US", { maximumFractionDigits: 0 })} · ${seg.count} position${seg.count === 1 ? "" : "s"}. Click to ${isSelected ? "clear the" : "filter holdings by this"} sector.`
                  }
                  className={cn(
                    "flex h-[15px] min-w-0 items-center gap-1 rounded-[2px] px-0.5 text-left",
                    !isOther && "hover:bg-muted/40",
                    isSelected && "bg-primary/10",
                  )}
                  style={{ opacity: emphasisFor(seg.sector) }}
                >
                  {/* Swatch matches the slice color exactly. */}
                  <span
                    aria-hidden
                    className="size-1.5 shrink-0 rounded-[1px]"
                    style={{
                      backgroundColor: isOther
                        ? OTHER_COLOR
                        : DONUT_COLORS[i % DONUT_COLORS.length],
                    }}
                  />
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate text-[9px] leading-none",
                      isSelected ? "text-primary" : "text-muted-foreground",
                    )}
                  >
                    {isOther ? `+${tail.length} more` : seg.sector}
                  </span>
                  {/* ADR-F-15: all numerics font-mono tabular-nums. */}
                  <span className="shrink-0 font-mono text-[9px] leading-none tabular-nums text-foreground">
                    {fmtWeight(seg.weight)}
                  </span>
                  <span className="shrink-0 font-mono text-[9px] leading-none tabular-nums text-muted-foreground">
                    {fmtCompactUsd(seg.market_value)}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Partial-pricing caveat — same "~" convention as PerformanceStrip. */}
          {data && data.covered_pct < 0.99 && (
            <span
              data-testid="donut-coverage-hint"
              title={`Only ${Math.round(data.covered_pct * 100)}% of holdings had price data when this breakdown was computed — weights are approximate.`}
              className="shrink-0 self-start font-mono text-[9px] text-muted-foreground"
            >
              ~{Math.round(data.covered_pct * 100)}%
            </span>
          )}
        </>
      )}
    </div>
  );
}
