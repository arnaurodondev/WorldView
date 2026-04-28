/**
 * components/portfolio/PortfolioAnalyticsSection.tsx — Wave-5 analytics composer
 *
 * WHY THIS EXISTS: Wave 5 introduces three new portfolio analytics surfaces
 * (equity curve, exposure, risk metrics). Composing them in one component
 * keeps the parent ``portfolio/page.tsx`` from accumulating yet another
 * triplet of useState/useQuery declarations — the analytics section has
 * its own self-contained data flow because each child fetches independently.
 *
 * LAYOUT (12-column grid, per PLAN-0046 spec):
 *   ┌──────────────────────────────────────────┬──────────────┐
 *   │ Equity Curve (col-span-8)                │ Exposure     │
 *   │                                          │ (col-span-4) │
 *   ├──────────────────────────────────────────┴──────────────┤
 *   │ Risk Metrics Strip (col-span-12)                         │
 *   └─────────────────────────────────────────────────────────┘
 *
 * WHY 8/4 SPLIT (not 6/6 or 9/3): equity-curve charts need horizontal
 * real estate to read trends; exposure is a single bar + headline that
 * fits comfortably in a third of the row. 8/4 (≈67/33) is the same
 * split the dashboard PortfolioSummary uses for chart-vs-summary.
 *
 * MOUNT POINT: parent renders this BELOW SemanticHoldingsTable in the
 * Holdings tab — the user lands on the holdings table (concrete positions),
 * then scrolls into the analytics section for "how am I doing across the
 * book?" context.
 */

"use client";
// WHY "use client": the children all use TanStack Query; React's strict-mode
// boundary handling means client components compose more safely than
// trying to mix server + client at this granularity. Also, the wrapper
// reads cached query state to size the equity-curve panel — that requires
// browser-side query client access.

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineEmptyState } from "@/components/data/InlineEmptyState";
import { useAuth } from "@/hooks/useAuth";
import { createGateway } from "@/lib/gateway";
import { EquityCurveChart } from "./EquityCurveChart";
import { ExposureBreakdown } from "./ExposureBreakdown";
import { RiskMetricsStrip } from "./RiskMetricsStrip";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface PortfolioAnalyticsSectionProps {
  /** Active portfolio UUID (or ROOT id for the aggregate view). */
  portfolioId: string;
}

// ── PortfolioAnalyticsSection ─────────────────────────────────────────────────

export function PortfolioAnalyticsSection({
  portfolioId,
}: PortfolioAnalyticsSectionProps) {
  // WHY duplicate the EquityCurveChart query here: we need to know whether
  // there are any snapshot points BEFORE rendering the outer panel wrapper.
  // The query is keyed on (portfolioId, "3M") — same default the chart uses.
  // TanStack Query deduplicates by key, so this does NOT cause a second
  // network request: both calls share one in-flight promise + one cache entry.
  // staleTime 60_000 — 1 minute matches the chart's setting; daily snapshots
  // do not change intra-day, so a longer stale window would just delay the
  // first fetch when the user navigates back.
  const { accessToken } = useAuth();
  const { data: equityData, isLoading: equityLoading } = useQuery({
    queryKey: ["value-history", portfolioId, "3M"],
    queryFn: () =>
      createGateway(accessToken).getValueHistory(portfolioId, {
        days: 90,
        granularity: "1d",
      }),
    enabled: !!accessToken && !!portfolioId,
    staleTime: 60_000,
  });

  // Treat all-zero series the same as empty — see EquityCurveChart F-210.
  const equityPoints = equityData?.points ?? [];
  const equityIsEmpty =
    !equityLoading &&
    (equityPoints.length === 0 ||
      equityPoints.every((p) => Number(p.value) === 0));

  return (
    // WHY mt-3 + space-y-3: terminal density — 12px gap above the section
    // (separating it from the holdings table) and 12px between the chart
    // row and the risk strip.
    // WHY mt-2 space-y-2 (was mt-3 space-y-3): tighter terminal density —
    // 8px gaps everywhere (table → analytics, analytics-row → risk-strip)
    // make the page read as one coherent dense surface rather than a stack
    // of separate cards each demanding their own breathing room.
    <section
      aria-label="Portfolio analytics"
      className="mt-2 space-y-2"
    >
      {/* ── Top row: equity curve (8) + exposure (4) ─────────────────── */}
      {/* WHY grid-cols-12 + col-span-{8,4}: matches PLAN-0046 spec exactly.
          On narrow screens (< sm), Tailwind's grid still respects the 12-col
          layout but the gap is small enough to look reasonable; the breakpoint
          where this would feel cramped (< 600px) is rare on a finance terminal.
          WHY gap-2 (was gap-3): see space-y rationale above — 8px is the
          standard inter-panel gap across the rest of the app. */}
      <div className="grid grid-cols-12 gap-2">
        {/* Equity curve — fixed minimum height so the chart doesn't
            collapse into a sliver before its data resolves.
            WHY min-h-[200px] (was 220px): the chart's intrinsic content
            (header + ResponsiveContainer at min-h-[180px]) only needs ~200px;
            the extra 20px was reserved space producing a "tall black panel"
            effect on the dark page background (bg-card panel on bg-card page
            looked like one giant black box). 200px keeps the chart legible
            without inflating the panel.
            WHY p-2 (was p-3): one notch tighter padding pulls the chart
            content closer to the panel edges — same effect Bloomberg PORT
            uses, where chart content runs nearly edge-to-edge. */}
        {/* WHY conditional wrapper: when the user has no equity history yet,
            an unconditional `min-h-[200px] bg-card` panel rendered as a large
            black rectangle on the dark page background ("big black panel"
            bug, F-P-001). Splitting into three states keeps the chart's
            footprint proportional to its content:
              - loading → skeleton at full height
              - empty   → small bordered card with InlineEmptyState
              - data    → original 200px bg-card chart wrapper */}
        {equityLoading ? (
          <div className="col-span-12 lg:col-span-8">
            <Skeleton className="h-[200px] w-full rounded-[2px]" />
          </div>
        ) : equityIsEmpty ? (
          <div className="col-span-12 lg:col-span-8 flex h-auto items-center justify-center rounded-[2px] border border-border/40 py-6">
            <InlineEmptyState message="No equity history yet — snapshots accumulate over trading days." />
          </div>
        ) : (
          <div className="col-span-12 lg:col-span-8 min-h-[200px] bg-card border border-border rounded-[2px] p-2">
            <EquityCurveChart portfolioId={portfolioId} />
          </div>
        )}

        {/* Exposure breakdown — compact panel with the same min-height as
            the chart so the row's vertical alignment stays clean. */}
        <div className="col-span-12 lg:col-span-4 min-h-[200px] bg-card border border-border rounded-[2px] p-2">
          <ExposureBreakdown portfolioId={portfolioId} />
        </div>
      </div>

      {/* ── Bottom row: risk metrics strip, full width ────────────────── */}
      {/* WHY no border wrapper: the strip itself draws the border (it's
          already a self-contained card). Wrapping it again would double up. */}
      <RiskMetricsStrip portfolioId={portfolioId} />
    </section>
  );
}
