/**
 * components/instrument/chart/OHLCVChart.tsx — OHLCV candlestick chart (slim orchestrator).
 *
 * WHY: institutional traders read price action first. This component owns React
 * state (timeframe, indicators) and wires `useChartSeries` to the toolbars;
 * intentionally kept under 180 lines per PLAN-0090 T-B-01.
 *
 * MOVED to chart/ subdir (T-B-01). DrawingPalette / DrawingCanvas / CrosshairHUD
 * / VolumeProfileOverlay / Compare overlay all REMOVED per PRD-0088 §5 — deferred
 * for the Quote tab redesign. WHO USES IT: components/instrument/OverviewLayout.tsx.
 * DATA SOURCE: S9 GET /v1/ohlcv/{instrumentId}?timeframe=1D.
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { qk } from "@/lib/query/keys";
// Round-3 item 4: shape-matched skeleton (axis hints) replaces the flat
// <Skeleton> rectangle for the chart's cold first load.
import { ChartSkeleton } from "@/components/instrument/chart/ChartSkeleton";
import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import { TimeframeToolbar } from "@/components/instrument/chart/TimeframeToolbar";
import { useChartSeries } from "@/components/instrument/chart/useChartSeries";
import { CrosshairLegend } from "@/components/instrument/chart/CrosshairLegend";
import {
  CHART_PERIOD_PRESETS,
  DEFAULT_CHART_PERIOD,
  periodStartIso,
  type ChartPeriod,
} from "@/components/instrument/chart/chartPeriods";
import { CHART_HEIGHT } from "@/lib/chart-adapter";
import {
  loadIndicatorsFromStorage,
  saveIndicatorsToStorage,
  type IndicatorId,
  type VolumeProfileBucket,
} from "@/lib/instrument-context";
import type { OHLCVBar } from "@/types/api";

interface OHLCVChartProps {
  instrumentId: string;
  /** Initial bars from CompanyOverview (last 30d 1D — render immediately). */
  initialBars?: OHLCVBar[];
}

export function OHLCVChart({ instrumentId, initialBars }: OHLCVChartProps) {
  const { accessToken } = useAuth();
  // ── Period state (Round-1 requirement 2) ───────────────────────────────────
  // WHY period (not raw timeframe): analysts pick a look-back window
  // (1D/1W/1M/3M/1Y/5Y); the bar resolution + fetch start date are derived
  // from CHART_PERIOD_PRESETS.
  // WAVE-4 (2026-06-12): the default is now DEFAULT_CHART_PERIOD ("1Y" — daily
  // bars), NOT "1D". The old "1D" default fetched 5-minute bars over 3 days and
  // windowed to a single session, which the dev intraday store could only fill
  // with ~10-30 candles (the sparse band the user reported). The 1Y default
  // loads the full ~500-bar daily window and shows the last ~200 bars (see the
  // visibleBars-aware windowing effect below), so the chart opens dense and
  // readable with real history to pan back through.
  const [period, setPeriod] = useState<ChartPeriod>(DEFAULT_CHART_PERIOD);
  const preset = CHART_PERIOD_PRESETS[period];
  // The derived bar resolution. 1M/3M/1Y all derive "1D" — they share one
  // fetch + one cache slot and differ only in the client-side visible range.
  const timeframe = preset.timeframe;
  // WHY default showVolume=true: volume is the industry-standard candlestick companion.
  const [showVolume, setShowVolume] = useState(true);
  const [showMA50, setShowMA50] = useState(false);
  const [showMA200, setShowMA200] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // WHY isFullscreenRef: ResizeObserver inside useChartSeries captures a stale
  // closure; the ref always reflects the live value across renders.
  const isFullscreenRef = useRef(false);
  useEffect(() => { isFullscreenRef.current = isFullscreen; }, [isFullscreen]);

  // Indicator overlays (RSI/MACD/Bollinger). Lazy init reads localStorage so
  // prior selections persist across reloads (PLAN-0050 §H).
  const [indicators, setIndicators] = useState(() => loadIndicatorsFromStorage());
  const [showVolMA20, setShowVolMA20] = useState(false);
  const [showVWAPLine, setShowVWAPLine] = useState(false);
  // WHY default linear scale: institutional default. logScaleRef avoids a
  // stale closure when the chart initialises asynchronously.
  const [logScale, setLogScale] = useState(false);
  const logScaleRef = useRef(logScale);
  logScaleRef.current = logScale;

  // Volume-profile overlay is deferred (PRD-0088 §5). Callback retained so
  // useChartSeries' API contract stays unchanged.
  const [, setVolumeProfileBuckets] = useState<VolumeProfileBucket[]>([]);
  const handleVolumeProfileBuckets = useCallback((b: VolumeProfileBucket[]) => {
    setVolumeProfileBuckets(b);
  }, []);

  const containerRef = useRef<HTMLDivElement>(null);

  // WHY useMemo: a fresh object every render re-fires the data-update effect
  // in useChartSeries — previously caused viewport scroll-to-1985 (BP-376).
  const memoizedPlaceholder = useMemo(() => {
    if (initialBars && timeframe === "1D") {
      return { instrument_id: instrumentId, ticker: "", timeframe: "1D" as const, bars: initialBars };
    }
    return undefined;
  }, [initialBars, timeframe, instrumentId]);

  // Round-4 hardening (item 1b): isError/refetch are consumed below — a
  // failed OHLCV fetch previously fell through every render branch
  // (isLoading=false, data=undefined) and left a blank canvas with live
  // toolbars around it. Now it renders a named per-section error + Retry
  // while the rest of the page (header, metrics rail) keeps working.
  const { data, isLoading, isError, refetch } = useQuery({
    // WHY qk.instruments.ohlcv (Round-1 fix — was a bare ["ohlcv", ...] key):
    // QuoteTab's SessionStatsStrip passively subscribes (enabled:false) to
    // qk.instruments.ohlcv(instrumentId, "1D") to mirror the chart's freshest
    // daily bars. The previous ad-hoc key meant that subscription NEVER saw
    // the chart's data (silent dead data-path) — the strip was stuck on the
    // page-bundle's initial bars forever. Keying through the shared factory
    // reconnects the two components.
    // WHY no `period` element in the key: periods sharing a bar resolution
    // (1M/3M/1Y → "1D") intentionally share one cache slot — switching among
    // them is a pure client-side zoom (see visible-range effect below), so a
    // refetch would be wasted work.
    queryKey: qk.instruments.ohlcv(instrumentId, timeframe),
    // WHY explicit `start`: S9 injects only a 90-day default for daily bars —
    // not enough for the 1Y period. periodStartIso derives the widest window
    // any period sharing this resolution needs (730d daily / 1830d weekly).
    // WHY explicit `limit: 1000` (Wave-4, 2026-06-12): S3 caps the OHLCV result
    // at 200 bars when no limit is given — which is exactly the ~200 the old
    // default showed with NO history left to pan into. A high limit lets the
    // daily window return its full ~500 bars (273 in the current dev dataset)
    // so the chart opens showing ~200 with the rest loaded behind it. 1000 is a
    // safe ceiling: more than any single resolution's window can contain, so it
    // never truncates real data and the same value is correct for every period.
    queryFn: () =>
      createGateway(accessToken).getOHLCV(instrumentId, {
        timeframe,
        start: periodStartIso(period),
        limit: 1000,
      }),
    enabled: !!accessToken && !!instrumentId,
    // WHY 5 min (was 1 min): leaving the Quote tab unmounts the chart; on
    // return the query remounts and refetches anything stale. 5 minutes keeps
    // tab switching instant (requirement 5) while still refreshing the
    // forming candle within a reasonable window.
    staleTime: 5 * 60_000,
    placeholderData: memoizedPlaceholder,
  });

  const { chartRef, isChartReady, chartError } = useChartSeries({
    containerRef, isFullscreen, isFullscreenRef, indicators,
    showVolume, showMA50, showMA200, showVolMA20, showVWAPLine,
    data, instrumentId, timeframe, logScaleRef, logScale,
    onVolumeProfileBuckets: handleVolumeProfileBuckets,
  });

  // ── Visible-range windowing per period (Round-1 requirement 2) ────────────
  // Periods that share a bar resolution (1M/3M/1Y → daily bars) share ONE
  // fetched dataset; the selected period only changes which slice is VISIBLE.
  // WHY a lastApplied ref (BP-376 family): the effect must re-window ONLY when
  // the instrument or period changes — a background refetch (new bars array,
  // same period) must NOT snap the viewport back while the analyst is panning.
  const lastAppliedRangeKey = useRef<string | null>(null);
  useEffect(() => {
    const bars = data?.bars;
    const chart = chartRef.current;
    const rangeKey = `${instrumentId}|${period}`;
    // Guards: chart not initialised yet / no bars / already applied for this
    // instrument+period combination.
    if (!chart || !isChartReady || !bars || bars.length === 0) return;
    if (lastAppliedRangeKey.current === rangeKey) return;

    // ── Bar-count windowing (Wave-4, 2026-06-12) ──────────────────────────────
    // When the preset declares a precise `visibleBars` count (the 1Y default
    // wants the last ~200 of ~500 loaded bars), window by LOGICAL bar index via
    // setVisibleLogicalRange — this is the only API that promises an exact bar
    // COUNT regardless of how many calendar days those bars span (trading days
    // per calendar day vary, so a day-window can't). The logical scale runs
    // 0..barsLength-1; we show the last `visibleBars` indices, clamped so a
    // short series (fewer bars than the budget) just shows everything.
    if (preset.visibleBars != null && bars.length > 0) {
      const barsLength = bars.length;
      const visibleBars = Math.min(preset.visibleBars, barsLength);
      // Half-bar padding on each edge keeps the first/last candle off the axis
      // gutter (lightweight-charts convention) without clipping them.
      const fromIndex = Math.max(0, barsLength - visibleBars) - 0.5;
      const toIndex = barsLength - 0.5;
      chart.timeScale().setVisibleLogicalRange({
        from: fromIndex as never,
        to: toIndex as never,
      });
      lastAppliedRangeKey.current = rangeKey;
      return;
    }

    const firstSec = Math.floor(new Date(bars[0].timestamp).getTime() / 1000);
    const lastSec = Math.floor(new Date(bars[bars.length - 1].timestamp).getTime() / 1000);
    // Window start: lastBar - visibleDays, clamped to the first loaded bar so
    // we never ask lightweight-charts for a range before the data begins.
    const fromSec = Math.max(firstSec, lastSec - preset.visibleDays * 24 * 60 * 60);

    // WHY from < to guard (min==max / single-bar case): setVisibleRange with
    // an empty or inverted interval throws inside lightweight-charts. With a
    // single bar (e.g. a freshly listed instrument) we just scroll to the
    // newest bar instead of windowing.
    if (fromSec >= lastSec) {
      chart.timeScale().scrollToRealTime();
    } else {
      // Cast: lightweight-charts' Time type is a branded number (UTCTimestamp);
      // our epoch-seconds values satisfy it at runtime.
      chart.timeScale().setVisibleRange({
        from: fromSec as never,
        to: lastSec as never,
      });
    }
    lastAppliedRangeKey.current = rangeKey;
  }, [data?.bars, isChartReady, period, instrumentId, preset.visibleDays, preset.visibleBars, chartRef]);

  // ── Crosshair legend (Round-1 requirement 2c) ──────────────────────────────
  // Hovering a candle shows its O/H/L/C + volume in a corner overlay. The
  // legacy CrosshairHUD was deleted in PLAN-0090 T-B-01; this is the
  // minimalist replacement scoped to the redesigned Quote tab.
  const [hoveredBar, setHoveredBar] = useState<OHLCVBar | null>(null);

  // WHY a time→bar Map: lightweight-charts' crosshair event reports the bar's
  // time (the same epoch-seconds we fed via toTime); an O(1) lookup avoids a
  // linear scan on every mousemove (fires at pointer frequency).
  const barsByTime = useMemo(() => {
    const map = new Map<number, OHLCVBar>();
    for (const bar of data?.bars ?? []) {
      map.set(Math.floor(new Date(bar.timestamp).getTime() / 1000), bar);
    }
    return map;
  }, [data?.bars]);
  // WHY a ref mirror: the subscription effect below intentionally re-runs only
  // when the chart instance appears (isChartReady) — reading the map through a
  // ref keeps the handler current without re-subscribing on every data change.
  const barsByTimeRef = useRef(barsByTime);
  useEffect(() => { barsByTimeRef.current = barsByTime; }, [barsByTime]);

  // ── Plottable-bar count (Round-4 hardening, item 1d) ───────────────────────
  // A bar is "plottable" only when all four OHLC legs are finite numbers.
  // WHY this exists: a degraded ingest row can carry null/NaN OHLC (the API
  // type says `number` but the wire doesn't enforce it); lightweight-charts
  // renders such bars as gaps and a single surviving bar as an apparently
  // empty canvas. <2 plottable bars cannot form price action, so we render a
  // named state instead of a blank chart (the candle-level filtering itself
  // lives in useChartSeries so the library never sees a non-finite value).
  const plottableBarCount = useMemo(() => {
    let count = 0;
    for (const b of data?.bars ?? []) {
      if (
        Number.isFinite(b.open) && Number.isFinite(b.high) &&
        Number.isFinite(b.low) && Number.isFinite(b.close)
      ) {
        count += 1;
      }
    }
    return count;
  }, [data?.bars]);

  // ── Canvas a11y summary (Round-4 hardening, item 2) ────────────────────────
  // The lightweight-charts canvas is pure pixels — invisible to screen
  // readers. We expose the latest session's OHLC as an aria-label on the
  // wrapper (role="img": the chart is a single graphic, not a widget tree).
  // WHY latest PLOTTABLE bar (not bars[-1]): a trailing degraded bar with
  // null OHLC would read "NaN" to assistive tech.
  const chartAriaLabel = useMemo(() => {
    const bars = data?.bars ?? [];
    for (let i = bars.length - 1; i >= 0; i--) {
      const b = bars[i];
      if (
        Number.isFinite(b.open) && Number.isFinite(b.high) &&
        Number.isFinite(b.low) && Number.isFinite(b.close)
      ) {
        return (
          `Price chart, ${period} period. Latest bar: ` +
          `open ${b.open.toFixed(2)}, high ${b.high.toFixed(2)}, ` +
          `low ${b.low.toFixed(2)}, close ${b.close.toFixed(2)}.`
        );
      }
    }
    return `Price chart, ${period} period. No price data loaded.`;
  }, [data?.bars, period]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !isChartReady) return;
    // param.time is the hovered bar's time (number for UTC-timestamp series),
    // undefined when the pointer leaves the pane.
    const handler = (param: { time?: unknown }) => {
      const t = typeof param.time === "number" ? param.time : null;
      setHoveredBar(t != null ? (barsByTimeRef.current.get(t) ?? null) : null);
    };
    chart.subscribeCrosshairMove(handler);
    return () => chart.unsubscribeCrosshairMove(handler);
  }, [isChartReady, chartRef]);

  // Indicator toggle handler persists selections to localStorage.
  const handleToggleIndicator = useCallback((id: IndicatorId) => {
    setIndicators((prev) => {
      const next = { ...prev, [id]: { ...prev[id], enabled: !prev[id].enabled } };
      saveIndicatorsToStorage(next);
      return next;
    });
  }, []);

  // Escape exits fullscreen — convention across every chart UI.
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setIsFullscreen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  return (
    // WHY conditional fixed positioning: fullscreen stretches chart to fill
    // the viewport (z-50); exit via toolbar or Escape.
    //
    // WHY `flex h-full flex-col` in the NON-fullscreen branch (Wave-3 black-void
    // fix, 2026-06-11): QuoteTab gives this component a `flex-1 min-h-0` slot,
    // but this root div used to be a plain `className=""` block — height:auto.
    // Per CSS, a child's percentage height resolves to AUTO when the parent's
    // height is auto, so the chart wrapper's `h-full` below collapsed to its
    // content. The content's height was the lightweight-charts canvas itself,
    // which had been initialised from `clientHeight=0 → CHART_HEIGHT (280px)`
    // — a CIRCULAR measurement the ResizeObserver could never escape (the
    // container's size WAS the canvas size, so it kept re-applying 280px).
    // Result at 1440×900: a 280px chart inside a ~600px slot with a giant
    // black void below the time axis. Making the root a full-height flex
    // column restores the chain: slot (definite) → root (h-full) → wrapper
    // (flex-1) → container (h-full) → canvas fills every pixel.
    <div className={isFullscreen ? "fixed inset-0 z-50 bg-background flex flex-col" : "flex h-full flex-col"}>
      <div className="flex items-center h-7 px-2 border-b border-border/30 shrink-0">
        <TimeframeToolbar
          period={period}
          onPeriodChange={setPeriod}
          logScale={logScale}
          onToggleLogScale={() => setLogScale((v) => !v)}
          // Compare overlay deferred (PRD-0088 §5) — required props passed as no-ops.
          showCompareInput={false}
          onToggleCompareInput={() => { /* deferred */ }}
          compareActive={false}
          compareInput=""
          onCompareInputChange={() => { /* deferred */ }}
          onCompareSubmit={() => { /* deferred */ }}
        />
        <div className="ml-auto flex items-center">
          <ChartToolbar
            showVolume={showVolume} onToggleVolume={() => setShowVolume((v) => !v)}
            showMA50={showMA50} onToggleMA50={() => setShowMA50((v) => !v)}
            showMA200={showMA200} onToggleMA200={() => setShowMA200((v) => !v)}
            isFullscreen={isFullscreen} onFullscreen={() => setIsFullscreen((v) => !v)}
            indicators={indicators} onToggleIndicator={handleToggleIndicator}
            showVolMA20={showVolMA20} onToggleVolMA20={() => setShowVolMA20((v) => !v)}
            // Volume-profile overlay deferred per PRD-0088 §5.
            showVolProfile={false} onToggleVolProfile={() => { /* deferred */ }}
            showVWAPLine={showVWAPLine} onToggleVWAPLine={() => setShowVWAPLine((v) => !v)}
          />
        </div>
      </div>

      {chartError && (
        <div className="flex items-center justify-center rounded-[2px] border border-border bg-card" style={{ height: CHART_HEIGHT }}>
          <p className="text-[11px] text-muted-foreground">Chart unavailable</p>
        </div>
      )}

      {/* ── Per-section fetch error (Round-4 hardening, item 1b) ──────────────
          Distinct from `chartError` above (library failed to LOAD): this is
          the OHLCV QUERY failing while the chart library is fine. NAMED state
          with a real Retry — the header/metrics keep working, only the chart
          slot reports. WHY isError && !data: placeholder/cached bars beat an
          error from a background refetch (stale data > error screen). */}
      {!chartError && isError && !data && (
        <div
          data-testid="chart-fetch-error"
          className="flex flex-col items-center justify-center gap-1"
          style={{ height: CHART_HEIGHT }}
        >
          <p className="text-[12px] text-muted-foreground">Couldn&apos;t load price data</p>
          <p className="text-[10px] text-muted-foreground/60">
            The OHLCV request failed — the rest of the page is unaffected.
          </p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-1 h-6 rounded-[2px] border border-border px-2.5 text-[10px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            Retry
          </button>
        </div>
      )}

      {!chartError && !(isError && !data) && (
        // WHY containerRef stays mounted: removing it destroys the WebGL
        // context (visible flash + re-init). No left-gutter padding now that
        // the drawing palette is gone.
        // WHY `flex-1 min-h-0` on the wrapper (Wave-3 black-void fix — was
        // `h-full`): the root div above is now a `flex h-full flex-col` with a
        // fixed 28px toolbar row, so `h-full` here would OVERFLOW the slot by
        // 28px (100% of the root, ignoring the toolbar). `flex-1` claims
        // exactly the remaining height; `min-h-0` lets it shrink below its
        // content size (flex items default to min-height:auto, which would
        // otherwise let the canvas prop the wrapper open and re-create the
        // circular-measurement bug on downsize).
        // Round-4 hardening (item 2): role="img" + aria-label expose the
        // latest OHLC to screen readers — the canvas itself is opaque pixels.
        <div
          className="relative w-full flex-1 min-h-0"
          data-testid="chart-wrapper"
          role="img"
          aria-label={chartAriaLabel}
        >
          {/* WHY h-full works HERE (but didn't on the old wrapper): the wrapper
              is a flex item with a definite flexed height, so the percentage
              resolves against a real number. The ResizeObserver in
              useChartSeries reads this div's clientWidth/clientHeight and
              mirrors them onto the chart canvas — height now tracks the slot. */}
          <div ref={containerRef} className="h-full w-full" />
          {/* Crosshair legend — O/H/L/C/V of the hovered candle (requirement 2c).
              Rendered as an overlay INSIDE the wrapper so it tracks fullscreen.
              CrosshairLegend returns null when nothing is hovered. */}
          <CrosshairLegend bar={hoveredBar} />
          {/* Round-3 item 4: shape-matched skeleton — full-bleed plot surface
              + right price-axis and bottom time-axis hints, so the canvas
              paints in-place with zero shift (ChartSkeleton owns inset-0). */}
          {isLoading && !data && <ChartSkeleton />}
          {/* Empty-state for explicit 0-bar success response (CHART-001).
              WHY period-aware copy: the default 1D period needs intraday (5-min)
              bars which sparse instruments may not have — pointing the analyst
              at the daily-bar periods (1M/3M/1Y) is the actionable next step. */}
          {!isLoading && data && data.bars.length === 0 && (
            <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center justify-center" style={{ height: CHART_HEIGHT }}>
              <p className="text-[12px] text-muted-foreground">No price data for the {period} period</p>
              <p className="mt-1 text-[10px] text-muted-foreground/60">Try a longer period — 1M, 3M or 1Y use daily bars</p>
            </div>
          )}
          {/* Round-4 hardening (item 1d): bars exist but fewer than 2 are
              plottable (finite OHLC) — a single candle or all-null series
              renders as an apparently empty canvas. NAMED state so the
              analyst knows the data, not the chart, is the problem. */}
          {!isLoading && data && data.bars.length > 0 && plottableBarCount < 2 && (
            <div
              data-testid="chart-insufficient-data"
              className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center justify-center"
              style={{ height: CHART_HEIGHT }}
            >
              <p className="text-[12px] text-muted-foreground">Not enough price data to draw a chart</p>
              <p className="mt-1 text-[10px] text-muted-foreground/60">
                {plottableBarCount === 1
                  ? "Only one valid bar in this window — try a longer period"
                  : "The bars in this window have no valid OHLC values"}
              </p>
            </div>
          )}
          {isLoading && data && (
            <span role="status" aria-live="polite" className="pointer-events-none absolute right-2 top-2 rounded-[2px] bg-muted/80 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
              refreshing
            </span>
          )}
        </div>
      )}
    </div>
  );
}
