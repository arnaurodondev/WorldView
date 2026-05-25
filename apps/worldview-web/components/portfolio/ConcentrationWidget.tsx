/**
 * components/portfolio/ConcentrationWidget.tsx — HHI concentration gauge with segment bar.
 *
 * WHY THIS EXISTS: ConcentrationSectorTeaseStrip is a 22px horizontal strip for
 * the page header band — it shows HHI inline with sector data but has very little
 * vertical space. This widget is a standalone, taller panel that gives HHI more
 * breathing room: a large HHI number, a colour-coded label, a 30-segment bar
 * that makes the raw number visually scannable, and the top-3 share percentage.
 *
 * DECISION — 30 segments: each segment represents 333 HHI points (10,000 / 30).
 * At HHI = 1,500 (EU diversified threshold) → 4–5 segments lit.
 * At HHI = 2,500 (EU concentrated threshold) → 7–8 segments lit.
 * At HHI = 10,000 (single position) → all 30 lit.
 * This mapping lets the user read the label AND see the severity at a glance.
 *
 * WHO USES IT: portfolio overview page Wave B-1 enrichment sidebar.
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/concentration → ConcentrationResponse.
 * DESIGN REFERENCE: PLAN-0091 Wave B-1 §Concentration widget.
 */
"use client";
// WHY "use client": useQuery and React.useState require client-side React context.

import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { qk } from "@/lib/query/keys";
import type { ConcentrationResponse } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ConcentrationWidgetProps {
  portfolioId: string;
}

// ── Label colour mapping ──────────────────────────────────────────────────────

/**
 * labelClass — maps ConcentrationResponse.label to Tailwind colour class.
 *
 * WHY these colours:
 *  "diversified" → muted text (HHI < 1500, no action needed)
 *  "moderate"    → amber warning (HHI 1500-2500, worth monitoring)
 *  "concentrated"→ red alert (HHI > 2500, position-sizing risk)
 *  "empty"       → muted (no holdings; any colour would be misleading)
 *
 * Thresholds follow EU competition law HHI brackets, widely adopted in portfolio
 * analytics (FactSet PORT-CONC, Bloomberg PORT use the same convention).
 */
function labelClass(label: ConcentrationResponse["label"]): string {
  switch (label) {
    case "diversified": return "text-muted-foreground";
    case "moderate":    return "text-[#FFB000]";
    case "concentrated":return "text-[#EF5350]";
    case "empty":       return "text-muted-foreground";
    default:            return "text-muted-foreground";
  }
}

// ── Segment bar helper ────────────────────────────────────────────────────────

/**
 * SegmentBar — 30 horizontal segments representing HHI magnitude.
 *
 * WHY 30 segments (not a CSS gradient bar): segments give the user discrete
 * "notches" that are easier to read at a glance than a smooth gradient.
 * At standard 22px row height, each segment is ~3px wide with a 1px gap.
 *
 * N = Math.round((hhi / 10_000) * 30) filled segments — proportional to the
 * full HHI scale so 0 fills nothing and 10,000 fills all 30.
 */
function SegmentBar({ hhi }: { hhi: number }) {
  // Clamp N to [0, 30] so an out-of-range API value doesn't overflow the bar.
  const n = Math.min(30, Math.max(0, Math.round((hhi / 10_000) * 30)));

  return (
    <div className="flex items-center gap-px" aria-label={`HHI segment bar: ${n} of 30 segments filled`}>
      {Array.from({ length: 30 }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-[4px] flex-1 rounded-[1px]",
            i < n
              ? "bg-[#0EA5E9]/50"    // WHY /50 opacity: filled segment is coloured but subtle
              : "bg-muted/20",       // WHY /20 opacity: empty segment is barely visible
          )}
        />
      ))}
    </div>
  );
}

// ── ConcentrationWidget ───────────────────────────────────────────────────────

export function ConcentrationWidget({ portfolioId }: ConcentrationWidgetProps) {
  const { accessToken } = useAuth();

  // WHY qk.portfolios.concentration(portfolioId): nests under detail(portfolioId)
  // so any portfolio position mutation (add/sell) cascades a cache invalidation
  // here automatically — no per-mutation invalidation call needed.
  const { data, isLoading, isError } = useQuery({
    queryKey: qk.portfolios.concentration(portfolioId),
    queryFn: () => createGateway(accessToken).getConcentration(portfolioId),
    enabled: !!accessToken && !!portfolioId,
    // WHY 30s staleTime + refetchInterval: concentration is a live-price-derived
    // metric during market hours. 30s balances freshness vs request volume.
    // WHY refetchIntervalInBackground: false: suppress background-tab polling to avoid
    // S9 load from unfocused tabs. Data refetches on focus regain (TanStack default).
    staleTime: 30_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  return (
    <div
      className="flex flex-col gap-1.5 bg-[#131722] border border-border rounded-[2px] p-2"
      data-testid="concentration-widget"
    >
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-mono">
          Concentration
        </span>
        {/* WHY show prices_stale badge in header: same pattern as exposure/sector
            widgets — the user needs to know immediately if the HHI is computed
            on cost basis rather than live prices (less accurate). */}
        {data?.prices_stale && (
          <span className="text-[9px] font-mono text-[#FFB000]">prices delayed</span>
        )}
      </div>

      {/* ── Loading skeleton ──────────────────────────────────────────── */}
      {isLoading && (
        <div className="flex flex-col gap-1.5" data-testid="concentration-skeleton">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-[4px] w-full" />
          <Skeleton className="h-3 w-32" />
        </div>
      )}

      {/* ── Error state ───────────────────────────────────────────────── */}
      {isError && (
        <div className="text-[10px] font-mono text-[#EF5350]">
          Failed to load concentration data.
        </div>
      )}

      {/* ── Data state ────────────────────────────────────────────────── */}
      {!isLoading && !isError && data && (
        <>
          {/* HHI number + label on one row */}
          <div className="flex items-baseline gap-1.5">
            <span
              className="text-[12px] font-mono tabular-nums text-foreground"
              data-testid="hhi-value"
            >
              {/* WHY toFixed(0): HHI is a percent² metric — decimal places
                  add false precision. Ints read more naturally (e.g. "2,340"). */}
              {data.hhi.toFixed(0)}
            </span>
            <span
              className={cn("text-[9px] font-mono uppercase", labelClass(data.label))}
              data-testid="hhi-label"
            >
              {data.label}
            </span>
          </div>

          {/* 30-segment horizontal magnitude bar */}
          <SegmentBar hhi={data.hhi} />

          {/* Top-3 share percentage below the bar */}
          <div className="flex items-center gap-1 text-[10px] font-mono tabular-nums text-muted-foreground">
            <span>Top 3:</span>
            <span
              className="text-foreground"
              data-testid="top3-share"
            >
              {/* WHY toFixed(1): top_3_share_pct is already a 0-100 percent value
                  (not a 0-1 fraction) per the API contract in lib/api/portfolios.ts.
                  One decimal place is sufficient precision for a share percent. */}
              {data.top_3_share_pct.toFixed(1)}%
            </span>
          </div>
        </>
      )}
    </div>
  );
}
