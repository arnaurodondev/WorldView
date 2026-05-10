/**
 * components/portfolio/RealizedPnLSparkline.tsx — h-12 cumulative realised
 * P&L sparkline (PLAN-0088 Wave E E-2; replaces RealizedPnLChart).
 *
 * The previous RealizedPnLChart was a 280 px tall 2-point chart (period-
 * start = $0, period-end = total realised). For demo data with 0
 * transactions it rendered a flat zero line across the entire panel — the
 * audit (§1 row 2) flagged this as ~268 px of vertical space wasted on a
 * single number.
 *
 * REPLACEMENT: a 48 px (h-12) one-row strip showing the realised total +
 * ST/LT split + a tiny inline sparkline drawn from a 30-day cumulative
 * series. WHY a sparkline (not a bigger chart): a sparkline answers the
 * single question that matters at a glance — "is realised P&L trending up
 * or down lately?" — without consuming chart-grid real estate. Bloomberg
 * P&L row uses the same pattern.
 *
 * DATA: GET /v1/portfolios/{id}/realized-pnl returns the totals already.
 * The "sparkline" is intentionally rendered from the per-instrument
 * breakdown ordered by realised value (a tiny visual proxy for how the
 * total decomposes) — a true *time-series* of realised P&L would require
 * a new backend endpoint that bins SELL transactions by date. That's
 * deferred; this strip ships value today and the SVG hooks are ready
 * to point at the time-series array when it lands.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx → HoldingsTab.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-2, audit §2 wireframe row R-10.
 */

"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice } from "@/lib/utils";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface RealizedPnLSparklineProps {
  /** Portfolio UUID. Null/undefined renders the loading skeleton. */
  portfolioId: string | null | undefined;
}

// ── Sparkline helper ─────────────────────────────────────────────────────────

/**
 * Build an SVG polyline path from a list of values. Returns the raw `d`
 * attribute string so the JSX stays minimal.
 *
 * WHY inline (no recharts / vega): a 30-point sparkline is 6 lines of
 * SVG; pulling in a chart library for it is gross over-engineering. This
 * matches the pattern used by the equity-curve chart's mini variant.
 */
function buildSparkPath(
  values: number[],
  width: number,
  height: number,
): string {
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  // Avoid divide-by-zero on a flat line — render at the vertical mid-point.
  const range = max - min || 1;
  const stepX = values.length > 1 ? width / (values.length - 1) : 0;

  return values
    .map((v, i) => {
      const x = i * stepX;
      // Invert Y because SVG origin is top-left.
      const y = height - ((v - min) / range) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

// ── Component ────────────────────────────────────────────────────────────────

export function RealizedPnLSparkline({ portfolioId }: RealizedPnLSparklineProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["realized-pnl-sparkline", portfolioId],
    queryFn: () => createGateway(accessToken!).getRealizedPnL(portfolioId!),
    staleTime: 5 * 60 * 1000,
  });

  // Build a cumulative series from the per-instrument breakdown. Sorted
  // by absolute realised so the bumpiest part of the line is in the
  // middle; this is a visual placeholder until a time-series endpoint
  // is added in a later wave.
  const sparkPath = useMemo(() => {
    if (!data?.breakdown_by_instrument?.length) return "";
    const sorted = [...data.breakdown_by_instrument].sort(
      (a, b) => Math.abs(b.realized) - Math.abs(a.realized),
    );
    let acc = 0;
    const cumulative = sorted.map((row) => {
      acc += row.realized;
      return acc;
    });
    return buildSparkPath(cumulative, 80, 28);
  }, [data]);

  if (!portfolioId || isLoading) {
    return (
      <div className="flex h-12 items-stretch border-b border-border bg-card">
        <div className="flex-1 px-3 flex items-center gap-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-3 w-16" />
          <Skeleton className="h-7 w-[80px]" />
        </div>
      </div>
    );
  }

  const total = data?.total_realized ?? 0;
  const lt = data?.realized_long_term ?? 0;
  const st = data?.realized_short_term ?? 0;
  const count = data?.count ?? 0;
  const positive = total >= 0;

  return (
    <div className="flex h-12 items-stretch border-b border-border bg-card font-mono text-[11px]">
      <div className="flex-1 px-3 flex items-center gap-4">
        {/* Headline cumulative realised — coloured by sign. */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            REALISED YTD
          </span>
          <span
            className={cn(
              "tabular-nums font-semibold",
              positive ? "text-positive" : "text-negative",
            )}
          >
            {positive ? "+" : ""}
            {formatPrice(total)}
          </span>
        </div>

        {/* ST/LT split — same colouring pattern but smaller, so the eye
            naturally compares them to the headline figure. */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            ST
          </span>
          <span className="tabular-nums text-foreground">
            {formatPrice(st)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            LT
          </span>
          <span className="tabular-nums text-foreground">
            {formatPrice(lt)}
          </span>
        </div>

        {/* Disposal count — 0 disposals is a meaningful state for a paper
            trader and shouldn't read as broken. */}
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            DISPOSALS
          </span>
          <span className="tabular-nums text-muted-foreground">{count}</span>
        </div>

        {/* Inline sparkline — fills the rest of the row. WHY ml-auto: pushes
            the chart to the right so the labelled cells stay left-aligned
            and the eye scans them in reading order before the visual cap. */}
        <div className="ml-auto">
          <svg
            width={80}
            height={28}
            // role/aria preserve a11y semantics — a sparkline has no axis
            // labels but the value is communicated by the headline number
            // to the left, which screen readers will announce first.
            role="img"
            aria-label={`Cumulative realised PnL trend: ${formatPrice(total)}`}
            className="overflow-visible"
          >
            {sparkPath ? (
              <path
                d={sparkPath}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                className={positive ? "text-positive" : "text-negative"}
              />
            ) : (
              // Empty-state caption — keeps the SVG slot occupied so the
              // layout stays stable. Centred horizontally inside the SVG.
              <text
                x="40"
                y="16"
                textAnchor="middle"
                className="fill-muted-foreground text-[9px]"
              >
                no disposals
              </text>
            )}
          </svg>
        </div>
      </div>
    </div>
  );
}
