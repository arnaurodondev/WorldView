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
 * PLAN-0059-G Wave G-2: OHLCVChart + EntityGraphPanel are lazy-loaded via
 * next/dynamic to reduce the initial JS bundle on the instrument detail page.
 * Both components use browser-only APIs (lightweight-charts needs a DOM node;
 * EntityGraphPanel reads SVG getBoundingClientRect), so ssr:false is required.
 */

"use client";
// WHY "use client": uses useState for sparkline metric selectors.
// The parent page.tsx is also "use client" but each component that uses hooks
// must declare its own boundary.

import { useState } from "react";
import dynamic from "next/dynamic";
// WHY dynamic import for OHLCVChart: lightweight-charts initialises a WebGL/Canvas
// context inside a useEffect — it MUST run in the browser. Lazy-loading saves
// ~100KB from the initial instrument-page bundle so above-the-fold metrics render
// faster. The Skeleton fills the chart area while the bundle downloads.
import { Skeleton } from "@/components/ui/skeleton";
import { SessionStatsStrip } from "@/components/instrument/SessionStatsStrip";
import { OverviewSidebarMetrics } from "@/components/instrument/InstrumentKeyMetrics";
import { InstrumentTopNews } from "@/components/instrument/InstrumentTopNews";
import { FundamentalSparkline } from "@/components/instrument/FundamentalSparkline";
import { InstrumentAskAiButton } from "@/components/instrument/InstrumentAskAiButton";
// 2026-05-09 Overview redesign:
//   PerformanceBar       — multi-timeframe % chips above the chart (TradingView pattern)
//   OverviewInsiderStrip — 5-row insider transactions panel sibling to TopNews
import { PerformanceBar } from "@/components/instrument/PerformanceBar";
import { OverviewInsiderStrip } from "@/components/instrument/OverviewInsiderStrip";
// PLAN-0088 Wave F-3: SplitsDividendsPanel completes the 12-zone Overview
// wireframe (zone 12). Placed at the bottom of the right rail so income-
// stock context (yield, payout, ex-date, last split) is visible without the
// user needing to switch to the Fundamentals tab.
import { SplitsDividendsPanel } from "@/components/instrument/SplitsDividendsPanel";
// WHY shadcn Select (T-B-2-03): finance mandate prohibits native <select> elements.
// The native select has system-default styling that breaks the terminal dark theme and
// produces OS-chrome dropdowns (white background on macOS). shadcn Select uses a Radix
// UI popover with consistent dark theme styling across all platforms.
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { OHLCVBar, Fundamentals, Instrument } from "@/types/api";

// ── Lazy-loaded heavy components ──────────────────────────────────────────────

/**
 * OHLCVChart — lazy-loaded candlestick chart (lightweight-charts ~100KB).
 *
 * WHY ssr:false: lightweight-charts calls document.createElement() on import.
 * Server-side rendering has no document object — importing synchronously would
 * crash the SSR pass. next/dynamic with ssr:false skips SSR and hydrates the
 * chart client-side only.
 *
 * WHY the chart-height Skeleton: OHLCVChart renders at a fixed 360px height
 * (set by the chart container). The Skeleton reserves that space so the page
 * layout does not shift when the bundle loads — prevents CLS (Cumulative Layout
 * Shift), which would push the session-stats strip and news row downward.
 */
const OHLCVChart = dynamic(
  () => import("@/components/instrument/OHLCVChart").then((m) => ({ default: m.OHLCVChart })),
  {
    ssr: false, // lightweight-charts requires browser DOM — SSR would crash
    loading: () => (
      // WHY h-[360px]: matches the default chart container height so the page
      // layout is stable while the ~100KB bundle downloads + initialises.
      <Skeleton className="h-[360px] w-full rounded-none" />
    ),
  },
);

/**
 * EntityGraphPanel — lazy-loaded SVG entity relationship graph.
 *
 * WHY ssr:false: EntityGraphPanel calls svgRef.current.getBoundingClientRect()
 * for tooltip positioning — a browser layout API unavailable during SSR.
 * Lazy-loading also shaves the SVG + tooltip state code from the initial bundle.
 *
 * WHY h-full Skeleton (2026-05-09 Overview redesign): the new layout sizes
 * the panel via the parent grid cell (min-h-[400px] on the row), so the
 * loader fills its container instead of a hard-coded height. Matches the
 * EntityGraphPanel responsive update.
 */
const EntityGraphPanel = dynamic(
  () => import("@/components/instrument/EntityGraphPanel").then((m) => ({ default: m.EntityGraphPanel })),
  {
    ssr: false, // getBoundingClientRect() is browser-only
    loading: () => (
      // WHY flex h-full items-center justify-center: the loading placeholder fills
      // the entire 400px container (set by the parent div) and centres the Skeleton
      // within it. Using h-full (not h-[400px]) makes the loader responsive to the
      // parent container height — if the container height changes in future, the
      // loader adapts without a separate constant to update.
      // WHY Skeleton h-full w-full: gives a subtle shimmer that signals "content
      // loading" rather than a blank or solid-black rectangle (the previous state
      // before Cytoscape.js initialised). Consistent with how OHLCVChart and other
      // async panels signal loading state in this layout.
      <div className="flex h-full items-center justify-center">
        <Skeleton className="h-full w-full" />
      </div>
    ),
  },
);

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
  /**
   * PLAN-0071 Phase 4: When the AnalystRail is docked open on the instrument page,
   * the floating InstrumentAskAiButton should be hidden to avoid redundancy.
   * The rail already provides the same functionality, docked and context-aware.
   */
  hideAskAiButton?: boolean;
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
  hideAskAiButton = false,
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

      {/* ── Performance bar (2026-05-09 Overview redesign) ───────────────── */}
      {/* WHY ABOVE the chart row (not in the right sidebar): TradingView and
          Finviz both place the multi-timeframe % strip directly under the
          symbol header so analysts get an instant "is this hot/cold across
          horizons?" read before they engage with the chart. Placing it in the
          sidebar would compete with the metrics rail for attention. */}
      <PerformanceBar instrumentId={instrumentId} />

      {/* ── Upper section: chart + right sidebar ─────────────────────────── */}
      {/* WHY flex (was grid grid-cols-[1fr_280px]): flex lets the chart column
          grow to fill remaining space (flex-1) while the sidebar stays at a
          fixed w-[280px] flex-shrink-0. This makes the sidebar truly independent
          of the chart — resizing the chart no longer affects sidebar width.
          Grid's 1fr column tracks the grid container width, which can cause the
          sidebar to shift slightly when scrollbars appear; flex avoids that. */}
      {/* WHY border-b: separates chart row from news+graph bottom row */}
      <div className="flex min-h-0 border-b border-border">

        {/* ── Left column: chart + session stats strip ───────────────────── */}
        {/* WHY flex-1: chart column absorbs all horizontal space the sidebar
            does not claim. min-h-0 prevents the flex child from overflowing
            the parent height in column-direction flex contexts. */}
        {/* WHY border-r: hairline separator between chart and sidebar */}
        <div className="flex flex-col flex-1 min-h-0 border-r border-border">

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
        {/* WHY w-[280px] flex-shrink-0: sidebar must stay exactly 280px regardless
            of chart width. flex-shrink-0 prevents the flex algorithm from squeezing
            it when the container is narrow — the chart (flex-1) absorbs all compression.
            WHY overflow-y-auto: sidebar content (12 metrics + 2 sparklines) may
            exceed the chart height. Independent scroll preserves the chart view.
            T-F-6-16 (sidebar scroll unification): this single overflow-y-auto on the
            column wrapper IS the unified scroll block. Neither OverviewSidebarMetrics
            nor SparklinePanel define their own overflow classes — both render as
            normal flow content that the parent scroll container scrolls as one unit. */}
        <div className="w-[280px] flex-shrink-0 flex flex-col overflow-y-auto">

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

          {/* Zone 12 (PLAN-0088 Wave F-3): Splits & Dividends panel.
              WHY at the bottom of the right rail: yield/payout/ex-date are
              "context numbers" — useful but secondary to the live metrics
              and trend sparklines above. Income screeners hit this panel
              first; growth analysts skip past it. The right rail's
              overflow-y-auto handles scroll if total content exceeds the
              chart-row height (typical: 12 metrics × 22px + 2 sparklines
              + this panel ≈ 460-540px). */}
          <SplitsDividendsPanel
            instrumentId={instrumentId}
            dividendYield={fundamentals?.dividend_yield ?? null}
          />
        </div>
      </div>

      {/* ── Lower section: news + insider (left col) | entity graph (right col) ─ */}
      {/* 2026-05-09 Overview redesign:
          Old layout: 50/50 news + graph (graph wrapped in `h-[400px] bg-card/20`
          while EntityGraphPanel SVG was only 280px tall → 120px black void below
          the SVG; "black empty component" reported by the user).
          New layout: 3 columns at 33% each — News, Insider, Graph. The graph
          panel now fills its column (no fixed-height wrapper that doesn't match
          the SVG). News empty (often 0 articles) is no longer half the screen;
          insider transactions backfill the density.
          WHY min-h-[400px]: matches the EntityGraphPanel internal target so the
          row never collapses. Without this, the row collapses to 22px before
          content paints. */}
      <div className="grid grid-cols-3 min-h-[400px]">

        {/* Zone 6: Top News (1/3 col) */}
        <div className="border-r border-border min-w-0">
          <InstrumentTopNews
            entityId={entityId}
            onViewAll={onViewAllNews}
          />
        </div>

        {/* Zone 7: Insider Activity (1/3 col)
            WHY between news and graph: insider data is rich seeded data that
            balances a sparse news column. Placing it adjacent to news lets
            analysts scan both "what's the market hearing" and "what are
            executives doing" side-by-side — the standard Bloomberg analyst
            workflow. */}
        <div className="border-r border-border min-w-0">
          <OverviewInsiderStrip instrumentId={instrumentId} />
        </div>

        {/* Zone 8: Entity Graph (1/3 col)
            WHY no h-[400px] wrapper anymore: the previous wrapper was 400px
            tall but the SVG inside was only 280px → 120px of black space at
            the bottom (the "black empty component" complaint). The
            EntityGraphPanel now renders responsively — see EntityGraphPanel.tsx
            for the responsive SVG fix. */}
        <div className="min-w-0">
          <EntityGraphPanel
            entityId={entityId}
            centerLabel={centerLabel}
          />
        </div>
      </div>

      {/* PLAN-0071 Phase 4: hide the floating button when the AnalystRail is docked open.
          The rail is the preferred surface — docked, persistent, context-aware.
          WHY still render when hideAskAiButton=false: on mobile or when the rail is
          closed, the floating button remains the entry point. */}
      {!hideAskAiButton && (
        <InstrumentAskAiButton
          ticker={centerLabel}
          currentPrice={currentPrice}
          recentBars={initialBars}
          fundamentals={fundamentals}
        />
      )}
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
 * WHY shadcn Select (T-B-2-03): Finance mandate prohibits native <select> elements.
 * shadcn Select renders a Radix UI combobox with consistent dark-theme styling —
 * no OS-chrome white background dropdowns on macOS.
 *
 * WHY dynamic label (T-B-2-03): The header was hardcoded "TREND" which gave no
 * context about which metric was selected. Now the label mirrors the selected metric
 * (e.g. "P/E RATIO") so the panel is self-describing without opening the dropdown.
 *
 * WHY height={68} (T-B-2-05): was 48px — too short for meaningful trendlines on
 * quarterly data. 68px gives the sparkline enough vertical range to distinguish
 * compression vs expansion without dominating the sidebar.
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
  // Build the full metric list (current metric + available — no duplicates)
  // WHY include current metric even if filtered out by sibling: the sibling panel
  // filters out the same metric to prevent duplicate selection. The current panel
  // always needs its active metric in the list so the Select shows its value.
  const fullMetricList = [
    ...availableMetrics,
    ...(availableMetrics.some((m) => m.value === metric)
      ? []
      : SPARKLINE_METRICS.filter((m) => m.value === metric)),
  ];

  // Derive the human-readable label for the currently selected metric.
  // WHY dynamic label: header mirrors active metric so the panel is self-describing
  // without opening the dropdown — analysts glance at the label, not the trigger.
  const currentLabel =
    SPARKLINE_METRICS.find((m) => m.value === metric)?.label.toUpperCase() ?? "TREND";

  return (
    // WHY border-t: hairline separator above each sparkline panel
    <div className="border-t border-border">

      {/* Panel header row: dynamic metric label + shadcn Select */}
      <div className="flex items-center justify-between px-2 h-6">
        {/* WHY dynamic label (T-B-2-03): was hardcoded "TREND" — now mirrors the
            selected metric name so the panel is self-describing at a glance. */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          {currentLabel}
        </span>

        {/* Metric selector — shadcn Select (T-B-2-03)
            WHY h-6 text-[11px]: matches the panel row height; compact trigger
            that blends into the 280px sidebar without extra chrome. */}
        <Select value={metric} onValueChange={onMetricChange}>
          <SelectTrigger
            className="h-6 text-[11px] w-auto min-w-[80px] border-none bg-transparent px-1 focus:ring-0"
            aria-label="Select trend metric"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {fullMetricList.map((m) => (
              <SelectItem
                key={m.value}
                value={m.value}
                className="text-[11px]"
              >
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Sparkline chart — fetches timeseries data for the selected metric */}
      {/* WHY height={68} (T-B-2-05): was 48px — too short for meaningful trendlines
          on quarterly fundamental data. 68px gives enough vertical range to show
          compression vs expansion without dominating the 280px sidebar. */}
      <div className="px-2 pb-2">
        <FundamentalSparkline
          instrumentId={instrumentId}
          metric={metric}
          height={68}
          showAxis={true}
        />
      </div>
    </div>
  );
}
