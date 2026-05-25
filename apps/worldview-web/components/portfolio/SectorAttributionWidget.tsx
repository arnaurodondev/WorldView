/**
 * components/portfolio/SectorAttributionWidget.tsx — Live-priced sector breakdown.
 *
 * WHY THIS EXISTS: The exposure endpoint gives a single "invested / cash / leverage"
 * snapshot. Sector attribution decomposes the invested leg by GICS sector and shows
 * per-sector day P&L — answering "which sectors are driving my P&L today?".
 *
 * WHY TWO VIEW MODES (bars / donut): horizontal bars are the default — they give
 * the most information density (sector name + fill proportion + day P&L in one row).
 * The SVG donut gives a quick "shape of portfolio" overview that traders compare
 * against benchmark weights. The `[■]` / `[○]` toggle in the header switches modes
 * without a full re-mount — state lives in the component so the preference is
 * preserved while the page is open but not persisted across sessions (intentional;
 * the bars are the analytical default).
 *
 * WHO USES IT: portfolio overview page Wave B-1 enrichment sidebar.
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/sector-attribution → SectorAttributionResponse.
 * DESIGN REFERENCE: PLAN-0091 Wave B-1 §Sector Attribution widget, Wave F-3 SVG donut.
 */
"use client";
// WHY "use client": useQuery + useState require client-side React context.

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { qk } from "@/lib/query/keys";
import type { SectorBucket } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface SectorAttributionWidgetProps {
  portfolioId: string;
}

// ── Donut colour palette ──────────────────────────────────────────────────────

// WHY 6 colours (not more): more than 6 sectors on a small 80×80px donut
// becomes unreadable — the arcs shrink below the minimum distinguishable width.
// Any sectors beyond 6 are grouped into "Other" (by market_value desc sort).
// Colours: primary blue → teal → purple → orange → red → amber
// WHY sequential (not categorical): adjacent sectors in market_value order are
// often related (e.g. Tech + Comm Services) — sequential hues make clusters
// easier to spot.
const DONUT_PALETTE = [
  "#0EA5E9", // primary blue
  "#26A69A", // teal
  "#8B5CF6", // purple
  "#F97316", // orange
  "#EF4444", // red
  "#FFB000", // amber
] as const;

// ── SVG Donut chart ───────────────────────────────────────────────────────────

interface DonutSlice {
  sector: string;
  pct: number;  // 0-100
  colour: string;
}

/**
 * polarToXY — convert (cx, cy, radius, angleDeg) to SVG (x, y).
 *
 * WHY a local helper (not a library): the donut is 4 arcs in a 80×80 viewport.
 * A full chart lib (recharts / d3) would add 30KB+ for this single usage.
 */
function polarToXY(
  cx: number,
  cy: number,
  r: number,
  angleDeg: number,
): { x: number; y: number } {
  // WHY -90 deg offset: SVG angles start at 3 o'clock; we want 12 o'clock.
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

/**
 * SectorDonut — 80×80 SVG donut chart (Wave F-3 / §Donut mode).
 *
 * WHY pure SVG (not a canvas): SVG is accessible (aria-label on paths),
 * renders pixel-perfect at any DPI (no blurring on Retina), and requires
 * zero dependencies. Canvas would need explicit DPR handling and has no
 * native a11y.
 *
 * WHY cx=40 cy=40 outer=38 inner=28: leaves 2px margin on each side for
 * the stroke antialiasing not to clip. Inner radius 28 creates the donut
 * hole — matching a standard "thick ring" proportion.
 */
function SectorDonut({ slices }: { slices: DonutSlice[] }) {
  const cx = 40;
  const cy = 40;
  const outerR = 38;
  const innerR = 28;
  // WHY small gap: 0.5° gap between arcs prevents colour bleeding at the join
  const gapDeg = 0.5;

  let currentAngle = 0;

  return (
    <svg
      width={80}
      height={80}
      viewBox="0 0 80 80"
      aria-label="Sector allocation donut chart"
      role="img"
    >
      {slices.map((slice) => {
        const totalDeg = (slice.pct / 100) * 360;
        const sweepDeg = Math.max(0, totalDeg - gapDeg);
        const startAngle = currentAngle + gapDeg / 2;
        const endAngle = startAngle + sweepDeg;
        currentAngle += totalDeg;

        if (sweepDeg <= 0) return null;

        const outerStart = polarToXY(cx, cy, outerR, startAngle);
        const outerEnd   = polarToXY(cx, cy, outerR, endAngle);
        const innerStart = polarToXY(cx, cy, innerR, endAngle);
        const innerEnd   = polarToXY(cx, cy, innerR, startAngle);

        // WHY largeArcFlag: SVG arc needs a flag for > 180° sweeps.
        const largeArcFlag = sweepDeg > 180 ? 1 : 0;

        const d = [
          `M ${outerStart.x} ${outerStart.y}`,
          `A ${outerR} ${outerR} 0 ${largeArcFlag} 1 ${outerEnd.x} ${outerEnd.y}`,
          `L ${innerStart.x} ${innerStart.y}`,
          `A ${innerR} ${innerR} 0 ${largeArcFlag} 0 ${innerEnd.x} ${innerEnd.y}`,
          "Z",
        ].join(" ");

        return (
          <path
            key={slice.sector}
            d={d}
            fill={slice.colour}
            opacity={0.85}
            aria-label={`${slice.sector}: ${slice.pct.toFixed(1)}%`}
          />
        );
      })}

      {/* WHY centre label "%" — a plain visual anchor so the user recognises
          this is a "weights" donut, not a P&L pie. */}
      <text
        x={cx}
        y={cy + 4}
        textAnchor="middle"
        fontSize="10"
        fill="#94A3B8" // muted-foreground colour hex equivalent
        fontFamily="monospace"
      >
        wt%
      </text>
    </svg>
  );
}

// ── Bar chart row ─────────────────────────────────────────────────────────────

interface BarRowProps {
  bucket: SectorBucket;
  /** Max market_value in the bucket set — used to scale the fill bar proportionally. */
  maxValue: number;
}

/**
 * BarRow — one 22px sector row in bar mode.
 *
 * WHY proportional fill (not a % of total portfolio): using maxValue as the
 * scale baseline makes the largest sector fill the bar completely, giving
 * maximum visual differentiation between sectors. An absolute weight-based bar
 * would make small sectors nearly invisible.
 *
 * WHY day P&L (not total P&L): the attribution endpoint provides per-sector
 * day P&L which answers the actionable question "is my Energy sector helping
 * or hurting me today?"
 */
function BarRow({ bucket, maxValue }: BarRowProps) {
  const fillPct = maxValue > 0 ? (bucket.market_value / maxValue) * 100 : 0;
  const pnlPositive = bucket.sector_day_pnl >= 0;

  return (
    <div className="relative flex h-[22px] items-center overflow-hidden" data-testid="sector-row">
      {/* Fill bar — absolute positioned behind the text labels */}
      <div
        className="absolute inset-y-0 left-0 bg-[#0EA5E9]/50 rounded-[1px]"
        style={{ width: `${fillPct}%` }}
        aria-hidden="true"
      />

      {/* Sector name — left-anchored on top of the fill bar */}
      <span className="relative z-10 flex-1 truncate px-2 text-[10px] font-mono text-foreground">
        {bucket.sector}
      </span>

      {/* Day P&L — right-anchored, colour-coded */}
      <span
        className={cn(
          "relative z-10 pr-2 text-[10px] font-mono tabular-nums",
          pnlPositive ? "text-[#26A69A]" : "text-[#EF5350]",
        )}
      >
        {pnlPositive ? "+" : ""}
        {bucket.sector_day_pnl.toFixed(0)}
      </span>
    </div>
  );
}

// ── SectorAttributionWidget ───────────────────────────────────────────────────

export function SectorAttributionWidget({ portfolioId }: SectorAttributionWidgetProps) {
  // WHY local boolean (not a URL param): view mode preference is UI-transient.
  // The user's analytical default is bars; the donut is a secondary "overview"
  // view they may switch to momentarily. Persisting this to the URL would
  // pollute the browser history for a cosmetic preference.
  const [showDonut, setShowDonut] = useState(false);

  const { accessToken } = useAuth();

  // WHY qk.portfolios.sectorAttribution: nests under detail(portfolioId)
  // so any portfolio position mutation cascades an invalidation here.
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.sectorAttribution(portfolioId),
    queryFn: () =>
      createGateway(accessToken).getSectorAttribution(portfolioId),
    enabled: !!accessToken && !!portfolioId,
    // WHY refetchIntervalInBackground: false: suppress background-tab polling to
    // avoid S9 load from unfocused browser tabs. Data refetches on focus regain.
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  // Sort buckets by market_value desc — gives consistent ordering across
  // bar and donut modes so the user sees the same sector ranking in both.
  const sorted = [...(data?.buckets ?? [])].sort(
    (a, b) => b.market_value - a.market_value,
  );
  const maxValue = sorted[0]?.market_value ?? 0;

  // ── Donut slice computation ────────────────────────────────────────────────
  // Show at most 6 sectors; group the rest as "Other".
  // WHY: the 6-colour palette + readability constraint (see DONUT_PALETTE comment).
  const totalValue = sorted.reduce((sum, b) => sum + b.market_value, 0);

  const top6 = sorted.slice(0, 6);
  const rest = sorted.slice(6);

  const donutSlices: DonutSlice[] = [
    ...top6.map((b, i) => ({
      sector: b.sector,
      pct: totalValue > 0 ? (b.market_value / totalValue) * 100 : 0,
      colour: DONUT_PALETTE[i],
    })),
    // If there are more than 6 sectors, aggregate the remainder as "Other"
    ...(rest.length > 0
      ? [{
          sector: "Other",
          pct: totalValue > 0
            ? (rest.reduce((s, b) => s + b.market_value, 0) / totalValue) * 100
            : 0,
          colour: "#64748B", // WHY neutral slate: "Other" is a catch-all, not a real sector
        }]
      : []),
  ];

  return (
    <div
      className="flex flex-col gap-0 bg-[#131722] border border-border rounded-[2px]"
      data-testid="sector-attribution-widget"
    >
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="flex h-[22px] items-center justify-between border-b border-border px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          Sector Attribution
        </span>

        <div className="flex items-center gap-1.5">
          {/* WHY prices_stale badge in header: the attribution is live-price-driven.
              When prices are delayed, day P&L figures are based on prior-close data.
              The user must know this before interpreting the colours. */}
          {data?.prices_stale && (
            <span className="text-[9px] font-mono text-[#FFB000]" data-testid="prices-stale-badge">
              prices delayed
            </span>
          )}

          {/* ── Donut / bars toggle button ─────────────────────────────
              WHY [■] for donut-active / [○] for bars-active:
              "■" (filled square) suggests "solid shape" (donut is a shape view).
              "○" (empty circle) suggests "outline" (bars are the structured view).
              These ASCII symbols are zero-dependency and render identically
              across all fonts in the IBM Plex Mono stack. */}
          <button
            onClick={() => setShowDonut((prev) => !prev)}
            className="text-[10px] font-mono text-muted-foreground hover:text-foreground transition-colors"
            aria-label={showDonut ? "Switch to bar chart" : "Switch to donut chart"}
            aria-pressed={showDonut}
            data-testid="donut-toggle"
          >
            {showDonut ? "[■]" : "[○]"}
          </button>
        </div>
      </div>

      {/* ── Loading skeleton ──────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex flex-col gap-px p-1" data-testid="sector-skeleton">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[22px] w-full" />
          ))}
        </div>
      )}

      {/* ── Error state ───────────────────────────────────────────────── */}
      {isError && (
        <div className="px-2 py-1 text-[10px] font-mono text-[#EF5350]">
          Failed to load sector data.
        </div>
      )}

      {/* ── Data state — BAR mode ─────────────────────────────────────── */}
      {!isLoading && !isError && data && !showDonut && (
        <div className="flex flex-col divide-y divide-border">
          {sorted.length === 0 ? (
            <div className="px-2 py-1 text-[10px] font-mono text-muted-foreground">
              No sector data available.
            </div>
          ) : (
            sorted.map((bucket) => (
              <BarRow key={bucket.sector} bucket={bucket} maxValue={maxValue} />
            ))
          )}
        </div>
      )}

      {/* ── Data state — DONUT mode (Wave F-3) ───────────────────────── */}
      {!isLoading && !isError && data && showDonut && (
        <div className="flex flex-col items-center gap-2 py-2" data-testid="donut-view">
          <SectorDonut slices={donutSlices} />

          {/* Legend rows below the donut — sector name + pct */}
          <div className="flex flex-col gap-0.5 w-full px-2">
            {donutSlices.map((s) => (
              <div key={s.sector} className="flex h-[18px] items-center gap-1.5">
                {/* Colour swatch */}
                <div
                  className="h-2 w-2 shrink-0 rounded-[1px]"
                  style={{ backgroundColor: s.colour }}
                  aria-hidden="true"
                />
                <span className="flex-1 truncate text-[9px] font-mono text-muted-foreground">
                  {s.sector}
                </span>
                <span className="text-[9px] font-mono tabular-nums text-foreground">
                  {s.pct.toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
