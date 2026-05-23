/**
 * components/instrument/chart/TimeframeToolbar.tsx — Timeframe + log + compare + type + range controls
 *
 * WHY THIS EXISTS: OHLCVChart.tsx had ~115 lines of inline toolbar JSX for timeframe
 * selection, log-scale toggle, and the compare-overlay popover. Extracting them into
 * this component lets OHLCVChart focus on chart orchestration while this component
 * is a pure presentation layer with no chart-library dependencies.
 *
 * WHY PARENT-CONTROLLED STATE: OHLCVChart owns the timeframe (drives API queries),
 * logScale (drives chart.priceScale options), and compare state (drives the compare
 * OHLCV query). This component only reflects and reports user intent — keeping all
 * state in OHLCVChart avoids the need for a context or event bus.
 *
 * WHY SEPARATE FROM ChartToolbar: ChartToolbar handles overlay toggles (MA, Vol,
 * Indicators, Fullscreen). TimeframeToolbar handles navigation controls (which
 * timeframe am I looking at, log mode, compare, chart type, range presets). The two
 * have different conceptual roles and different update frequencies — timeframe changes
 * trigger API fetches, overlay toggles are purely local visibility changes.
 *
 * CHART TYPE TOGGLE (added here):
 *   Three compact buttons — C (Candle), L (Line), A (Area) — sit to the right of
 *   the range presets. The actual series-swap happens in useChartSeries; this toolbar
 *   only reports user intent via onChartTypeChange.
 *
 * RANGE PRESETS (added here):
 *   YTD / 3Y / 5Y / ALL buttons shift the visible range without changing the fetch
 *   timeframe. They trigger the 1D timeframe (daily bars) and pass a preset ID to
 *   onRangePreset; the parent translates presets to lightweight-charts timeScale calls.
 *
 * WHO USES IT: components/instrument/OHLCVChart.tsx
 * PLAN REFERENCE: PLAN-0089 Wave D-1 (split OHLCVChart into chart/ subdirectory)
 */

// WHY no "use client": this is a pure presentation component — no hooks or browser
// APIs needed. The parent OHLCVChart (which is "use client") renders it.

import type { Timeframe, ChartType, RangePreset } from "@/lib/chart-adapter";

// ── Constants ──────────────────────────────────────────────────────────────────

/**
 * RANGE_PRESETS — ordered list of visible-range shortcuts shown after the
 * timeframe interval buttons.
 *
 * WHY this order (YTD → 3Y → 5Y → ALL): increasing duration — matches Bloomberg
 * terminal UX where shorter ranges appear first. ALL is last because it is the
 * least precise (no date anchor).
 */
const RANGE_PRESETS: RangePreset[] = ["YTD", "3Y", "5Y", "ALL"];

/**
 * CHART_TYPE_BUTTONS — compact C/L/A buttons displayed to the right of range
 * presets. Font-mono 10px keeps them at terminal density.
 */
const CHART_TYPE_BUTTONS: { type: ChartType; label: string; title: string }[] = [
  { type: "candle", label: "C", title: "Candlestick chart" },
  { type: "line",   label: "L", title: "Line chart (close price)" },
  { type: "area",   label: "A", title: "Area chart (close price)" },
];

// ── Props ──────────────────────────────────────────────────────────────────────

export interface TimeframeToolbarProps {
  /** Currently selected timeframe — drives the active button highlight */
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;

  /** Whether log-scale is active on the right price axis */
  logScale: boolean;
  onToggleLogScale: () => void;

  /** Whether the compare input popover is open */
  showCompareInput: boolean;
  onToggleCompareInput: () => void;

  /** Whether a compare instrument is currently active */
  compareActive: boolean;

  /** The current value of the compare ticker text input */
  compareInput: string;
  onCompareInputChange: (value: string) => void;

  /** Called when user presses Enter or clicks "Go" in the compare popover */
  onCompareSubmit: () => void;

  /**
   * Active chart rendering type (Candle / Line / Area).
   * Default: "candle" — callers that don't need the toggle can omit this.
   */
  chartType?: ChartType;
  onChartTypeChange?: (type: ChartType) => void;

  /**
   * Fired when user clicks a range preset (YTD / 3Y / 5Y / ALL).
   * The parent is responsible for translating the preset to a lightweight-charts
   * timeScale.setVisibleRange() call (or fitContent() for ALL).
   *
   * WHY callback (not direct chart access): this toolbar has no dependency on the
   * chart API — it stays a pure presentation component. The parent (OHLCVChart)
   * owns the chart ref and handles the actual viewport change.
   */
  onRangePreset?: (preset: RangePreset) => void;
}

// ── Component ──────────────────────────────────────────────────────────────────

export function TimeframeToolbar({
  timeframe,
  onTimeframeChange,
  logScale,
  onToggleLogScale,
  showCompareInput,
  onToggleCompareInput,
  compareActive,
  compareInput,
  onCompareInputChange,
  onCompareSubmit,
  chartType = "candle",
  onChartTypeChange,
  onRangePreset,
}: TimeframeToolbarProps) {
  return (
    <>
      {/* Timeframe interval tabs — left side of toolbar */}
      {/* WHY this exact order: intraday (5M, 1H) → daily → weekly → monthly.
          1W/1M are added because S3 ingests weekly/monthly EODHD bars as
          first-class timeframes. */}
      {(["5M", "1H", "1D", "1W", "1M"] as Timeframe[]).map((tf) => (
        <button
          key={tf}
          onClick={() => onTimeframeChange(tf)}
          className={`rounded-[2px] px-2 py-0.5 text-[11px] font-medium transition-colors ${
            timeframe === tf
              ? "bg-primary/20 text-primary"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          {tf}
        </button>
      ))}

      {/* Hairline separator: timeframe intervals (high-frequency) → range presets (viewport-only) */}
      <span className="mx-1.5 h-3 w-px shrink-0 bg-border/50" aria-hidden />

      {/* Range preset buttons — set the visible viewport without changing the fetched data.
          WHY they also call onTimeframeChange("1D"): range presets make most sense on
          daily bars. If the user is on 5M, zooming to "3Y" would show 3 years of 5-min
          candles which is dense to the point of being unreadable. Switching to 1D first
          gives a clean daily bar view before applying the range viewport. */}
      {onRangePreset && RANGE_PRESETS.map((preset) => (
        <button
          key={preset}
          data-testid={`range-preset-${preset.toLowerCase()}`}
          onClick={() => {
            // Ensure 1D bars are fetched (range presets pair with daily bars).
            if (timeframe !== "1D") onTimeframeChange("1D");
            onRangePreset(preset);
          }}
          className="rounded-[2px] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70 hover:text-foreground transition-colors"
          title={
            preset === "YTD" ? "Year to date" :
            preset === "ALL" ? "Fit all bars" :
            `Last ${preset}`
          }
        >
          {preset}
        </button>
      ))}

      {/* Hairline separator: range presets → view-mode toggles */}
      <span className="mx-1.5 h-3 w-px shrink-0 bg-border/50" aria-hidden />

      {/* Chart type toggle: C (Candle) / L (Line) / A (Area).
          WHY compact w-6 h-6 font-mono buttons: Bloomberg-grade density — these are
          single-key selections, not labels. The active type gets primary tint matching
          the timeframe active state convention used throughout this toolbar. */}
      {onChartTypeChange && CHART_TYPE_BUTTONS.map(({ type, label, title }) => (
        <button
          key={type}
          data-testid={`chart-type-${type}`}
          onClick={() => onChartTypeChange(type)}
          aria-pressed={chartType === type}
          title={title}
          className={`inline-flex items-center justify-center w-6 h-6 rounded-[2px] font-mono text-[10px] transition-colors ${
            chartType === type
              ? "bg-primary/20 text-primary"
              : "text-muted-foreground/70 hover:text-foreground"
          }`}
        >
          {label}
        </button>
      ))}

      {/* QA iter-1: 1px hairline separator marks the visual class break
          between chart-type toggles and view-mode toggles (log scale). */}
      <span className="mx-1.5 h-3 w-px shrink-0 bg-border/50" aria-hidden />

      {/* PLAN-0059 H-2: log-scale toggle. Demoted from primary-tinted (which
          visually competed with active timeframe) to ghost+ring style: log
          is a rare-toggle view mode, not a timeframe sibling. */}
      <button
        onClick={onToggleLogScale}
        className={`rounded-[2px] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors ${
          logScale
            ? "text-foreground ring-1 ring-border bg-transparent"
            : "text-muted-foreground/70 hover:text-foreground"
        }`}
        aria-pressed={logScale}
        aria-label="Toggle logarithmic price scale"
        title="Logarithmic price scale"
      >
        log
      </button>

      {/* PLAN-0059 H-2: Compare overlay button (+CMP).
          WHY data-testid="toolbar-compare": the H-2 test finds this button
          by testid to open the compare popover. */}
      <div className="relative ml-2 flex items-center">
        <button
          data-testid="toolbar-compare"
          onClick={onToggleCompareInput}
          className={`rounded-[2px] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider transition-colors ${
            showCompareInput || compareActive
              ? "text-foreground ring-1 ring-border bg-transparent"
              : "text-muted-foreground/70 hover:text-foreground"
          }`}
          aria-pressed={showCompareInput}
          aria-label="Toggle compare overlay"
          title="Compare with another instrument"
        >
          +CMP
        </button>

        {/* Compare input popover — floats below the toolbar button */}
        {showCompareInput && (
          <div className="absolute top-full left-0 z-20 mt-0.5 flex items-center gap-1 rounded-[2px] border border-border bg-card px-2 py-1 ">
            <input
              type="text"
              aria-label="Enter ticker to compare"
              placeholder="MSFT"
              autoFocus
              value={compareInput}
              onChange={(e) => onCompareInputChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onCompareSubmit();
                if (e.key === "Escape") onToggleCompareInput();
              }}
              className="h-5 w-20 rounded-[2px] border border-border bg-background px-1 font-mono text-[10px] text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
            />
            <button
              onClick={onCompareSubmit}
              className="h-5 rounded-[2px] bg-primary/20 px-2 font-mono text-[10px] text-primary hover:bg-primary/30"
            >
              Go
            </button>
          </div>
        )}
      </div>
    </>
  );
}
