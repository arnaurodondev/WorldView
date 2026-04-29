/**
 * components/instrument/ChartToolbar.tsx — OHLCV chart overlay controls
 *
 * WHY THIS EXISTS: Institutional traders need one-click access to common chart
 * overlays and technical indicators. Bloomberg and TradingView both show a toolbar
 * above the chart. Adding/removing overlays without a toolbar would require props
 * on every parent, making the chart component harder to use from outside.
 *
 * WHY PARENT-CONTROLLED STATE (not internal): OHLCVChart owns the chart instance
 * and series refs — it must apply visibility changes directly to lightweight-charts
 * series objects. If ChartToolbar owned the state, it would need to call into
 * OHLCVChart via ref or context. Lifting state to OHLCVChart keeps the data flow
 * simple: state lives with the chart, toolbar just reflects and toggles it.
 *
 * WHY SEPARATE COMPONENT (not inline in OHLCVChart): ChartToolbar is pure UI (no
 * chart logic). Extracting it keeps OHLCVChart focused on charting and makes the
 * toolbar testable in isolation.
 *
 * WAVE C ADDITIONS (PLAN-0050 T-C-3-01, T-C-3-03):
 *   - Indicators dropdown: RSI, MACD, Bollinger Bands, ATR, Stochastic, OBV, VWAP
 *     backed by lightweight-charts LineSeries / HistogramSeries per-indicator.
 *   - Volume submenu: Base Volume toggle + Vol MA20 + Volume Profile + VWAP Line.
 *     Each is an individually-toggleable series.
 *
 * WHO USES IT: OHLCVChart (PLAN-0041 Wave C-2)
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-01, TradingView toolbar UX
 */

// WHY no "use client": ChartToolbar is a pure presentation component — it receives
// all state and callbacks via props. No hooks or browser APIs needed.

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { IndicatorId, IndicatorConfig } from "@/lib/instrument-context";

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ChartToolbarProps {
  // ── Original controls (preserved from Wave C-2) ───────────────────────────
  /** Whether the base volume histogram is currently visible */
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

  // ── Wave C: Indicators dropdown (T-C-3-01) ────────────────────────────────
  /**
   * Map of indicator ID → config. Owned by OHLCVChart.
   * ChartToolbar reads `enabled` to show checkbox state.
   */
  indicators: Record<IndicatorId, IndicatorConfig>;
  /**
   * Callback when user toggles an indicator. OHLCVChart updates the indicators
   * map and triggers the appropriate series to show/hide.
   */
  onToggleIndicator: (id: IndicatorId) => void;

  // ── Wave C: Volume submenu (T-C-3-03) ────────────────────────────────────
  /** Whether the Volume MA20 line is visible on the volume scale */
  showVolMA20: boolean;
  onToggleVolMA20: () => void;
  /** Whether the Volume Profile right-side histogram is visible */
  showVolProfile: boolean;
  onToggleVolProfile: () => void;
  /** Whether the VWAP anchored-daily line is visible on the price scale */
  showVWAPLine: boolean;
  onToggleVWAPLine: () => void;
}

// ── Indicator metadata ────────────────────────────────────────────────────────

/**
 * INDICATOR_META — display labels for each indicator ID.
 *
 * WHY separate from IndicatorConfig: the metadata (label, description) is a
 * UI concern — it doesn't need to be persisted or passed through the chart API.
 * Keeping it here co-located with the toolbar avoids importing UI strings into
 * lib/instrument-context.ts (which is a pure-logic module).
 */
const INDICATOR_META: Record<IndicatorId, { label: string; description: string }> = {
  RSI:        { label: "RSI",              description: "Relative Strength Index (14)" },
  MACD:       { label: "MACD",             description: "MACD (12, 26, 9)" },
  BOLLINGER:  { label: "BB",               description: "Bollinger Bands (20, 2σ)" },
  ATR:        { label: "ATR",              description: "Average True Range (14)" },
  STOCHASTIC: { label: "STOCH",            description: "Stochastic Oscillator (14, 3, 3)" },
  OBV:        { label: "OBV",              description: "On-Balance Volume" },
  VWAP:       { label: "VWAP",             description: "Volume Weighted Avg Price" },
  // Volume sub-indicators — shown in the VOL submenu, not the Indicators dropdown
  VOL_MA20:   { label: "Vol MA20",         description: "Volume 20-period Moving Average" },
  VOL_PROFILE:{ label: "Vol Profile",      description: "Volume Profile (price distribution)" },
  VWAP_LINE:  { label: "VWAP Line",        description: "Anchored VWAP on price scale" },
};

/**
 * MAIN_INDICATORS — the indicator IDs shown in the Indicators dropdown.
 * Volume sub-indicators are in the VOL submenu, not here.
 */
const MAIN_INDICATORS: IndicatorId[] = [
  "RSI", "MACD", "BOLLINGER", "ATR", "STOCHASTIC", "OBV", "VWAP",
];

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
  "data-testid": dataTestId,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title?: string;
  "data-testid"?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      data-testid={dataTestId}
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
  indicators,
  onToggleIndicator,
  showVolMA20,
  onToggleVolMA20,
  showVolProfile,
  onToggleVolProfile,
  showVWAPLine,
  onToggleVWAPLine,
}: ChartToolbarProps) {

  // Count how many main indicators are active — used in the "Indicators" button
  // label to give immediate feedback (e.g., "IND 3" when 3 indicators are on).
  // WHY badge on the trigger (not a tooltip): analysts want to know at a glance
  // how many overlays are active without opening the dropdown.
  const activeIndicatorCount = MAIN_INDICATORS.filter(
    (id) => indicators[id].enabled,
  ).length;

  // Count active volume sub-indicators for the VOL dropdown label
  const activeVolCount = [showVolume, showVolMA20, showVolProfile, showVWAPLine].filter(Boolean).length;

  return (
    // WHY ml-auto: toolbar aligns to the right of the row; timeframe tabs own the left side
    <div className="ml-auto flex items-center gap-0.5" data-testid="chart-toolbar">

      {/* ── MA overlays ─────────────────────────────────────────────────────── */}

      {/* MA50 line overlay toggle */}
      {/* WHY color indicator in the label: gives the user a preview of what the
          MA50 line looks like before enabling it — same color as the actual series. */}
      <ToolbarButton
        active={showMA50}
        onClick={onToggleMA50}
        title="Toggle 50-day moving average"
        data-testid="toolbar-ma50"
      >
        <span className="text-[10px]">MA<span className="text-primary">50</span></span>
      </ToolbarButton>

      {/* MA200 line overlay toggle */}
      <ToolbarButton
        active={showMA200}
        onClick={onToggleMA200}
        title="Toggle 200-day moving average"
        data-testid="toolbar-ma200"
      >
        {/* WHY text-sky-500: MA200 line color — matches lightweight-charts config */}
        <span className="text-[10px]">MA<span className="text-sky-500">200</span></span>
      </ToolbarButton>

      {/* ── Volume submenu (T-C-3-03) ───────────────────────────────────────── */}
      {/* WHY a DropdownMenu for volume (not just a toggle): volume now has 4 sub-
          options (Base, MA20, Profile, VWAP Line). A flat toolbar with 4 VOL-related
          buttons would look cluttered at terminal density. The dropdown keeps the
          row width under control while exposing all options on demand.
          WHY Radix DropdownMenu via shadcn: matches the Indicators dropdown's
          interaction pattern — keyboard navigable, portal-based (z-index safe),
          consistent with the rest of the shadcn/ui usage in this file. */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            data-testid="toolbar-volume-menu"
            className={`rounded-[2px] px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
              activeVolCount > 0
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
            title="Volume sub-indicators"
          >
            {/* WHY show count: instantly shows how many volume overlays are on */}
            VOL{activeVolCount > 0 ? ` ${activeVolCount}` : ""}
          </button>
        </DropdownMenuTrigger>

        {/* WHY align="end": dropdown opens flush-right with the trigger button
            so it doesn't overflow the left edge of the toolbar area */}
        <DropdownMenuContent align="end" className="w-48">
          <DropdownMenuLabel className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Volume Overlays
          </DropdownMenuLabel>
          <DropdownMenuSeparator />

          {/* Base Volume histogram */}
          {/* WHY this is the first item: base volume is the primary volume display.
              The sub-indicators (MA20, Profile, VWAP) are enhancements to it. */}
          <DropdownMenuCheckboxItem
            checked={showVolume}
            onCheckedChange={onToggleVolume}
            data-testid="vol-base"
          >
            <span className="text-[11px]">Base Volume</span>
          </DropdownMenuCheckboxItem>

          {/* Volume MA20 — smooth line over the histogram bars */}
          <DropdownMenuCheckboxItem
            checked={showVolMA20}
            onCheckedChange={onToggleVolMA20}
            data-testid="vol-ma20"
          >
            <span className="text-[11px]">Volume MA20</span>
          </DropdownMenuCheckboxItem>

          {/* Volume Profile — right-side horizontal histogram */}
          {/* WHY "right-side": unlike other series, Volume Profile renders as
              a sideways histogram anchored to the right price scale — it shows
              which price levels had the most trading activity over the visible range. */}
          <DropdownMenuCheckboxItem
            checked={showVolProfile}
            onCheckedChange={onToggleVolProfile}
            data-testid="vol-profile"
          >
            <span className="text-[11px]">Volume Profile</span>
          </DropdownMenuCheckboxItem>

          {/* VWAP Line — anchored daily VWAP on main price scale */}
          {/* WHY in VOL menu (not Indicators): VWAP is volume-derived. Placing it
              in the volume submenu groups it logically with volume-based overlays. */}
          <DropdownMenuCheckboxItem
            checked={showVWAPLine}
            onCheckedChange={onToggleVWAPLine}
            data-testid="vol-vwap"
          >
            <span className="text-[11px]">VWAP Line</span>
          </DropdownMenuCheckboxItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* ── Indicators dropdown (T-C-3-01) ──────────────────────────────────── */}
      {/* WHY a dropdown (not individual toggles): 7 indicators × ~25px per button
          would be 175px of toolbar width — more than the timeframe tabs. At terminal
          density, a compact "IND N" trigger button is much better UX. Bloomberg
          uses a similar collapsed indicator panel approach. */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            data-testid="toolbar-indicators-menu"
            className={`rounded-[2px] px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
              activeIndicatorCount > 0
                ? "bg-primary/20 text-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
            title="Technical indicators"
          >
            {/* WHY "IND N" label (not "Studies"): "IND" is more Bloomberg-like.
                The count badge is the key affordance — analysts see at a glance
                how many indicators are active without opening the menu. */}
            IND{activeIndicatorCount > 0 ? ` ${activeIndicatorCount}` : ""}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuLabel className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Technical Indicators
          </DropdownMenuLabel>
          <DropdownMenuSeparator />

          {/* Map over the main indicators — each gets a checkbox item */}
          {/* WHY DropdownMenuCheckboxItem: shadcn's CheckboxItem renders a
              Radix-managed checkbox with keyboard support (Space to toggle) and
              correct ARIA roles. We don't need to manage focus state ourselves. */}
          {MAIN_INDICATORS.map((id) => (
            <DropdownMenuCheckboxItem
              key={id}
              checked={indicators[id].enabled}
              onCheckedChange={() => onToggleIndicator(id)}
              data-testid={`indicator-${id.toLowerCase()}`}
            >
              {/* WHY flex layout: left column = short label (RSI, MACD), right
                  column = description (Relative Strength Index (14)). The mono
                  label gives Bloomberg-style data density; the description aids
                  new users who don't know the abbreviation. */}
              <span className="flex items-baseline gap-2">
                <span className="w-10 font-mono text-[10px] text-primary">
                  {INDICATOR_META[id].label}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {INDICATOR_META[id].description}
                </span>
              </span>
            </DropdownMenuCheckboxItem>
          ))}

          <DropdownMenuSeparator />
          {/* WHY hint text: oscillator indicators (RSI, MACD, ATR, STOCH) render
              in a sub-pane below the main chart. Price-scale indicators (BB, OBV,
              VWAP) overlay the main chart. Users need to know this distinction. */}
          <div className="px-2 py-1 text-[9px] text-muted-foreground/70">
            Oscillators render in a sub-pane below the chart.
          </div>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* ── Fullscreen toggle — rightmost ────────────────────────────────────── */}
      {/* WHY ⛶/⊡ glyphs: Unicode chart control glyphs are zero-dep and recognisable.
          Using SVG here would add complexity for a single-character affordance. */}
      <button
        onClick={onFullscreen}
        title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        className="ml-1 rounded-[2px] px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        data-testid="toolbar-fullscreen"
      >
        {isFullscreen ? "⊡" : "⛶"}
      </button>
    </div>
  );
}
