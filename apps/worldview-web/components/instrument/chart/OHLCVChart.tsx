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
 *
 * PLAN-0091 F-1 (TA overlay extension):
 *   TAOverlayPanel is rendered INSIDE OHLCVChart (below the toolbar row) rather
 *   than in QuoteTab because it needs both `timeframe` and `data.bars`, which are
 *   internal state/data here. Lifting them to QuoteTab would bloat the orchestrator
 *   with chart-only concerns. OHLCVChart manages `overlayLines` state and passes it
 *   down to useChartSeries as the `overlays` option.
 *
 *   The `overlays` prop on OHLCVChartProps is kept for external callers (e.g. tests
 *   or non-QuoteTab embed points) that want to inject overlays without TAOverlayPanel.
 *   When both `overlays` prop and internal TAOverlayPanel are active, the prop wins
 *   (external caller takes precedence over the chip strip).
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import { TimeframeToolbar } from "@/components/instrument/chart/TimeframeToolbar";
import { TAOverlayPanel } from "@/components/instrument/quote/TAOverlayPanel";
import { useChartSeries } from "@/components/instrument/chart/useChartSeries";
import { CHART_HEIGHT, type ChartType, type RangePreset, type Timeframe } from "@/lib/chart-adapter";
import {
  loadIndicatorsFromStorage,
  saveIndicatorsToStorage,
  type IndicatorId,
  type VolumeProfileBucket,
} from "@/lib/instrument-context";
import type { OHLCVBar } from "@/types/api";

/**
 * OverlaySeries — a single TA indicator line to overlay on the OHLCV chart.
 *
 * WHY EXPORTED: TAOverlayPanel imports this type to type-check its
 * `onOverlaysChange` callback without creating a circular dependency.
 *
 * DESIGN NOTES:
 *   id          — stable string key (e.g. "ema-20", "boll-upper") used to
 *                 identify series handles in useChartSeries; changes cause
 *                 the old series to be removed and a new one created.
 *   data        — same length as the bars array; NaN entries are skipped
 *                 (lightweight-charts does not render gaps for NaN).
 *   axis        — "left" binds to the main candlestick price scale; "right"
 *                 is reserved for future right-axis oscillators (RSI on its
 *                 own axis). Currently all overlays use "left".
 *   strokeWidth — default 1; VWAP uses 2 for visual emphasis.
 */
export interface OverlaySeries {
  id: string;
  label: string;
  data: number[];
  color: string;
  axis?: "left" | "right";
  strokeWidth?: number;
}

interface OHLCVChartProps {
  instrumentId: string;
  /** Initial bars from CompanyOverview (last 30d 1D — render immediately). */
  initialBars?: OHLCVBar[];
  /**
   * KG entity UUID — forwarded to TAOverlayPanel to enable the SENTI chip
   * (sentiment timeseries overlay). When null/undefined the SENTI chip renders
   * disabled. Comes from QuoteTab → useInstrumentBrief().entity_id.
   */
  entityId?: string | null;
  /**
   * External TA overlay lines (PLAN-0091 F-1 escape hatch for non-QuoteTab callers).
   * When provided, these overlays are merged with (or override) the lines produced
   * by the internal TAOverlayPanel chip strip. Most callers should omit this prop
   * and rely on the chip strip instead.
   */
  overlays?: OverlaySeries[];
}

export function OHLCVChart({ instrumentId, initialBars, entityId, overlays: externalOverlays }: OHLCVChartProps) {
  const { accessToken } = useAuth();
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  // WHY default chartType="candle": candlestick is the institutional default for
  // equity charts — OHLC data visible in full. Line/Area are alternative views.
  const [chartType, setChartType] = useState<ChartType>("candle");
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

  // WHY overlayLines (internal state for chip-strip overlays, distinct from externalOverlays prop):
  //   TAOverlayPanel lives inside OHLCVChart because it needs `timeframe` + `data.bars`
  //   which are internal here. The chip strip calls handleOverlaysChange → setOverlayLines.
  //   The final `overlays` passed to useChartSeries merges chip lines with any external
  //   overlays (external prop takes precedence so embed callers can fully override).
  const [overlayLines, setOverlayLines] = useState<OverlaySeries[]>([]);
  const handleOverlaysChange = useCallback((lines: OverlaySeries[]) => {
    setOverlayLines(lines);
  }, []);

  // Merge chip-strip overlays with any externally-injected overlays.
  // WHY external prop takes precedence: embed callers (non-QuoteTab contexts) that
  // supply the `overlays` prop know exactly what they want — the chip strip should
  // not interfere. When externalOverlays is undefined the chip strip is the sole source.
  const resolvedOverlays = externalOverlays ?? overlayLines;

  const containerRef = useRef<HTMLDivElement>(null);

  // WHY useMemo: a fresh object every render re-fires the data-update effect
  // in useChartSeries — previously caused viewport scroll-to-1985 (BP-376).
  const memoizedPlaceholder = useMemo(() => {
    if (initialBars && timeframe === "1D") {
      return { instrument_id: instrumentId, ticker: "", timeframe: "1D" as const, bars: initialBars };
    }
    return undefined;
  }, [initialBars, timeframe, instrumentId]);

  const { data, isLoading } = useQuery({
    queryKey: ["ohlcv", instrumentId, timeframe],
    queryFn: () => createGateway(accessToken).getOHLCV(instrumentId, { timeframe }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 60_000, // WHY 1 min: bars in the current candle period don't change.
    placeholderData: memoizedPlaceholder,
  });

  const { chartError, setVisibleRange } = useChartSeries({
    containerRef, isFullscreen, isFullscreenRef, indicators,
    showVolume, showMA50, showMA200, showVolMA20, showVWAPLine,
    data, instrumentId, timeframe, logScaleRef, logScale,
    onVolumeProfileBuckets: handleVolumeProfileBuckets,
    // PLAN-0091 F-1: TA overlay lines from the chip strip (or external prop override).
    // useChartSeries manages the diff-based series creation/removal without re-mounting.
    overlays: resolvedOverlays,
    // Chart type toggle — controls which series kind renders the main price series.
    chartType,
  });

  // Range preset handler — translates a RangePreset into a chart timeScale call.
  // WHY useCallback: stable reference prevents unnecessary re-renders of TimeframeToolbar.
  const handleRangePreset = useCallback((preset: RangePreset) => {
    setVisibleRange(preset);
  }, [setVisibleRange]);

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

  // W5-T-07: numeric chord 1/5/30 switches the chart timeframe (Δ15).
  // WHY window-scoped with page guard: the chart may not be focused; window
  // capture reaches the shortcut regardless of focus state. The Quote-tab
  // scope guard in InstrumentTabs (T-26) prevents collision with global chords.
  //
  // WHY 1→1D / 5→1W / 30→1M:
  //   The Timeframe enum has "5M"|"1H"|"1D"|"1W"|"1M" — no "5D"/"30D".
  //   1 week = ~5 trading days; 1 month = ~30 trading days.
  //   The "30" chord is a 2-key sequence ("3" then "0"). We implement it via
  //   a pending-digit buffer with a 400ms window: pressing "3" primes the
  //   buffer; pressing "0" within 400ms completes the chord to "1M". If "3"
  //   is not followed by "0", it is discarded (no single-"3" action).
  //
  // WHY !e.ctrlKey && !e.metaKey && !e.altKey:
  //   Prevents shadowing browser shortcuts like Ctrl+1 (tab switch in many
  //   browsers) or Cmd+1 (macOS workspace switch).
  useEffect(() => {
    let pendingDigit: string | null = null;
    let pendingTimer: ReturnType<typeof setTimeout> | null = null;

    const clearPending = () => {
      pendingDigit = null;
      if (pendingTimer !== null) { clearTimeout(pendingTimer); pendingTimer = null; }
    };

    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) { clearPending(); return; }
      // WHY target check: ignore keypresses inside text inputs / textareas.
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        clearPending(); return;
      }
      if (pendingDigit === "3" && e.key === "0") {
        clearPending();
        setTimeframe("1M"); // 30 trading days ≈ 1M
        return;
      }
      clearPending();
      if (e.key === "1") { setTimeframe("1D"); return; }
      if (e.key === "5") { setTimeframe("1W"); return; } // 5 trading days ≈ 1W
      if (e.key === "3") {
        // Prime the 2-key "30" chord; discard after 400ms if "0" not pressed.
        pendingDigit = "3";
        pendingTimer = setTimeout(clearPending, 400);
      }
    };
    window.addEventListener("keydown", handler);
    return () => { window.removeEventListener("keydown", handler); clearPending(); };
  }, []);

  return (
    // WHY conditional class (Δ32 — W5-T-07):
    //   Fullscreen: fixed overlay fills the viewport (z-50).
    //   Normal: min-h-[320px] guarantees a usable chart height in the CSS Grid
    //     slot (QuoteTab grid cell). Previously 440px, reduced to 320px to give
    //     the MultiPeriodReturnsStrip + IntradayStatsBand room below the chart
    //     without requiring the user to scroll immediately on 1080p displays.
    //   `h-full flex flex-col`: fills the grid cell height; inner toolbar (h-7)
    //     + canvas (flex-1) stack without overflow.
    <div className={isFullscreen ? "fixed inset-0 z-50 bg-background flex flex-col" : "min-h-[320px] h-full flex flex-col"}>
      <div className="flex items-center h-7 px-2 border-b border-border/30 shrink-0">
        <TimeframeToolbar
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          logScale={logScale}
          onToggleLogScale={() => setLogScale((v) => !v)}
          // Compare overlay deferred (PRD-0088 §5) — required props passed as no-ops.
          showCompareInput={false}
          onToggleCompareInput={() => { /* deferred */ }}
          compareActive={false}
          compareInput=""
          onCompareInputChange={() => { /* deferred */ }}
          onCompareSubmit={() => { /* deferred */ }}
          // Chart type toggle (C/L/A buttons).
          chartType={chartType}
          onChartTypeChange={setChartType}
          // Range preset buttons (YTD/3Y/5Y/ALL).
          onRangePreset={handleRangePreset}
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

      {/* PLAN-0091 F-1: TA chip strip — renders below the toolbar, above the canvas.
          WHY inside OHLCVChart (not QuoteTab): TAOverlayPanel needs `timeframe` and
          `data.bars` which are internal state/data here. Rendering here avoids lifting
          them to QuoteTab which would bloat the orchestrator with chart-only concerns.
          WHY shrink-0: the chip strip must not flex-shrink — it is always visible
          regardless of chart height. The canvas area (flex-1) absorbs the remaining space.
          WHY data.bars ?? []: during the initial skeleton (data=undefined), the chip
          strip renders but all TA chips produce empty arrays → no overlays appear
          until bars arrive (correct behaviour — no "flash of empty lines"). */}
      {!chartError && (
        <TAOverlayPanel
          bars={data?.bars ?? []}
          onOverlaysChange={handleOverlaysChange}
          entityId={entityId}
          timeframe={timeframe}
        />
      )}

      {chartError && (
        <div className="flex items-center justify-center rounded-[2px] border border-border bg-card" style={{ height: CHART_HEIGHT }}>
          <p className="text-[11px] text-muted-foreground">Chart unavailable</p>
        </div>
      )}

      {!chartError && (
        // WHY containerRef stays mounted: removing it destroys the WebGL
        // context (visible flash + re-init). No left-gutter padding now that
        // the drawing palette is gone.
        // WHY h-full on wrapper + container (PLAN-0090 Y-axis scaling fix):
        // QuoteTab nests the chart in a `flex-1 min-h-0` slot; without h-full
        // the inner divs collapsed to their content (the chart canvas was
        // sized from clientHeight=0 → fallback 280px, leaving 70% empty).
        // h-full propagates the flex slot's height down to the lightweight-
        // charts container ref so chart.height = full slot height.
        <div className="relative w-full h-full" data-testid="chart-wrapper">
          <div ref={containerRef} className={`w-full h-full ${isFullscreen ? "flex-1" : ""}`} />
          {isLoading && !data && (
            <Skeleton className="pointer-events-none absolute inset-0 w-full" style={{ height: CHART_HEIGHT }} />
          )}
          {/* Empty-state for explicit 0-bar success response (CHART-001). */}
          {!isLoading && data && data.bars.length === 0 && (
            <div className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center justify-center" style={{ height: CHART_HEIGHT }}>
              <p className="text-[12px] text-muted-foreground">No price data for this timeframe</p>
              <p className="mt-1 text-[10px] text-muted-foreground/60">Try the 1D or 1W timeframe</p>
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
