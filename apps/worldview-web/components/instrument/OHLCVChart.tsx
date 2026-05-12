/**
 * components/instrument/OHLCVChart.tsx — OHLCV candlestick chart (orchestrator)
 *
 * WHY THIS EXISTS: Institutional traders assess price action visually before
 * reading fundamentals. A candlestick chart communicates open/high/low/close
 * (the complete daily narrative) in a single glyph, unlike a line chart.
 *
 * WHY lightweight-charts: TradingView's open-source chart library — WebGL-
 * accelerated, zero external dependencies, familiar to Bloomberg users.
 *
 * ARCHITECTURE (PLAN-0089 Wave D-1 split):
 *   - lib/chart-adapter.ts       — pure data-transform utilities + constants
 *   - chart/useChartSeries.ts    — all lightweight-charts series management
 *   - chart/TimeframeToolbar.tsx — timeframe selector, log toggle, compare popover
 *   - ChartToolbar.tsx           — MA/Vol/Indicator/Fullscreen controls
 *
 * This file owns React state, wires props to sub-components, and renders
 * the chart wrapper with drawing palette + annotation overlay.
 *
 * WHO USES IT: OverviewLayout
 * DATA SOURCE: S9 GET /v1/ohlcv/{instrumentId}?timeframe=1D
 * DESIGN REFERENCE: PRD-0028 §6.5, PLAN-0050 §Wave C, PLAN-0089 Wave D-1
 */

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { UTCTimestamp } from "lightweight-charts";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import { DrawingPalette } from "@/components/instrument/DrawingPalette";
import { DrawingCanvas } from "@/components/instrument/DrawingCanvas";
import { VolumeProfileOverlay } from "@/components/instrument/VolumeProfileOverlay";
import { CrosshairHUD } from "@/components/instrument/CrosshairHUD";
import { TimeframeToolbar } from "@/components/instrument/chart/TimeframeToolbar";
import { useChartSeries } from "@/components/instrument/chart/useChartSeries";
import { CHART_HEIGHT, PALETTE_WIDTH, type Timeframe } from "@/lib/chart-adapter";
import {
  loadIndicatorsFromStorage,
  saveIndicatorsToStorage,
  loadAnnotationsFromIDB,
  saveAnnotationsToIDB,
  type IndicatorId,
  type Annotation,
  type VolumeProfileBucket,
} from "@/lib/instrument-context";
import type { OHLCVBar } from "@/types/api";

// ── Props ──────────────────────────────────────────────────────────────────────

interface OHLCVChartProps {
  instrumentId: string;
  /** Initial bars from CompanyOverview (last 30 days 1D — show immediately) */
  initialBars?: OHLCVBar[];
}

// ── Component ──────────────────────────────────────────────────────────────────

export function OHLCVChart({ instrumentId, initialBars }: OHLCVChartProps) {
  const { accessToken } = useAuth();
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");

  // ── Toolbar toggle state ───────────────────────────────────────────────────
  // WHY default showVolume=true: volume is standard in all financial charting UIs.
  const [showVolume, setShowVolume] = useState(true);
  const [showMA50, setShowMA50] = useState(false);
  const [showMA200, setShowMA200] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  // WHY isFullscreenRef: the ResizeObserver callback (in useChartSeries) captures
  // a stale closure; the ref always reflects the current value across renders.
  const isFullscreenRef = useRef(false);
  useEffect(() => { isFullscreenRef.current = isFullscreen; }, [isFullscreen]);

  // ── Indicator state — lazy init reads localStorage ─────────────────────────
  const [indicators, setIndicators] = useState(() => loadIndicatorsFromStorage());

  // ── Volume submenu state ───────────────────────────────────────────────────
  const [showVolMA20, setShowVolMA20] = useState(false);
  const [showVolProfile, setShowVolProfile] = useState(false);
  const [showVWAPLine, setShowVWAPLine] = useState(false);

  // ── Log-scale toggle ───────────────────────────────────────────────────────
  // WHY default false: linear is the institutional default.
  const [logScale, setLogScale] = useState(false);
  // logScaleRef: stale-closure-safe ref read at chart-init time so the user's
  // pre-init choice is applied as soon as the dynamic import resolves.
  const logScaleRef = useRef(logScale);
  logScaleRef.current = logScale;

  // ── Volume profile data (computed inside useChartSeries, surfaced here) ───
  const [volumeProfileBuckets, setVolumeProfileBuckets] = useState<VolumeProfileBucket[]>([]);

  // ── Drawing palette + annotation state ────────────────────────────────────
  const [activeTool, setActiveTool] = useState<import("@/lib/instrument-context").DrawingToolId | null>(null);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);

  // ── Compare overlay state ──────────────────────────────────────────────────
  // WHY three separate states: each changes at a different point in the flow.
  const [showCompareInput, setShowCompareInput] = useState(false);
  const [compareInput, setCompareInput] = useState("");
  const [compareInstrumentId, setCompareInstrumentId] = useState<string | null>(null);

  // ── Chart canvas container ref ─────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null);

  // PLAN-0053 T-A-1-01: stabilise placeholderData reference. A fresh object
  // literal on every render causes the data-update effect to re-fire →
  // setVolumeProfileBuckets → re-render → infinite loop (chart scrolls to 1985).
  // useMemo keeps the reference stable so the effect fires only on real bar changes.
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
    staleTime: 60_000, // WHY 1min: OHLCV bars don't change within the same candle period
    placeholderData: memoizedPlaceholder,
  });

  // ── Compare overlay OHLCV query ────────────────────────────────────────────
  const { data: compareData } = useQuery({
    queryKey: ["ohlcv", compareInstrumentId, timeframe],
    queryFn: () => createGateway(accessToken).getOHLCV(compareInstrumentId!, { timeframe }),
    enabled: !!accessToken && !!compareInstrumentId,
    staleTime: 60_000,
  });

  // ── useChartSeries — all lightweight-charts logic ─────────────────────────
  // WHY useCallback for onVolumeProfileBuckets: it's in useChartSeries' data-update
  // effect deps — a new reference on every render would cause the effect to re-fire.
  const handleVolumeProfileBuckets = useCallback((buckets: VolumeProfileBucket[]) => {
    setVolumeProfileBuckets(buckets);
  }, []);

  const { chartRef, seriesRef, volumeSeriesRef, compareSeriesRef, converters, chartError } =
    useChartSeries({
      containerRef, isFullscreen, isFullscreenRef, indicators,
      showVolume, showMA50, showMA200, showVolMA20, showVWAPLine,
      data, instrumentId, timeframe, logScaleRef, logScale,
      onVolumeProfileBuckets: handleVolumeProfileBuckets,
    });

  // ── Apply compare series data when resolved ────────────────────────────────
  useEffect(() => {
    if (!compareData?.bars?.length || !chartRef.current) return;
    async function addCompareSeries() {
      try {
        const { LineSeries } = await import("lightweight-charts");
        if (compareSeriesRef.current && chartRef.current) {
          chartRef.current.removeSeries(compareSeriesRef.current);
          compareSeriesRef.current = null;
        }
        if (!chartRef.current) return;
        // WHY amber (#F59E0B): visually distinct from green/red candlesticks and blue MAs.
        // WHY "compare" priceScaleId: avoids sharing the right scale (which makes one flat).
        const compareSeries = chartRef.current.addSeries(LineSeries, {
          color: "#F59E0B", lineWidth: 1, priceScaleId: "compare",
        });
        compareSeriesRef.current = compareSeries;
        // WHY normalise: the compare overlay shows relative performance, not absolute price.
        const bars = compareData!.bars;
        const baseClose = bars[0]?.close ?? 1;
        compareSeries.setData(bars.map((b) => ({
          time: Math.floor(new Date(b.timestamp).getTime() / 1000) as UTCTimestamp,
          value: ((b.close - baseClose) / baseClose) * 100,
        })));
      } catch { /* non-fatal — overlay failure must not crash the main chart */ }
    }
    void addCompareSeries();
  }, [compareData, chartRef, compareSeriesRef]);

  // ── Handle compare ticker submit ───────────────────────────────────────────
  const handleCompareSubmit = useCallback(async () => {
    const ticker = compareInput.trim().toUpperCase();
    if (!ticker) return;
    try {
      const results = await createGateway(accessToken).searchInstruments(ticker, 1);
      const first = results?.results?.[0];
      if (first?.instrument_id) setCompareInstrumentId(first.instrument_id);
    } catch { /* non-fatal */ }
    setShowCompareInput(false);
    setCompareInput("");
  }, [accessToken, compareInput]);

  // ── Load annotations from IndexedDB on instrumentId change ────────────────
  useEffect(() => {
    let cancelled = false;
    loadAnnotationsFromIDB(instrumentId).then((saved) => { if (!cancelled) setAnnotations(saved); });
    return () => { cancelled = true; };
  }, [instrumentId]);

  // ── Indicator toggle ───────────────────────────────────────────────────────
  const handleToggleIndicator = useCallback((id: IndicatorId) => {
    setIndicators((prev) => {
      const updated = { ...prev, [id]: { ...prev[id], enabled: !prev[id].enabled } };
      saveIndicatorsToStorage(updated);
      return updated;
    });
  }, []);

  // ── Annotation handlers ────────────────────────────────────────────────────
  const handleAnnotationAdd = useCallback((annotation: Annotation) => {
    setAnnotations((prev) => {
      const next = [...prev, annotation];
      void saveAnnotationsToIDB(instrumentId, next);
      return next;
    });
  }, [instrumentId]);

  const handleAnnotationDelete = useCallback((id: string) => {
    setAnnotations((prev) => {
      const next = prev.filter((a) => a.id !== id);
      void saveAnnotationsToIDB(instrumentId, next);
      return next;
    });
  }, [instrumentId]);

  // ── Escape key exits fullscreen ────────────────────────────────────────────
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setIsFullscreen(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isFullscreen]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    // WHY conditional fixed positioning: fullscreen stretches chart to fill the
    // entire viewport (z-50 above all panels). Exit via ChartToolbar or Escape.
    <div className={isFullscreen ? "fixed inset-0 z-50 bg-background flex flex-col" : ""}>

      {/* ── Combined toolbar: timeframe + chart controls ──────────────────── */}
      <div className="flex items-center h-7 px-2 border-b border-border/30 shrink-0">
        {/* Left: timeframe buttons, log toggle, compare popover */}
        <TimeframeToolbar
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          logScale={logScale}
          onToggleLogScale={() => setLogScale((v) => !v)}
          showCompareInput={showCompareInput}
          onToggleCompareInput={() => setShowCompareInput((v) => !v)}
          compareActive={!!compareInstrumentId}
          compareInput={compareInput}
          onCompareInputChange={setCompareInput}
          onCompareSubmit={() => void handleCompareSubmit()}
        />
        {/* Right: MA/Vol/Indicator/Fullscreen overlay controls */}
        <div className="ml-auto flex items-center">
          <ChartToolbar
            showVolume={showVolume}
            onToggleVolume={() => setShowVolume((v) => !v)}
            showMA50={showMA50}
            onToggleMA50={() => setShowMA50((v) => !v)}
            showMA200={showMA200}
            onToggleMA200={() => setShowMA200((v) => !v)}
            isFullscreen={isFullscreen}
            onFullscreen={() => setIsFullscreen((v) => !v)}
            indicators={indicators}
            onToggleIndicator={handleToggleIndicator}
            showVolMA20={showVolMA20}
            onToggleVolMA20={() => setShowVolMA20((v) => !v)}
            showVolProfile={showVolProfile}
            onToggleVolProfile={() => setShowVolProfile((v) => !v)}
            showVWAPLine={showVWAPLine}
            onToggleVWAPLine={() => setShowVWAPLine((v) => !v)}
          />
        </div>
      </div>

      {/* ── Chart error fallback ──────────────────────────────────────────── */}
      {chartError && (
        <div
          className="flex items-center justify-center rounded-[2px] border border-border bg-card"
          style={{ height: CHART_HEIGHT }}
        >
          <p className="text-[11px] text-muted-foreground">Chart unavailable</p>
        </div>
      )}

      {/* ── Chart wrapper: [DrawingPalette][chart canvas + DrawingCanvas SVG]
          position:relative lets palette + SVG overlay be absolutely positioned.
          WHY always in DOM (not conditional): removing containerRef destroys
          the WebGL context — expensive flash + re-init. */}
      {!chartError && (
        <div className="relative w-full" data-testid="chart-wrapper">

          <DrawingPalette
            activeTool={activeTool}
            onSelectTool={setActiveTool}
            annotationCount={annotations.length}
          />

          {/* WHY pl-7: offset chart canvas past the 28px drawing palette */}
          <div ref={containerRef} className={`w-full pl-7 ${isFullscreen ? "flex-1" : ""}`} />

          <DrawingCanvas
            activeTool={activeTool}
            annotations={annotations}
            onAnnotationAdd={handleAnnotationAdd}
            onAnnotationDelete={handleAnnotationDelete}
            converters={converters}
            chartHeight={isFullscreen ? window.innerHeight - 60 : CHART_HEIGHT}
            paletteWidth={PALETTE_WIDTH}
          />

          {showVolProfile && (
            <VolumeProfileOverlay
              buckets={volumeProfileBuckets}
              converters={converters}
              chartHeight={isFullscreen ? window.innerHeight - 60 : CHART_HEIGHT}
              profileWidth={60}
            />
          )}

          {/* Crosshair HUD: OHLCV + volume at hovered bar. Pointer-events
              disabled so it never blocks chart crosshair tracking. */}
          <CrosshairHUD
            chart={chartRef.current}
            candleSeries={seriesRef.current}
            volumeSeries={volumeSeriesRef.current}
          />

          {/* Skeleton while loading and no placeholder data yet */}
          {isLoading && !data && (
            <Skeleton
              className="pointer-events-none absolute inset-0 w-full"
              style={{ height: CHART_HEIGHT }}
            />
          )}

          {/* Empty-state for 0 bars (CHART-001 fix, 2026-05-09):
              WHY check `data && bars.length === 0` (not `!data`):
              `!data` is the loading case (Skeleton above). Empty is a
              successful response that happens to have no data. */}
          {!isLoading && data && data.bars.length === 0 && (
            <div
              className="pointer-events-none absolute inset-x-0 top-0 flex flex-col items-center justify-center"
              style={{ height: CHART_HEIGHT }}
            >
              <p className="text-[12px] text-muted-foreground">No price data for this timeframe</p>
              <p className="mt-1 text-[10px] text-muted-foreground/60">Try the 1D or 1W timeframe</p>
            </div>
          )}

          {/* "refreshing" pill during background refetch */}
          {isLoading && data && (
            <span
              role="status"
              aria-live="polite"
              className="pointer-events-none absolute right-2 top-2 rounded-[2px] bg-muted/80 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-muted-foreground"
            >
              refreshing
            </span>
          )}
        </div>
      )}
    </div>
  );
}
