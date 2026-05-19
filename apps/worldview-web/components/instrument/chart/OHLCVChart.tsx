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
import { Skeleton } from "@/components/ui/skeleton";
import { ChartToolbar } from "@/components/instrument/ChartToolbar";
import { TimeframeToolbar } from "@/components/instrument/chart/TimeframeToolbar";
import { useChartSeries } from "@/components/instrument/chart/useChartSeries";
import { CHART_HEIGHT, type Timeframe } from "@/lib/chart-adapter";
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
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
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

  const { data, isLoading } = useQuery({
    queryKey: ["ohlcv", instrumentId, timeframe],
    queryFn: () => createGateway(accessToken).getOHLCV(instrumentId, { timeframe }),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 60_000, // WHY 1 min: bars in the current candle period don't change.
    placeholderData: memoizedPlaceholder,
  });

  const { chartError } = useChartSeries({
    containerRef, isFullscreen, isFullscreenRef, indicators,
    showVolume, showMA50, showMA200, showVolMA20, showVWAPLine,
    data, instrumentId, timeframe, logScaleRef, logScale,
    onVolumeProfileBuckets: handleVolumeProfileBuckets,
  });

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
    <div className={isFullscreen ? "fixed inset-0 z-50 bg-background flex flex-col" : ""}>
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

      {!chartError && (
        // WHY containerRef stays mounted: removing it destroys the WebGL
        // context (visible flash + re-init). No left-gutter padding now that
        // the drawing palette is gone.
        <div className="relative w-full" data-testid="chart-wrapper">
          <div ref={containerRef} className={`w-full ${isFullscreen ? "flex-1" : ""}`} />
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
