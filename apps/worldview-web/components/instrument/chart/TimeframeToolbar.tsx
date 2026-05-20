/**
 * components/instrument/chart/TimeframeToolbar.tsx — Timeframe + log + compare controls
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
 * timeframe am I looking at, log mode, compare). The two have different conceptual
 * roles and different update frequencies — timeframe changes trigger API fetches,
 * overlay toggles are purely local visibility changes.
 *
 * WHO USES IT: components/instrument/OHLCVChart.tsx
 * PLAN REFERENCE: PLAN-0089 Wave D-1 (split OHLCVChart into chart/ subdirectory)
 */

// WHY no "use client": this is a pure presentation component — no hooks or browser
// APIs needed. The parent OHLCVChart (which is "use client") renders it.

import type { Timeframe } from "@/lib/chart-adapter";

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
}: TimeframeToolbarProps) {
  return (
    <>
      {/* Timeframe tabs — left side of toolbar */}
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

      {/* QA iter-1: 1px hairline separator marks the visual class break
          between timeframe selection (high-frequency) and view-mode
          toggles (low-frequency, e.g. log). */}
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
