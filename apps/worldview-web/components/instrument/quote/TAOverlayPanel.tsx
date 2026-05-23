/**
 * components/instrument/quote/TAOverlayPanel.tsx — TA indicator chip strip.
 *
 * WHY THIS EXISTS (PLAN-0091 Wave F-1):
 *   Institutional traders toggle indicator overlays constantly while reading
 *   price action — they need EMA/Bollinger/VWAP on/off without navigating
 *   menus. This chip strip gives one-click overlay toggling directly below
 *   the chart in the Quote tab.
 *
 * PLAN-0091 Wave F-2 — SENTI chip:
 *   Added chip 8 (SENTI) that overlays net_sentiment = positive_ratio −
 *   negative_ratio on the chart's right Y-axis. This lets analysts correlate
 *   news sentiment direction with price moves — a Bloomberg Intelligence staple.
 *   Data comes from `useEntitySentimentTimeseries` (lib/api/intelligence.ts) and
 *   is date-aligned against the OHLCV bar timestamps before rendering.
 *
 * WHO USES IT:
 *   - components/instrument/quote/QuoteTab.tsx (renders above the chart strips)
 *
 * DATA SOURCE:
 *   TA chips: no API calls — computes from bars[] via lib/ta/indicators.ts.
 *   SENTI chip: GET /v1/entities/{entityId}/sentiment-timeseries?days=90
 *               (only when entityId is provided AND SENTI chip is active).
 *
 * DESIGN REFERENCE: PLAN-0091 F-1/F-2 chip strip spec.
 *   - Chip strip: flex flex-wrap gap-1 px-2 py-1
 *   - Active chip: #0EA5E9 accent, 10px font-mono
 *   - Inactive chip: muted/20, hover: muted/40
 *   - SENTI disabled (no entityId): opacity-40 cursor-not-allowed
 *   - Colors follow Bloomberg terminal convention (sky=EMA, purple=EMA50, orange=SMA200)
 *
 * PERFORMANCE:
 *   useMemo recomputes TA arrays only when bars changes (new fetch). The memo
 *   dependency is the bars array reference; TanStack Query returns a stable
 *   reference for cached data so this runs at most once per timeframe fetch.
 *   Sentiment fetch is gated by `enabled: !!entityId && sentiActive` so it
 *   never fires until the user explicitly toggles the SENTI chip.
 */

"use client";

import { useEffect, useMemo, useState } from "react";
import { ema, sma, rsi, macd, bollingerBands, vwap } from "@/lib/ta/indicators";
// WHY import useEntitySentimentTimeseries here: the SENTI chip needs to fetch
// daily article-level sentiment aggregates from S9. This is the only hook that
// owns that cache slot; importing it here keeps all overlay data in one file.
import { useEntitySentimentTimeseries } from "@/lib/api/intelligence";
import type { OHLCVBar } from "@/types/api";
import type { OverlaySeries } from "@/components/instrument/chart/OHLCVChart";

// ── Chip definitions ─────────────────────────────────────────────────────────

/**
 * ChipId — stable string key identifying each TA chip.
 *
 * WHY a string union (not enum): consistent with IndicatorId in instrument-context.ts
 * and portable across JSX props without importing enum values.
 *
 * "senti" added in PLAN-0091 F-2: daily net sentiment overlay sourced from
 * the KG pipeline (article-level positive/negative ratios aggregated by S6).
 */
type ChipId =
  | "ema-20"
  | "ema-50"
  | "sma-200"
  | "macd"
  | "boll"
  | "rsi"
  | "vwap"
  | "senti";

/** Display label shown on each chip button. */
const CHIP_LABELS: Record<ChipId, string> = {
  "ema-20":  "EMA 20",
  "ema-50":  "EMA 50",
  "sma-200": "SMA 200",
  "macd":    "MACD",
  "boll":    "BOLL",
  "rsi":     "RSI",
  "vwap":    "VWAP",
  // WHY "SENTI": Bloomberg uses "SENT" for sentiment. We keep 5 chars for visual
  // parity with "VWAP" and readability at 10px mono font.
  "senti":   "SENTI",
};

/** Ordered chip display sequence (left → right in the strip). */
const CHIP_ORDER: ChipId[] = ["ema-20", "ema-50", "sma-200", "macd", "boll", "rsi", "vwap", "senti"];

// ── Props ────────────────────────────────────────────────────────────────────

export interface TAOverlayPanelProps {
  /**
   * OHLCV bars — the same array OHLCVChart uses. Passed in so TAOverlayPanel
   * can compute TA without a separate API call.
   *
   * WHY pass bars rather than fetching: bars are already in TanStack Query's
   * cache from OHLCVChart's own useQuery; reading them as props avoids a
   * duplicate network request and ensures TA is always computed on the same
   * bars that are rendered in the chart.
   */
  bars: OHLCVBar[];
  /**
   * Callback fired whenever the active chip set changes. The parent (QuoteTab)
   * should pass this directly to OHLCVChart as the `overlays` prop.
   */
  onOverlaysChange: (overlays: OverlaySeries[]) => void;
  /**
   * Entity UUID for the instrument — used to fetch sentiment timeseries.
   *
   * WHY optional / nullable: not every instrument in the system has a matching
   * KG entity. For example, ETFs, currencies, and newly-ingested tickers may
   * lack an entity record until S7 processes them. When null/undefined, the
   * SENTI chip renders in a visually disabled state (opacity-40, no-pointer)
   * and no sentiment fetch is attempted.
   *
   * Value flow: QuoteTab reads entityId from useInstrumentBrief().entity_id
   * which resolves asynchronously (undefined → string | null). The SENTI chip
   * guard (`enabled: !!entityId`) prevents any spurious API call during the
   * loading window.
   */
  entityId?: string | null;
}

// ── Overlay computation ───────────────────────────────────────────────────────

/**
 * computeOverlays — converts a set of active chip IDs and a bars array into
 * OverlaySeries objects ready for OHLCVChart.
 *
 * WHY a standalone function (not inlined in the hook): makes it independently
 * testable via TAOverlayPanel.test.tsx without mounting the component.
 *
 * Chip-to-overlay mapping (PLAN-0091 F-1 spec):
 *   ema-20  → EMA(20),   sky blue  (#0EA5E9), width 1
 *   ema-50  → EMA(50),   violet    (#8B5CF6), width 1
 *   sma-200 → SMA(200),  orange    (#F97316), width 1
 *   macd    → MACD line, teal      (#26A69A), width 1
 *   boll    → 3 series:  upper=#EF5350, middle=#FFB000, lower=#26A69A
 *   rsi     → RSI(14),   amber     (#FFB000), width 1
 *   vwap    → VWAP,      sky blue  (#0EA5E9), width 2 (thicker = emphasis)
 */
export function computeOverlays(active: Set<ChipId>, bars: OHLCVBar[]): OverlaySeries[] {
  const out: OverlaySeries[] = [];

  if (active.has("ema-20")) {
    out.push({ id: "ema-20", label: "EMA 20", data: ema(bars, 20), color: "#0EA5E9", axis: "left", strokeWidth: 1 });
  }

  if (active.has("ema-50")) {
    out.push({ id: "ema-50", label: "EMA 50", data: ema(bars, 50), color: "#8B5CF6", axis: "left", strokeWidth: 1 });
  }

  if (active.has("sma-200")) {
    out.push({ id: "sma-200", label: "SMA 200", data: sma(bars, 200), color: "#F97316", axis: "left", strokeWidth: 1 });
  }

  if (active.has("macd")) {
    // WHY only the MACD line (not signal/histogram): the chip strip is a
    // simplified one-click overlay, not the full indicator panel. Rendering
    // all three MACD components would require a separate sub-chart pane which
    // conflicts with the existing useChartSeries MACD pane (PLAN-0059 H-1).
    // The MACD *line* on the price scale gives directional signal without
    // the pane collision.
    const { macd: macdLine } = macd(bars);
    out.push({ id: "macd-line", label: "MACD", data: macdLine, color: "#26A69A", axis: "left", strokeWidth: 1 });
  }

  if (active.has("boll")) {
    const { upper, middle, lower } = bollingerBands(bars, 20, 2);
    out.push({ id: "boll-upper",  label: "BOLL Upper",  data: upper,  color: "#EF5350", axis: "left", strokeWidth: 1 });
    out.push({ id: "boll-mid",    label: "BOLL Middle", data: middle, color: "#FFB000", axis: "left", strokeWidth: 1 });
    out.push({ id: "boll-lower",  label: "BOLL Lower",  data: lower,  color: "#26A69A", axis: "left", strokeWidth: 1 });
  }

  if (active.has("rsi")) {
    // WHY RSI on axis "left": TAOverlayPanel's overlays share the main price
    // scale — we don't create a new oscillator pane here (that would conflict
    // with useChartSeries' dedicated RSI pane). Showing RSI as a price-scale
    // line gives quick trend visibility without pane layout complexity.
    out.push({ id: "rsi-14", label: "RSI 14", data: rsi(bars, 14), color: "#FFB000", axis: "left", strokeWidth: 1 });
  }

  if (active.has("vwap")) {
    // WHY strokeWidth 2: VWAP is the institutional reference line — it should
    // stand out visually from the thinner EMA/SMA lines.
    out.push({ id: "vwap-line", label: "VWAP", data: vwap(bars), color: "#0EA5E9", axis: "left", strokeWidth: 2 });
  }

  return out;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * TAOverlayPanel — chip strip for toggling TA overlays on the OHLCV chart.
 *
 * INTERACTION MODEL:
 *   1. User clicks an inactive chip → chip becomes active (highlighted sky-blue).
 *   2. computeOverlays() runs via useMemo → new OverlaySeries[] computed.
 *   3. onOverlaysChange() fires → QuoteTab forwards to OHLCVChart overlays prop.
 *   4. useChartSeries picks up the new overlays → adds/updates lightweight-charts series.
 *   5. User clicks an active chip → chip deactivates, overlay removed from chart.
 *   6. SENTI chip: disabled (no-op click, opacity-40) when entityId is null/undefined.
 *      When enabled and active, fires GET /v1/entities/{id}/sentiment-timeseries?days=90.
 *
 * WHY useMemo + useEffect:
 *   useMemo derives `overlays` from activeChips+bars synchronously (pure, instant).
 *   useEffect notifies the parent via onOverlaysChange after commit so we do not
 *   call parent setState during our own render (React forbids mid-render setState).
 *
 * WHY sentimentData participates in the memo dep via `sentiKey`:
 *   When the sentiment fetch resolves (data arrives), we must re-derive the overlay
 *   array. Including `sentiKey` (a string of sentimentData length or "none") in
 *   the chipsKey derivative ensures the memo fires when data changes.
 */
export function TAOverlayPanel({ bars, onOverlaysChange, entityId }: TAOverlayPanelProps) {
  // activeChips: which chips are currently toggled on.
  // WHY Set<ChipId> (not boolean[] or Record<ChipId, boolean>): Set membership
  // tests (has/add/delete) are O(1) and the spread into a new Set gives
  // React a stable identity check for the state update.
  const [activeChips, setActiveChips] = useState<Set<ChipId>>(new Set());

  // WHY track sentiActive separately: useEntitySentimentTimeseries needs to be
  // called at the TOP of the component (React rules of hooks — no conditional
  // hook calls). We pass `enabled` to disable the fetch when the chip is off.
  const sentiActive = activeChips.has("senti");

  // ── Sentiment timeseries fetch ──────────────────────────────────────────────
  //
  // WHY always call the hook (not inside an if): React hooks must be called in
  // the same order on every render — conditional hook calls break the rules of
  // hooks and cause runtime errors. Instead we control when the actual network
  // request fires via the `enabled` option inside useEntitySentimentTimeseries:
  //   enabled = !!entityId && !!token && sentiActive
  // When disabled, the hook returns { data: undefined } without fetching.
  //
  // WHY 90 days: covers ~3 months of trading days, giving enough history to
  // see sentiment trends alongside the default 1D timeframe OHLCV bars.
  const { data: sentimentData } = useEntitySentimentTimeseries(
    // WHY pass null explicitly when inactive: the hook's `enabled` guard
    // checks `!!entityId` — passing null prevents any spurious fetch even
    // if sentiActive briefly becomes true before entityId resolves.
    sentiActive ? (entityId ?? null) : null,
    90,
  );

  // ── Date-aligned sentiment values ──────────────────────────────────────────
  //
  // Sentiment points have "YYYY-MM-DD" dates; OHLCV bars have ISO-8601 UTC
  // timestamps. We align by extracting the date prefix from each bar's
  // timestamp (first 10 chars: "2026-01-15") and looking up the matching
  // sentiment point in a pre-built Map for O(1) per bar.
  //
  // WHY NaN for missing dates: lightweight-charts skips NaN values (renders
  // a visual gap), which is correct — if no articles were processed on a
  // given trading day, we have no sentiment signal to display.
  const sentimentAligned: number[] = useMemo(() => {
    // Only run alignment when the chip is active and data is available.
    // WHY check both sentiActive and sentimentData: sentiActive can be true
    // before the fetch resolves, and sentimentData can be stale from a previous
    // entityId if the parent switches instruments. Both conditions must be met.
    if (!sentiActive || !sentimentData?.points?.length) return [];

    // Build a date → net_sentiment lookup map.
    // WHY Map (not array.find per bar): O(n) build + O(1) lookup vs O(n²) with
    // array.find in a loop over potentially 250 bars × 90 sentiment points.
    const sentimentByDate = new Map<string, number>(
      sentimentData.points.map((pt) => [
        pt.date, // already "YYYY-MM-DD"
        // WHY positive_ratio − negative_ratio: this is the "net" signal in [-1, +1].
        // 1.0 = 100% positive articles on that day; -1.0 = 100% negative; 0 = neutral.
        // Neutral (0) means equal positive/negative or no sentiment signals.
        pt.positive_ratio - pt.negative_ratio,
      ]),
    );

    // For each OHLCV bar, extract the date and look up net_sentiment.
    // WHY substring(0, 10): bar.timestamp is ISO-8601 UTC like "2026-01-15T00:00:00Z";
    // slicing the first 10 chars gives "2026-01-15" which matches pt.date exactly.
    return bars.map((bar) => {
      const date = bar.timestamp.substring(0, 10);
      // NaN = no sentiment data for this trading day → lightweight-charts renders a gap
      return sentimentByDate.get(date) ?? NaN;
    });
    // WHY include sentimentData?.points?.length in dep: when the async fetch resolves,
    // the reference changes and memo re-runs to build the aligned array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sentiActive, sentimentData, bars]);

  // Computed overlays — recomputed only when bars, activeChips, or sentimentAligned changes.
  // WHY stringify for memo dep: Set is compared by reference (new Set() !== new Set())
  // but its contents change on each toggle. Serialising the sorted ids to a string
  // gives a value-based dependency that avoids stale closures while still memoising.
  //
  // WHY include sentimentAligned.length in chipsKey: sentimentAligned is a new array
  // reference each time the fetch resolves. Without a sentinel, useMemo wouldn't
  // refire when sentiment data arrives after the chip was toggled. Using the length
  // (0 while loading, N once resolved) is a lightweight stable proxy for "data arrived".
  const chipsKey = `${Array.from(activeChips).sort().join(",")};senti:${sentimentAligned.length}`;
  const overlays = useMemo(() => {
    // Compute the standard TA overlays (ema-20 through vwap).
    const ta = computeOverlays(activeChips, bars);

    // ── SENTI overlay (F-2) ────────────────────────────────────────────────
    // WHY check sentimentAligned.length (not just sentiActive):
    //   sentiActive becomes true immediately on click; sentimentAligned is []
    //   until the async fetch resolves. Checking length prevents us from adding
    //   a SENTI series with empty data[] which lightweight-charts would render
    //   as a flat empty series (confusing, looks like a bug).
    if (sentiActive && sentimentAligned.length > 0) {
      ta.push({
        id: "senti",
        label: "Sentiment",
        data: sentimentAligned,
        color: "#0EA5E9", // sky blue — same as EMA 20 but on the right axis, so no conflict
        // WHY axis "right": sentiment lives in [-1, +1], not in price space.
        // Binding to the right Y-axis gives it its own scale so the line isn't
        // crushed to a flat band when prices are in the hundreds.
        axis: "right",
        strokeWidth: 1.5,
      });
    }

    return ta;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chipsKey, bars, sentiActive, sentimentAligned]);

  // WHY useEffect for the parent callback (not inline in useMemo):
  //   useMemo runs during render — calling onOverlaysChange there would fire a
  //   parent setState mid-render, which React disallows. useEffect fires after
  //   the commit phase (DOM is updated), which is the correct time to notify
  //   the parent and let it update OHLCVChart's overlays prop.
  useEffect(() => {
    onOverlaysChange(overlays);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlays]);

  /** Toggle a chip's active state and recompute overlays. */
  function handleChipClick(id: ChipId) {
    // WHY guard SENTI here (not in JSX onClick only): the JSX `disabled` prop
    // prevents mouse clicks but not programmatic calls in tests. This guard
    // ensures the chip is truly inert when entityId is missing.
    if (id === "senti" && !entityId) return;

    setActiveChips((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id); // deactivate
      } else {
        next.add(id);    // activate
      }
      return next;
    });
  }

  return (
    // WHY border-b border-border/20: a thin hairline rule separates the chip
    // strip from the chart above it, matching the 1px grid language used
    // throughout the Quote tab (ChartToolbar, SessionStatsStrip).
    <div
      className="flex flex-wrap gap-1 px-2 py-1 border-b border-border/20 shrink-0"
      data-testid="ta-overlay-panel"
      role="toolbar"
      aria-label="Technical indicator overlays"
    >
      {CHIP_ORDER.map((id) => {
        const isActive = activeChips.has(id);

        // WHY a separate disabled state for SENTI: the chip must still render
        // in the strip so users know the feature exists, but interacting with
        // it would be a no-op (no entityId → no sentiment data). Visual cue:
        // opacity-40 (grayed-out) + cursor-not-allowed + aria-disabled.
        const isDisabled = id === "senti" && !entityId;

        return (
          <button
            key={id}
            type="button"
            onClick={() => handleChipClick(id)}
            aria-pressed={isDisabled ? false : isActive}
            aria-label={`Toggle ${CHIP_LABELS[id]} overlay`}
            aria-disabled={isDisabled}
            // WHY disabled prop on button: prevents keyboard activation (Space/Enter)
            // in addition to mouse clicks. Combined with aria-disabled it gives
            // full accessible indication that the chip is unavailable.
            disabled={isDisabled}
            // WHY text-[10px]: matches the data-table-grid font size used in
            // SessionStatsStrip and IntradayStatsBand (institutional density).
            // WHY tabular-nums: chip labels contain numerals (EMA 20, SMA 200);
            // tabular-nums prevents layout shift when numbers change width.
            className={
              isDisabled
                // Disabled SENTI: grayed-out to signal "no entity linked"
                ? "bg-muted/20 text-muted-foreground text-[10px] font-mono tabular-nums px-2 py-0.5 rounded border border-muted/20 opacity-40 cursor-not-allowed transition-colors"
                : isActive
                  ? "bg-[#0EA5E9]/20 text-[#0EA5E9] text-[10px] font-mono tabular-nums px-2 py-0.5 rounded cursor-pointer border border-[#0EA5E9]/30 transition-colors"
                  : "bg-muted/20 text-muted-foreground text-[10px] font-mono tabular-nums px-2 py-0.5 rounded cursor-pointer border border-muted/20 hover:border-muted/40 transition-colors"
            }
          >
            {CHIP_LABELS[id]}
          </button>
        );
      })}
    </div>
  );
}
