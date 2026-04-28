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
// trying to mix server + client at this granularity.

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
        <div className="col-span-12 lg:col-span-8 min-h-[200px] bg-card border border-border rounded-[2px] p-2">
          <EquityCurveChart portfolioId={portfolioId} />
        </div>

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
