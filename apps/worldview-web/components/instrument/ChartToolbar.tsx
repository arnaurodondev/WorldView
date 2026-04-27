/**
 * components/instrument/ChartToolbar.tsx — OHLCV chart overlay controls
 *
 * WHY THIS EXISTS: Institutional traders need one-click access to common chart
 * overlays. Bloomberg and TradingView both show a toolbar above the chart with
 * toggles for volume bars, moving averages, and display modes. Adding/removing
 * these overlays without a toolbar would require props on every parent, making
 * the chart component harder to use from outside.
 *
 * WHY PARENT-CONTROLLED STATE (not internal): OHLCVChart owns the chart instance
 * and series refs — it must apply visibility changes directly to lightweight-charts
 * series objects. If ChartToolbar owned the state, it would need to call into
 * OHLCVChart via ref or context. Lifting state to OHLCVChart keeps the data flow
 * simple: state lives with the chart, toolbar just reflects and toggles it.
 *
 * WHY SEPARATE COMPONENT (not inline in OHLCVChart): ChartToolbar is ~60 lines of
 * pure UI (no chart logic). Extracting it keeps OHLCVChart focused on charting.
 * The toolbar can also be tested in isolation without a chart instance.
 *
 * WHO USES IT: OHLCVChart (PLAN-0041 Wave C-2)
 * DESIGN REFERENCE: PLAN-0041 §T-C-2-01, TradingView toolbar UX
 */

// WHY no "use client": ChartToolbar is a pure presentation component — it receives
// all state and callbacks via props. No hooks or browser APIs needed.

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ChartToolbarProps {
  /** Whether volume histogram is currently visible */
  showVolume: boolean;
  onToggleVolume: () => void;
  /** Whether MA50 line overlay is visible */
  showMA50: boolean;
  onToggleMA50: () => void;
  /** Whether MA200 line overlay is visible */
  showMA200: boolean;
  onToggleMA200: () => void;
  /** Whether the chart is in fullscreen mode */
  isFullscreen: boolean;
  onFullscreen: () => void;
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * ToolbarButton — pill-shaped toggle button with active/inactive states.
 *
 * WHY bg-primary/20 text-primary for active: matches the timeframe selector
 * active state in OHLCVChart for visual consistency across the toolbar row.
 */
function ToolbarButton({
  active,
  onClick,
  children,
  title,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`rounded-[2px] px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
        active
          ? "bg-primary/20 text-primary"
          : "text-muted-foreground hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ChartToolbar({
  showVolume,
  onToggleVolume,
  showMA50,
  onToggleMA50,
  showMA200,
  onToggleMA200,
  isFullscreen,
  onFullscreen,
}: ChartToolbarProps) {
  return (
    // WHY ml-auto: toolbar aligns to the right of the row; timeframe tabs own the left side
    <div className="ml-auto flex items-center gap-0.5">

      {/* Volume histogram toggle */}
      {/* WHY "VOL" label (not an icon): avoids SVG import weight for a 10px label.
          Text labels are also more accessible — screen readers announce "VOL" clearly. */}
      <ToolbarButton
        active={showVolume}
        onClick={onToggleVolume}
        title="Toggle volume histogram"
      >
        VOL
      </ToolbarButton>

      {/* MA50 line overlay toggle */}
      {/* WHY gold color indicator in the label: gives the user a preview of what the
          MA50 line looks like before enabling it — same color as the actual series. */}
      <ToolbarButton
        active={showMA50}
        onClick={onToggleMA50}
        title="Toggle 50-day moving average"
      >
        <span className="text-[10px]">MA<span className="text-primary">50</span></span>
      </ToolbarButton>

      {/* MA200 line overlay toggle */}
      <ToolbarButton
        active={showMA200}
        onClick={onToggleMA200}
        title="Toggle 200-day moving average"
      >
        {/* WHY text-sky-500: MA200 line color — matches lightweight-charts config */}
        <span className="text-[10px]">MA<span className="text-sky-500">200</span></span>
      </ToolbarButton>

      {/* Fullscreen toggle — rightmost, separated by larger gap */}
      {/* WHY ⛶/⊡ glyphs: Unicode chart control glyphs are zero-dep and recognisable.
          Using SVG here would add complexity for a single-character affordance. */}
      <button
        onClick={onFullscreen}
        title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        className="ml-1 rounded-[2px] px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
      >
        {isFullscreen ? "⊡" : "⛶"}
      </button>
    </div>
  );
}
