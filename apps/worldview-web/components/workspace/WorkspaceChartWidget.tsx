/**
 * components/workspace/WorkspaceChartWidget.tsx — Panel-sized OHLCV chart
 *
 * WHY THIS EXISTS: The Instrument Detail page already has a heavy `OHLCVChart`
 * component with 7 indicators, drawing tools, fullscreen, and 280px fixed height.
 * That component is far too big and feature-rich for a workspace panel slot
 * (which can be as small as ~200px). This widget is a STRIPPED-DOWN sibling of
 * OHLCVChart — same lightweight-charts engine, same Midnight Pro palette, but:
 *   - No indicators (RSI/MACD/BB/etc.)
 *   - No drawing tools
 *   - No fullscreen
 *   - No volume MA / VWAP submenu
 *   - 5 timeframe pills (1D, 1W, 1M, 3M, 1Y) instead of intraday + 1M monthly
 *   - Fills 100% of the panel slot height (ResizeObserver-driven)
 *
 * WHY 1D/1W/1M/3M/1Y (not 5M/1H): workspace panels are for medium-term context.
 * Day traders who want intraday bars should open the full Instrument Detail page;
 * the workspace chart is meant to give "what does $TICKER look like over the last
 * year" at a glance, alongside a watchlist or news feed in adjacent panels.
 *
 * WHY no useSymbolLink import: the existing context (Part 1 may rename it later)
 * exports `useSymbolLinking`. Rather than break Part 1's WIP, this widget accepts
 * a `ticker` prop. The parent (WorkspacePanelContainer) is the one that reads
 * the linked symbol and forwards it. Future refactor: read directly from context
 * once Part 1's hook is finalized.
 *
 * WHO USES IT: WorkspacePanelContainer when panel.type === "chart"
 * DATA SOURCE: GET /v1/ohlcv/{instrumentId}?timeframe=… (S9 → S3 market-data)
 * DESIGN REFERENCE: PRD-0031 §5.4 Panel widgets, §0 Terminal CLI Quality Standard
 */

"use client";
// WHY "use client": uses useEffect (lightweight-charts DOM init), useRef (chart
// instance handle), useState (timeframe state), and ResizeObserver (browser-only
// API). None of this can run during SSR.

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { DashboardEmptyState } from "@/components/ui/dashboard-empty-state";
import { cn } from "@/lib/utils";

// ── Timeframe definitions ──────────────────────────────────────────────────────

/**
 * WorkspaceTimeframe — 5 medium-term horizons appropriate for a workspace pane.
 *
 * WHY this exact set: 1D = intraday context for swing traders; 1W = price action
 * over the last 6 months at weekly bars; 1M/3M/1Y = trend context. Skipping 5M/1H
 * intentional — workspace panels are not for scalping.
 *
 * The lookback `days` value is the LOAD WINDOW (how many days of history we
 * request). The timeframe `tf` value is the BAR SIZE we request from S3.
 * - 1D → 90 daily bars (3 months of dailies)
 * - 1W → 365 daily bars then aggregated to weekly (S3 returns weekly bars when timeframe="1w")
 * - 1M → 5 years of monthly bars (60 bars)
 * - 3M → 90 daily bars
 * - 1Y → 365 daily bars
 *
 * NOTE: S3's getOHLCV returns the bars at the requested timeframe; we don't aggregate
 * client-side. Our `days` field is informational for callers but unused in the actual
 * S9 call (S3 caps results internally).
 */
const TIMEFRAMES = [
  { id: "1D" as const, label: "1D", tf: "1D", days: 90 },
  { id: "1W" as const, label: "1W", tf: "1W", days: 365 },
  { id: "1M" as const, label: "1M", tf: "1M", days: 365 * 5 },
  { id: "3M" as const, label: "3M", tf: "1D", days: 90 },
  { id: "1Y" as const, label: "1Y", tf: "1D", days: 365 },
];

type WorkspaceTimeframeId = (typeof TIMEFRAMES)[number]["id"];

// ── Midnight Pro chart palette (hex literals — lightweight-charts can't read CSS vars) ─
//
// WHY hex literals (not CSS var()): lightweight-charts is a Canvas/WebGL library;
// it does NOT participate in the browser CSS cascade and has no access to
// document.documentElement.style.getPropertyValue() at the time it renders.
// Inline hex literals are the only reliable way to apply theme colors. If the
// design tokens in globals.css change, these constants must be updated to match
// (single source of truth: docs/ui/DESIGN_SYSTEM.md → Midnight Pro tokens).
const PALETTE = {
  background: "#09090B", // --background
  card: "#111113", // --card (used as recessive grid line color)
  text: "#71717A", // --muted-foreground (axis labels)
  positive: "#26A69A", // --positive (bullish candle, up wick)
  negative: "#EF5350", // --negative (bearish candle, down wick)
};

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * toUTCTimestamp — cast a Unix-seconds number to lightweight-charts' branded type.
 *
 * WHY this exists: lightweight-charts uses a phantom-tagged `UTCTimestamp` type
 * (number with a `_brand: "UTCTimestamp"` tag) so TypeScript catches accidental
 * millisecond-vs-second confusion. Our values ARE Unix seconds (Math.floor of
 * getTime()/1000), so the cast is safe — but `as UTCTimestamp` is more honest
 * than `as any` because it documents the contract.
 */
function toUTCTimestamp(t: number): UTCTimestamp {
  return t as UTCTimestamp;
}

// ── Component props ────────────────────────────────────────────────────────────

interface WorkspaceChartWidgetProps {
  /**
   * Optional ticker symbol (e.g., "AAPL"). When provided, the widget fetches
   * OHLCV bars for the corresponding instrument. When omitted, the widget shows
   * the empty state inviting the user to link a symbol via the color picker.
   *
   * WHY ticker (not instrumentId): higher-level callers (WorkspacePanelContainer)
   * already do the ticker→instrumentId mapping for the demo seed (entity-aapl /
   * ins-aapl). To stay decoupled from that mapping, this widget receives the
   * ticker and derives instrumentId itself with the same convention.
   */
  ticker?: string;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function WorkspaceChartWidget({ ticker }: WorkspaceChartWidgetProps) {
  const { accessToken } = useAuth();

  // WHY default 3M (not 1D): a workspace chart is for context, not signal.
  // 3 months of daily bars is the right horizon for "what's the trend?"
  const [activeTfId, setActiveTfId] = useState<WorkspaceTimeframeId>("3M");
  const activeTf = TIMEFRAMES.find((t) => t.id === activeTfId) ?? TIMEFRAMES[0];

  // WHY this convention: matches WorkspacePanelContainer's demo mapping
  // (entity-aapl / ins-aapl). The S9 demo seed uses lowercase ticker as suffix.
  // If ticker is undefined, we deliberately do NOT issue the OHLCV request —
  // the empty state renders instead.
  const instrumentId = ticker ? `ins-${ticker.toLowerCase()}` : undefined;

  // ── Data fetch ───────────────────────────────────────────────────────────
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["workspace-chart-ohlcv", instrumentId, activeTf.tf],
    queryFn: () => createGateway(accessToken).getOHLCV(instrumentId!, { timeframe: activeTf.tf }),
    // WHY enabled gate: don't fire requests when there's no symbol or no auth
    enabled: !!accessToken && !!instrumentId,
    // WHY 60s: OHLCV bars don't change within the same candle period during
    // market hours. After 60s we let TanStack Query consider the data stale and
    // refetch on the next focus/mount. Outside market hours, the data simply
    // doesn't change at all — the staleTime is harmless.
    staleTime: 60_000,
  });

  // ── Container + chart instance refs ──────────────────────────────────────
  // WHY refs (not state): lightweight-charts instances are MUTABLE handles we
  // call .setData() / .applyOptions() on directly. Storing them in state would
  // re-render every time we re-fetch data (we never want that — only the chart
  // canvas changes, not the React tree).
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // WHY chartError state: if lightweight-charts' dynamic import fails (CDN down,
  // bundle corruption), we MUST show a fallback rather than blank space. Financial
  // UIs blank-failing erodes user trust — silent failures are forbidden by §0.
  const [chartError, setChartError] = useState(false);

  // ── Chart lifecycle ──────────────────────────────────────────────────────
  // WHY init effect runs only when instrumentId changes (not every render):
  //
  // 1. CREATE: chart on first mount with a valid instrumentId.
  // 2. KEEP: same chart instance across timeframe switches (we just call
  //    series.setData() with the new bars when data changes).
  // 3. DESTROY: on unmount or when instrumentId becomes undefined (e.g. user
  //    unlinks the symbol).
  //
  // CRITICAL: lightweight-charts allocates a Canvas/WebGL context. Forgetting
  // to call chart.remove() in cleanup leaks GPU memory; with multiple panels,
  // the browser tab can OOM after a few minutes of resizing.
  useEffect(() => {
    if (!containerRef.current || !instrumentId) {
      // WHY clear refs here too: when instrumentId becomes undefined, we want
      // any previous chart torn down. The cleanup function below does that — we
      // just need to bail early so we don't try to recreate a chart with no data.
      return;
    }

    let chart: IChartApi | null = null;

    async function initChart() {
      try {
        // WHY dynamic import: lightweight-charts uses browser APIs (Canvas) that
        // would explode at SSR. Dynamic import keeps it client-only.
        const { createChart } = await import("lightweight-charts");

        // WHY this null-check after await: dynamic import is async — by the time
        // it resolves, the component may have unmounted. containerRef would be
        // null in that case. Bailing prevents creating an orphaned chart.
        if (!containerRef.current) return;

        chart = createChart(containerRef.current, {
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
          layout: {
            background: { color: PALETTE.background },
            textColor: PALETTE.text,
          },
          grid: {
            // WHY card color (not border color): #27272A border would be too
            // prominent — competes with candlesticks. #111113 is the recessive
            // structural color, just a hair brighter than background.
            vertLines: { color: PALETTE.card },
            horzLines: { color: PALETTE.card },
          },
          crosshair: { mode: 0 }, // 0 = Normal (both X and Y crosshairs)
          rightPriceScale: { borderColor: PALETTE.card },
          timeScale: { borderColor: PALETTE.card, timeVisible: true },
        });

        const series = chart.addCandlestickSeries({
          upColor: PALETTE.positive,
          downColor: PALETTE.negative,
          borderUpColor: PALETTE.positive,
          borderDownColor: PALETTE.negative,
          wickUpColor: PALETTE.positive,
          wickDownColor: PALETTE.negative,
        });

        chartRef.current = chart;
        seriesRef.current = series;
      } catch (err) {
        // WHY catch: a corrupt build or CDN hiccup must surface as the error
        // banner — never a silent blank panel. The error banner offers retry.
        // eslint-disable-next-line no-console
        console.error("WorkspaceChartWidget: failed to load lightweight-charts:", err);
        setChartError(true);
      }
    }

    initChart();

    // ── ResizeObserver — react to panel resize drags ─────────────────────
    // WHY ResizeObserver (not window.resize): the panel slot can change size
    // independently of the window (e.g., user drags the row separator). RO
    // fires whenever the OBSERVED ELEMENT's box changes, which is exactly what
    // we need. window resize would only fire on viewport changes.
    //
    // WHY observe containerRef (not document.body): we only care about THIS
    // panel's slot dimensions. Observing body would fire for every layout shift.
    const observer = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      // WHY this exact teardown order:
      // 1. Disconnect observer first — prevents a queued RO callback from firing
      //    after we've already removed the chart (would be a use-after-free).
      // 2. chart.remove() releases the Canvas/WebGL context. CRITICAL: skipping
      //    this leaks GPU memory; with N workspace panels, browser tabs OOM.
      // 3. Null the refs so a subsequent setData attempt no-ops harmlessly.
      observer.disconnect();
      chart?.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [instrumentId]);

  // ── Update chart data when bars change ───────────────────────────────────
  // WHY separate effect: chart instance lives across timeframe switches (per
  // the lifecycle effect above). When bars change we just push new data into
  // the existing series — much cheaper than tearing down and recreating.
  useEffect(() => {
    if (!seriesRef.current || !data?.bars) return;

    const formatted = data.bars.map((bar) => ({
      // WHY Math.floor(.../1000): lightweight-charts wants seconds, not millis.
      time: toUTCTimestamp(Math.floor(new Date(bar.timestamp).getTime() / 1000)),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    // WHY the eslint-disable: setData() expects CandlestickData[] which uses
    // the branded UTCTimestamp type. Our `formatted` already uses the brand,
    // but TS still wants an explicit assertion through `unknown` first. The
    // shape is correct at runtime — `as unknown as never[]` would be uglier.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    seriesRef.current.setData(formatted as any);

    // WHY fitContent: defaults to showing the most recent ~50 bars; without
    // this, lightweight-charts shows ALL bars cramped into the panel width.
    // fitContent uses the most-recent visible range that fits comfortably.
    if (formatted.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [data?.bars]);

  // ── Retry handler — exposed in the error banner ──────────────────────────
  // WHY useCallback: retry button is an inline JSX child of an error banner
  // that re-renders on every state change. useCallback gives a stable handler
  // reference so the button doesn't churn React's reconciliation tree.
  const handleRetry = useCallback(() => {
    setChartError(false);
    refetch();
  }, [refetch]);

  // ── Render: empty state when no symbol linked ─────────────────────────────
  if (!ticker) {
    return (
      // WHY full-height wrapper: keeps the empty state vertically centered in
      // the panel slot regardless of how the user has resized it.
      <div className="flex h-full w-full items-center justify-center">
        <DashboardEmptyState
          title="No symbol linked"
          message="Pick a symbol via the color picker or click a row in another panel."
        />
      </div>
    );
  }

  // ── Render: error state ──────────────────────────────────────────────────
  if (isError || chartError) {
    return (
      <div className="flex h-full w-full flex-col">
        {/* WHY border-l-2 + bg-negative tint: matches the canonical error banner
            pattern used elsewhere (alerts page, brokerage callback errors). */}
        <div
          className="m-2 flex items-center justify-between gap-2 rounded-[2px] border-l-2 border-negative bg-negative/10 px-2 py-1"
          role="alert"
        >
          <span className="text-[11px] text-foreground">Chart unavailable</span>
          <button
            onClick={handleRetry}
            className="rounded-[2px] px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground hover:text-foreground"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Render: full chart layout ────────────────────────────────────────────
  return (
    // WHY flex-col h-full: chart fills the entire panel slot. Header is fixed
    // height (h-6 = 24px), chart canvas takes remaining space.
    <div className="flex h-full w-full flex-col">
      {/* ── Sub-header: ticker + timeframe selector ──────────────────────── */}
      {/*
       * WHY h-6 (24px): consistent with the WorkspacePanelContainer header
       * height and other in-panel toolbars. Anything taller wastes pixels.
       * WHY border-b border-border/30: subtle separator from the chart canvas
       * below, half opacity so it doesn't compete with the panel border.
       */}
      <div className="flex h-6 shrink-0 items-center gap-2 border-b border-border/30 px-2">
        {/* Ticker text — font-mono uppercase 11px primary color */}
        <span
          className="font-mono text-[11px] uppercase tabular-nums text-primary"
          aria-label={`Ticker ${ticker}`}
        >
          {ticker}
        </span>

        {/* Timeframe selector — 5 small buttons */}
        {/*
         * WHY raw buttons (not shadcn ToggleGroup): the existing OHLCVChart
         * timeframe pills use the same raw-button pattern. Keeping the same
         * pattern here avoids visual divergence between the two chart components.
         * shadcn ToggleGroup would also add ~3kb of bundle for what is effectively
         * 5 stateful buttons.
         */}
        <div className="ml-auto flex items-center gap-px">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf.id}
              onClick={() => setActiveTfId(tf.id)}
              className={cn(
                "rounded-[2px] px-1.5 py-0.5 text-[10px] font-medium transition-colors duration-0",
                tf.id === activeTfId
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
              aria-pressed={tf.id === activeTfId}
              aria-label={`Set timeframe ${tf.label}`}
            >
              {tf.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Chart canvas area ────────────────────────────────────────────── */}
      {/*
       * WHY relative + flex-1 + min-h-0: fills remaining vertical space below
       * the header. min-h-0 is REQUIRED because flex children default to
       * min-height: auto (= content size) which would push the chart past the
       * panel boundary in flexbox. min-h-0 lets the chart shrink/grow with
       * the panel slot.
       *
       * WHY data-testid="workspace-chart-canvas": targeted by the Vitest tests
       * to assert the chart container exists. We don't need to test the actual
       * canvas pixels — just that the container is rendered with the right
       * structure when ticker is present.
       */}
      <div className="relative flex-1 min-h-0" data-testid="workspace-chart-canvas">
        <div ref={containerRef} className="h-full w-full" />

        {/* ── Skeleton overlay during initial load ───────────────────── */}
        {/*
         * WHY pointer-events-none: the skeleton must not intercept clicks meant
         * for the timeframe buttons or the panel header (e.g., close button).
         * absolute inset-0 + h-full guarantees full coverage during load.
         */}
        {isLoading && !data && (
          <Skeleton className="pointer-events-none absolute inset-0 h-full w-full" />
        )}
      </div>
    </div>
  );
}
