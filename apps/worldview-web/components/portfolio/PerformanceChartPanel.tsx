/**
 * PerformanceChartPanel — 120px collapsible equity-curve strip with SPY overlay.
 *
 * WHY THIS EXISTS: Portfolio managers need quick trend context without navigating
 * to the full PortfolioAnalyticsSection. 120px is compact enough to stay above
 * the fold while giving meaningful shape. SPY overlay (design spec DISCUSS-10:
 * locked to SPY-only for v1) provides immediate alpha/beta intuition.
 *
 * WHY lightweight-charts (not Recharts): lightweight-charts renders to Canvas so
 * it handles 365 daily points at 60fps without any DOM node overhead. Recharts
 * SVG at that density becomes sluggish on low-end hardware. The EquityCurveChart
 * (used in PortfolioAnalyticsSection) also uses lightweight-charts — same library,
 * no new bundle cost.
 *
 * COLLAPSE TOGGLE: pressing the header button shrinks to h-[28px]. The collapsed
 * state shows only the header row (period selector + label). This mirrors the
 * Finviz "table-only" toggle described in the design spec.
 *
 * DATA: fetches from GET /v1/portfolios/{id}/value-history (portfolio NAV series).
 *   - staleTime: 5 minutes (equity-curve refreshes daily at 21:30 UTC).
 *   - 404 / error: collapses itself and shows "Performance data not available yet."
 *
 * SPY OVERLAY: both series are normalised to 100 at the first shared date so the
 * chart shows *relative return* — the gap between the lines is alpha. DISCUSS-10
 * locked the benchmark to SPY-only for v1.
 *
 * WHO USES IT: portfolio overview page, between ConcentrationSectorTeaseStrip and SectorAllocationBar.
 * DESIGN REFERENCE: PRD-0089 §4.1 (layout strip), §6.1 (pixel spec), §7.1 hotkey "0"
 */
"use client";
// WHY "use client": useRef for the chart DOM container, useState for
// collapsed/period, useEffect to mount/destroy the chart, useQuery for data.

import { useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";

// ── Period configuration (shared with EquityCurveChart) ─────────────────────
export type PerfPeriod = "1W" | "1M" | "3M" | "6M" | "1Y" | "All";
const PERIODS: PerfPeriod[] = ["1W", "1M", "3M", "6M", "1Y", "All"];

// Days to subtract from today for each period label.
// "All" uses null to signal "send no from param — server returns full history".
const PERIOD_DAYS: Record<PerfPeriod, number | null> = {
  "1W": 7,
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "1Y": 365,
  "All": null,
};

// ── Chart colour tokens ───────────────────────────────────────────────────────
// WHY constants (not CSS vars): lightweight-charts uses JS colour strings, not
// CSS classes. We pull from the Midnight Pro palette used in the design system.
const CHART_PORTFOLIO_LINE = "#FFD60A";  // text-primary gold — portfolio line
const CHART_SPY_LINE = "#52525B";        // zinc-600 — SPY benchmark (muted, not competing)
const CHART_BG = "#09090B";             // bg-background
const CHART_GRID = "#1C1C1E";           // border-border at low opacity
const CHART_TEXT = "#71717A";           // text-muted-foreground

// Ticker used for the benchmark overlay (DISCUSS-10: locked to SPY for v1).
const BENCHMARK_TICKER = "SPY";

// ── Props ─────────────────────────────────────────────────────────────────────

interface PerformanceChartPanelProps {
  /** Portfolio UUID for data fetching. When null, the panel shows "—". */
  portfolioId: string | null;
  period: PerfPeriod;
  onPeriodChange: (p: PerfPeriod) => void;
  /** When true, panel is collapsed to 28px header-only. */
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

// ── Value-history point shape (mirrors S1 response) ──────────────────────────
interface ValueHistoryPoint {
  date: string;      // "YYYY-MM-DD"
  value: number;     // portfolio NAV
  cost_basis: number;
  cash: number;
}

export function PerformanceChartPanel({
  portfolioId,
  period,
  onPeriodChange,
  collapsed = false,
  onToggleCollapse,
}: PerformanceChartPanelProps) {
  const { accessToken } = useAuth();

  // Ref for the DOM div that lightweight-charts attaches to.
  // WHY useRef + useEffect (not controlled state): lightweight-charts mutates
  // the DOM directly; mounting it inside React state would trigger re-renders
  // on every price tick. Refs sidestep React's reconciler for imperative DOM.
  const containerRef = useRef<HTMLDivElement>(null);

  // We store the chart API in a ref so the cleanup useEffect can call chart.remove().
  // WHY not useState: updating a ref never triggers a re-render; we only need the
  // reference to destroy the chart on unmount.
  const chartRef = useRef<import("lightweight-charts").IChartApi | null>(null);

  // ── Data fetch: portfolio value-history ────────────────────────────────────
  // staleTime 5 min — equity-curve data is stable between daily snapshots.
  const days = PERIOD_DAYS[period];
  // Compute `from` once so both portfolio and SPY fetches use the same window.
  const fromDate =
    days != null
      ? (() => {
          const d = new Date();
          d.setDate(d.getDate() - days);
          return d.toISOString().slice(0, 10);
        })()
      : undefined;

  const { data: historyData, isError } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: qk.portfolios.valueHistory(portfolioId ?? "", period),
    queryFn: () =>
      createGateway(accessToken!).getValueHistory(portfolioId!, { from: fromDate }),
    staleTime: 5 * 60 * 1000,
    // WHY retry: false — a 404 means "no snapshots yet". Retrying wastes quota;
    // the error state shows a friendly "not available" message instead.
    retry: false,
  });

  // ── Data fetch: resolve SPY instrument_id once ─────────────────────────────
  // WHY resolveTickersBatch (not a hardcoded UUID): the instrument_id for SPY
  // is environment-specific (dev seed uses a deterministic UUID, prod differs).
  // Resolving at runtime means the same code works in all environments.
  // staleTime=24h — SPY's instrument_id never changes in a session.
  const { data: spyIdMap } = useQuery({
    enabled: Boolean(accessToken),
    queryKey: ["benchmark-resolve", BENCHMARK_TICKER],
    queryFn: () => createGateway(accessToken!).resolveTickersBatch([BENCHMARK_TICKER]),
    staleTime: 24 * 60 * 60 * 1000,
    retry: false,
  });
  const spyInstrumentId = spyIdMap?.[BENCHMARK_TICKER] ?? null;

  // ── Data fetch: SPY daily OHLCV for overlay ────────────────────────────────
  // We use daily close prices and normalise to 100 at the first portfolio date.
  // staleTime 5 min — same window as portfolio history.
  const { data: spyOhlcv } = useQuery({
    enabled: Boolean(accessToken && spyInstrumentId),
    queryKey: ["perf-panel-spy", spyInstrumentId, period],
    queryFn: () =>
      createGateway(accessToken!).getOHLCV(spyInstrumentId!, {
        timeframe: "1D",
        ...(fromDate ? { start: fromDate } : {}),
      }),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  // ── Chart mount / data update ──────────────────────────────────────────────
  // WHY single useEffect (not two): the chart must exist before we set data,
  // and we destroy it on unmount. Separating mount+data would require careful
  // ordering with chart existence checks everywhere. One effect keeps the logic
  // linear: create → set data → cleanup.
  const mountChart = useCallback(async () => {
    if (collapsed || !containerRef.current || !historyData?.points?.length) return;

    // Lazy-import lightweight-charts to avoid SSR errors (Canvas is browser-only).
    // WHY dynamic import: Next.js 15 tree-shakes dynamic imports correctly;
    // a top-level import would force the module into the server bundle.
    const { createChart, ColorType, LineSeries } = await import("lightweight-charts");

    // Destroy any existing chart before creating a new one.
    // WHY: React may re-run this effect when period changes or data arrives —
    // calling createChart on an already-occupied container creates a second chart
    // on top of the first, causing double-rendering and a memory leak.
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const container = containerRef.current;
    if (!container) return;

    // WHY explicit width/height: lightweight-charts defaults to 300×300 if the
    // container has no explicit size. Setting autoSize:true lets it read the
    // CSS-driven width. Height is fixed to match the 92px chart area (120px
    // panel − 28px header).
    const chart = createChart(container, {
      autoSize: true,
      height: container.clientHeight || 92,
      layout: {
        background: { type: ColorType.Solid, color: CHART_BG },
        textColor: CHART_TEXT,
        fontSize: 9,
        fontFamily: "ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: CHART_GRID },
        horzLines: { color: CHART_GRID },
      },
      // WHY no border: the outer <div> already has border-b; an inner chart
      // border would create a double-border artifact.
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderVisible: false,
        tickMarkFormatter: (time: number) => {
          // Render month abbreviation only for compact strip (not full date).
          const d = new Date(time * 1000);
          return d.toLocaleDateString("en-US", { month: "short" });
        },
      },
      crosshair: { mode: 1 }, // Normal crosshair
      handleScroll: false,    // WHY false: the table below the chart should scroll, not the chart
      handleScale: false,
    });

    chartRef.current = chart;

    // ── Build normalised portfolio series (base-100 return) ───────────────
    // WHY normalise to 100: portfolio NAV ($) and SPY price ($) have very
    // different magnitudes. Normalising both to 100 at the period's first
    // shared point lets the lines share one price scale and shows pure
    // relative-return divergence — i.e. alpha — directly as the gap.
    const rawPortfolio = historyData.points
      .filter((p: ValueHistoryPoint) => p.value != null)
      .map((p: ValueHistoryPoint) => ({
        time: (Date.parse(p.date) / 1000) as import("lightweight-charts").UTCTimestamp,
        value: p.value,
      }))
      .sort((a: { time: number }, b: { time: number }) => a.time - b.time);

    const firstPortfolioValue = rawPortfolio[0]?.value ?? 1;
    const portfolioData = rawPortfolio.map((pt) => ({
      time: pt.time,
      value: (pt.value / firstPortfolioValue) * 100,
    }));

    const portfolioSeries = chart.addSeries(LineSeries, {
      color: CHART_PORTFOLIO_LINE,
      lineWidth: 1,
      lastValueVisible: false,
      priceLineVisible: false,
    });

    if (portfolioData.length > 0) {
      portfolioSeries.setData(portfolioData);
    }

    // ── SPY overlay series ────────────────────────────────────────────────
    // Normalise SPY closes to 100 at the same start so both curves are
    // directly comparable. Only render when we have SPY bars.
    const spyBars = spyOhlcv?.bars ?? [];
    if (spyBars.length > 0) {
      const rawSpy = spyBars
        .map((bar) => ({
          time: (Date.parse(bar.timestamp) / 1000) as import("lightweight-charts").UTCTimestamp,
          value: bar.close,
        }))
        .sort((a: { time: number }, b: { time: number }) => a.time - b.time);

      const firstSpyClose = rawSpy[0]?.value ?? 1;
      const spyData = rawSpy.map((pt) => ({
        time: pt.time,
        value: (pt.value / firstSpyClose) * 100,
      }));

      const spySeries = chart.addSeries(LineSeries, {
        color: CHART_SPY_LINE,
        lineWidth: 1,
        lineStyle: 1, // WHY dashed: visually separates SPY (benchmark) from portfolio
        lastValueVisible: false,
        priceLineVisible: false,
      });
      spySeries.setData(spyData);
    }

    // Fit all data in view (no panning needed for a 120px strip).
    chart.timeScale().fitContent();
  // WHY period excluded: historyData and spyOhlcv already key on period via
  // their useQuery queryKeys — when period changes, those queries re-fetch and
  // the new data triggers mountChart. Including period would cause a double
  // render (once for period change, once for data arrival).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collapsed, historyData, spyOhlcv]);

  useEffect(() => {
    void mountChart();

    // Cleanup: destroy the chart when the component unmounts or deps change.
    return () => {
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [mountChart]);

  // ── Panel height ───────────────────────────────────────────────────────────
  // WHY collapsed → h-[22px] (not h-[28px]): PRD-0108 §6.1 specifies 22px for
  // the collapsed strip height. 22px is tight enough that the panel looks like
  // a thin divider bar, preserving vertical space for the holdings table below.
  // The header row is therefore also constrained to 22px when collapsed — font
  // size 10px renders comfortably within that.
  // WHY expanded → h-[120px]: 120px gives enough vertical range for trend shape
  // without dominating the viewport. Chart area = 120 − 22 = 98px.
  const panelHeight = collapsed ? "h-[22px]" : "h-[120px]";

  // ── Error / no-data state ──────────────────────────────────────────────────
  // When the endpoint 404s or has no data, show a short inline message instead
  // of a blank canvas. Design spec §7.5: collapse the panel and show the message.
  const showUnavailable = isError || (historyData && historyData.points?.length === 0);

  return (
    <div
      className={cn(
        "flex flex-col shrink-0 border-b border-border bg-card",
        panelHeight,
      )}
    >
      {/* ── Header row: label + collapse toggle + period selector ─────── */}
      <div className="flex h-[28px] shrink-0 items-center px-3 gap-2">
        {/* Collapse toggle — also the strip label per design §6.1 */}
        <button
          type="button"
          onClick={onToggleCollapse}
          className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground hover:text-foreground flex items-center gap-1"
          aria-label={collapsed ? "Expand performance chart" : "Collapse performance chart"}
        >
          <span>Performance</span>
          {/* WHY ▶/▼ glyph: single char, no import needed, terminal-native.
              ▶ = collapsed (click to expand), ▼ = expanded (click to collapse). */}
          <span aria-hidden>{collapsed ? "▶" : "▼"}</span>
        </button>

        {/* "vs SPY" label — benchmark annotation. Locked to SPY per DISCUSS-10. */}
        <span className="ml-1 text-[10px] text-muted-foreground">vs SPY</span>

        {/* Period buttons — right-aligned, same style as EquityCurveChart */}
        <div className="ml-auto flex items-center gap-0">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onPeriodChange(p)}
              className={cn(
                "h-5 px-1.5 text-[10px] font-mono",
                period === p
                  ? "border-b-2 border-primary text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* ── Chart area — only rendered when not collapsed ────────────────── */}
      {!collapsed && (
        <div className="flex-1 min-h-0 relative">
          {showUnavailable ? (
            // Design spec §7.5: show inline muted message on error/no-data.
            // WHY items-center justify-center: vertically centres the text in
            // the chart area so it doesn't hug the top.
            <div className="flex h-full items-center justify-center px-3">
              <span className="text-[11px] font-mono text-muted-foreground">
                Performance data not available yet.
              </span>
            </div>
          ) : (
            // The chart div is the lightweight-charts mount target.
            // WHY w-full h-full: autoSize:true reads these CSS-computed dimensions.
            // WHY absolute inset-0: ensures the container fills the flex-1 parent
            // without relying on block-width inheritance which can be 0 in flex.
            <div
              ref={containerRef}
              className="absolute inset-0 w-full h-full"
              aria-label="Portfolio performance chart"
            >
              {/* "Value ($)" y-axis label — PRD-0108 §6.1 spec.
                  WHY absolute top-0.5 left-1: lightweight-charts owns the canvas
                  and cannot render HTML labels. We overlay a positioned <span>
                  at the top-left corner where the y-axis price scale lives, so
                  the user can read the axis dimension without it overlapping the
                  chart content. z-10 lifts it above the canvas element.
                  WHY 9px / text-muted-foreground: matches the chart's own
                  fontSize:9 setting and uses the same muted colour token so the
                  label reads as metadata, not data. */}
              <span
                className="absolute top-0.5 left-1 z-10 text-[9px] text-muted-foreground pointer-events-none select-none"
                aria-hidden
              >
                Value ($)
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
