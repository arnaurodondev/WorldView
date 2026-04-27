/**
 * components/instrument/OverviewLayout.tsx — Bloomberg-style Overview tab layout
 *
 * WHY THIS EXISTS: Replaces the old full-width chart + 3-column bottom grid with
 * a Bloomberg-pattern layout: chart shares horizontal space with a right data
 * sidebar (KEY METRICS + sparkline panels). The bottom section becomes 50/50
 * news + entity graph.
 *
 * Layout structure (Wave C-1):
 * ┌──────────────────────────────────────┬──────────────┐
 * │  OHLCVChart + ChartToolbar           │  KEY METRICS │  ← grid-cols-[1fr_280px]
 * │  SessionStatsStrip                   │  TREND 1     │
 * │                                      │  TREND 2     │
 * ├──────────────────────────────────────┴──────────────┤
 * │  InstrumentTopNews (50%)  │  EntityGraph (50%)      │  ← grid-cols-2
 * └───────────────────────────┴─────────────────────────┘
 *
 * WHY 280px fixed sidebar (not percentage): percentages collapse below readability
 * at wide viewport widths and expand beyond useful at narrow widths. 280px is wide
 * enough for 12 metric rows (label + mono value) at 11px font without truncation.
 *
 * WHY right sidebar scrolls independently: metrics + sparklines can be taller than
 * the chart height. Independent scroll lets analysts see more metrics without
 * collapsing the chart — the chart stays fixed as the primary analysis surface.
 *
 * WHY two sparkline panels with metric selectors: a single sparkline is insufficient
 * for ratio analysis. Analysts compare P/E trend vs revenue trend side by side.
 * The selectors let them pick any available metric without navigation.
 *
 * WHY move from 3-column to 50/50 bottom: the entity graph (zone 3) needs more
 * horizontal width for the SVG layout to be legible. News was previously 30%
 * (300px at 1000px viewport) — now 50% gives it full breathing room.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Overview tab content)
 * DATA SOURCE: Props from CompanyOverview + child components fetch their own data
 * DESIGN REFERENCE: PLAN-0041 §T-C-1-01, §T-C-1-03
 */

"use client";
// WHY "use client": uses useState for sparkline metric selectors.
// The parent page.tsx is also "use client" but each component that uses hooks
// must declare its own boundary.

import { useState } from "react";
import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { SessionStatsStrip } from "@/components/instrument/SessionStatsStrip";
import { OverviewSidebarMetrics } from "@/components/instrument/InstrumentKeyMetrics";
import { InstrumentTopNews } from "@/components/instrument/InstrumentTopNews";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import { FundamentalSparkline } from "@/components/instrument/FundamentalSparkline";
import type { OHLCVBar, Fundamentals, Instrument } from "@/types/api";

// ── Constants ─────────────────────────────────────────────────────────────────

// WHY these metrics: the 6 most-asked-about fundamentals trends. Selecting a
// metric updates both sparkline panels independently — analysts can compare any two.
const SPARKLINE_METRICS: { value: string; label: string }[] = [
  { value: "pe_ratio",         label: "P/E Ratio" },
  { value: "revenue",          label: "Revenue" },
  { value: "gross_margin",     label: "Gross Margin" },
  { value: "net_margin",       label: "Net Margin" },
  { value: "roe",              label: "ROE" },
  { value: "debt_to_equity",   label: "D/E Ratio" },
  { value: "earnings_per_share", label: "EPS" },
];

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewLayoutProps {
  instrumentId: string;
  entityId: string;
  centerLabel: string;         // ticker for graph center node label
  initialBars?: OHLCVBar[];    // from CompanyOverview for initial chart render
  fundamentals: Fundamentals | null;
  /** Instrument metadata — passed to sidebar metrics for sector + gics_industry */
  instrument?: Instrument | null;
  /** Current market price — positions the 52W range bar marker in sidebar */
  currentPrice?: number | null;
  onViewAllNews: () => void;   // callback to switch parent to News tab
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OverviewLayout({
  instrumentId,
  entityId,
  centerLabel,
  initialBars,
  fundamentals,
  instrument,
  currentPrice,
  onViewAllNews,
}: OverviewLayoutProps) {
  // ── Sparkline metric selectors ─────────────────────────────────────────────
  // WHY two independent state values: each panel shows a different metric by
  // default (P/E vs Revenue) to give immediate dual-axis context on load.
  const [metric1, setMetric1] = useState("pe_ratio");
  const [metric2, setMetric2] = useState("revenue");

  // Derive SessionStatsStrip props from the last OHLCV bar.
  const lastBar = initialBars?.[initialBars.length - 1] ?? null;

  return (
    <div className="flex flex-col min-h-0">

      {/* ── Upper section: chart + right sidebar ─────────────────────────── */}
      {/* WHY grid-cols-[1fr_280px]: chart takes all remaining width; sidebar is
          fixed at 280px. 1fr > 280px ensures the chart always has a useful width
          (never collapses below sidebar width). */}
      {/* WHY border-b: separates chart row from news+graph bottom row */}
      <div className="grid grid-cols-[1fr_280px] min-h-0 border-b border-border">

        {/* ── Left column: chart + session stats strip ───────────────────── */}
        {/* WHY border-r: hairline separator between chart and sidebar */}
        <div className="flex flex-col min-h-0 border-r border-border">

          {/* Zone 1: Price chart */}
          {/* WHY no padding: OHLCVChart fills its container edge-to-edge.
              ChartToolbar is now inside OHLCVChart, no external wrapper needed. */}
          <OHLCVChart
            instrumentId={instrumentId}
            initialBars={initialBars}
          />

          {/* Zone 2: Session stats strip (full width, 20px) */}
          {/* WHY between chart and lower grid: Bloomberg convention places O/H/L/V
              immediately below the chart canvas, not in a separate section. */}
          <SessionStatsStrip
            open={lastBar?.open ?? null}
            high={lastBar?.high ?? null}
            low={lastBar?.low ?? null}
            volume={lastBar?.volume ?? null}
          />
        </div>

        {/* ── Right column: scrollable sidebar ────────────────────────────── */}
        {/* WHY overflow-y-auto: sidebar content (12 metrics + 2 sparklines) may
            exceed the chart height. Independent scroll preserves the chart view. */}
        <div className="flex flex-col overflow-y-auto">

          {/* Zone 3: Key Metrics panel — 12+ rows */}
          <OverviewSidebarMetrics
            fundamentals={fundamentals}
            instrument={instrument}
            currentPrice={currentPrice}
          />

          {/* Zone 4: Sparkline panel 1 with metric selector */}
          {/* WHY border-t: separates key metrics from sparkline panels */}
          <SparklinePanel
            instrumentId={instrumentId}
            metric={metric1}
            onMetricChange={setMetric1}
            availableMetrics={SPARKLINE_METRICS.filter((m) => m.value !== metric2)}
          />

          {/* Zone 5: Sparkline panel 2 with independent metric selector */}
          {/* WHY second panel: analysts compare two metrics side by side (e.g.,
              P/E trend vs Revenue trend). Two panels avoid navigation overhead. */}
          <SparklinePanel
            instrumentId={instrumentId}
            metric={metric2}
            onMetricChange={setMetric2}
            availableMetrics={SPARKLINE_METRICS.filter((m) => m.value !== metric1)}
          />
        </div>
      </div>

      {/* ── Lower section: news + entity graph (50/50) ───────────────────── */}
      {/* WHY grid-cols-2 (was 3fr:3fr:4fr): news gets 50% (was 30%) and graph
          gets 50% (was 40%). More news width allows 6 headlines without overflow;
          the graph SVG has more canvas for the radial layout. */}
      <div className="grid grid-cols-2 min-h-0">

        {/* Zone 6: Top News */}
        <div className="border-r border-border">
          <InstrumentTopNews
            entityId={entityId}
            onViewAll={onViewAllNews}
          />
        </div>

        {/* Zone 7: Entity Graph */}
        <EntityGraphPanel
          entityId={entityId}
          centerLabel={centerLabel}
        />
      </div>
    </div>
  );
}

// ── SparklinePanel ────────────────────────────────────────────────────────────

/**
 * SparklinePanel — a sidebar section with a metric dropdown + FundamentalSparkline.
 *
 * WHY extracted (not inline in OverviewLayout): keeps OverviewLayout clean and
 * makes the panel testable in isolation. The panel encapsulates the header +
 * select + sparkline unit — a logical composition boundary.
 *
 * WHY native <select> (not shadcn/ui Select): in a 280px sidebar, the native
 * select at 10px font is more compact than any Radix UI dropdown. The native
 * select also renders faster (no portal, no animation).
 */
function SparklinePanel({
  instrumentId,
  metric,
  onMetricChange,
  availableMetrics,
}: {
  instrumentId: string;
  metric: string;
  onMetricChange: (metric: string) => void;
  availableMetrics: { value: string; label: string }[];
}) {
  return (
    // WHY border-t: hairline separator above each sparkline panel
    <div className="border-t border-border">

      {/* Panel header row: "TREND" label + metric selector */}
      <div className="flex items-center justify-between px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          TREND
        </span>

        {/* Metric dropdown
            WHY bg-transparent border-none: blends into the dark panel background.
            The select is identified by its position (right side of label row), not
            a visible box outline — matches Bloomberg's minimal control chrome. */}
        <select
          value={metric}
          onChange={(e) => onMetricChange(e.target.value)}
          className="bg-transparent text-[10px] text-muted-foreground border-none outline-none cursor-pointer hover:text-foreground transition-colors"
        >
          {/* Always include the current metric so it stays selected after sibling changes */}
          {[
            ...availableMetrics,
            // Add current metric if filtered out by the sibling panel's exclusion
            ...(availableMetrics.some((m) => m.value === metric)
              ? []
              : (SPARKLINE_METRICS.filter((m) => m.value === metric))),
          ].map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      {/* Sparkline chart — fetches timeseries data for the selected metric */}
      <div className="px-2 pb-2">
        <FundamentalSparkline
          instrumentId={instrumentId}
          metric={metric}
          height={48}
          showAxis={true}
        />
      </div>
    </div>
  );
}
