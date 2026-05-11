/**
 * components/portfolio/DayPnLDistribution.tsx — h-7 day-Δ$ sparkline
 * (PLAN-0088 Wave E E-4).
 *
 * One row, the last 30 trading days' day-over-day equity-value Δ$ as a
 * horizontal sparkline. Robinhood Gold's "Investing Activity" surface uses
 * the same pattern. Anchored to actual snapshot deltas — NOT to cost
 * basis — so the viz only renders meaningful information once the equity
 * curve fix from F-H-1 lands (after which the snapshot worker writes
 * priced rows, not flat cost-basis rows).
 *
 * DATA: GET /v1/portfolios/{id}/value-history?days=30 — we pair-walk the
 * `points` array client-side to derive day-on-day Δvalue. WHY here (not
 * a new endpoint): the value-history endpoint already exposes daily
 * snapshots; pair-walking 30 numbers in JS is < 1ms. The wave plan
 * mentions extending get_value_history.py to return per-day Δ — but the
 * raw values are already in the response, so the additional field would
 * be redundant. Marking the spec extension as a no-op.
 *
 * WHO USES IT: HoldingsTab top-of-tab strip cluster.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-4, audit §2 wireframe row R-2.
 */

"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

// ── Props ────────────────────────────────────────────────────────────────────

export interface DayPnLDistributionProps {
  /** Portfolio UUID. Null/undefined renders the loading skeleton. */
  portfolioId: string | null | undefined;
}

// ── Component ────────────────────────────────────────────────────────────────

export function DayPnLDistribution({ portfolioId }: DayPnLDistributionProps) {
  const { accessToken } = useAuth();

  // 30 days is a one-month trading window — enough to show variance,
  // short enough that even on weekend snapshots the recent shape is fresh.
  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["portfolio-day-pnl-distribution", portfolioId],
    queryFn: () =>
      createGateway(accessToken!).getValueHistory(portfolioId!, { days: 30 }),
    staleTime: 60_000,
  });

  // Derive day-on-day Δ$ — values[i] - values[i-1]. WHY useMemo: the
  // computation runs every render of the parent (HoldingsTab) which
  // re-renders on every quote tick — memoising avoids re-walking the
  // 30-element array unnecessarily.
  const { deltas, avg, span, mostRecent } = useMemo(() => {
    const points = data?.points ?? [];
    if (points.length < 2) {
      return { deltas: [] as number[], avg: 0, span: 0, mostRecent: 0 };
    }
    const ds = points
      .slice(1)
      .map((p, i) => (p.value ?? 0) - (points[i].value ?? 0));
    const a = ds.reduce((s, d) => s + d, 0) / ds.length;
    const sp = Math.max(...ds) - Math.min(...ds);
    const last = ds[ds.length - 1] ?? 0;
    return { deltas: ds, avg: a, span: sp, mostRecent: last };
  }, [data]);

  if (!portfolioId || isLoading) {
    return (
      <div className="flex h-7 items-stretch border-b border-border bg-card">
        <div className="flex-1 px-3 flex items-center gap-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-3 w-12" />
          <Skeleton className="h-3 w-[200px]" />
        </div>
      </div>
    );
  }

  // Compute path for the sparkline. Tiny — same primitive as the realised
  // sparkline; not worth extracting into a util given two callsites.
  const buildPath = (vals: number[], w: number, h: number): string => {
    if (vals.length === 0) return "";
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const stepX = vals.length > 1 ? w / (vals.length - 1) : 0;
    return vals
      .map((v, i) => {
        const x = i * stepX;
        const y = h - ((v - min) / range) * h;
        return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  };

  const path = buildPath(deltas, 200, 16);
  const positive = mostRecent >= 0;

  return (
    <div className="flex h-7 items-stretch border-b border-border bg-card font-mono text-[11px]">
      <div className="flex-1 px-3 flex items-center gap-3">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          DAY P&amp;L 30D
        </span>
        {/* Sparkline — coloured by the SIGN OF THE LAST POINT, not by avg.
            Rationale: a trader scanning the row wants to know "is the most
            recent day green or red?" which is the closest cue to "what's
            happening right now". */}
        <svg
          width={200}
          height={16}
          role="img"
          aria-label={`Day P&L last 30 days, average ${avg.toFixed(0)}`}
          className="overflow-visible"
        >
          {path ? (
            <path
              d={path}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.25"
              className={positive ? "text-positive" : "text-negative"}
            />
          ) : (
            <text
              x="100"
              y="11"
              textAnchor="middle"
              className="fill-muted-foreground text-[9px]"
            >
              insufficient history
            </text>
          )}
        </svg>
        {/* Average + range — quick numeric summary so the row is informative
            even when the chart isn't being scanned. */}
        <span className="text-[10px] text-muted-foreground tabular-nums">
          avg {avg >= 0 ? "+" : ""}
          {Math.round(avg)}
        </span>
        <span className="text-[10px] text-muted-foreground tabular-nums">
          range {Math.round(span)}
        </span>
      </div>
    </div>
  );
}
