/**
 * components/instrument/quote/QuoteTab.tsx — Quote tab orchestrator (PLAN-0090 T-B-04).
 *
 * WHY THIS EXISTS (PRD-0088 §6.7 / PLAN-0090 T-B-04):
 *   The Instrument Detail redesign replaces the legacy `OverviewLayout` blob
 *   with a 3-tab structure (Quote / Financials / Intelligence). The Quote tab
 *   is the trader's first impression: chart on the left, Finviz-density
 *   metrics + strips on the right (320px lg / 380px xl fixed rail). This
 *   orchestrator owns ONLY the layout wiring — no data fetching, no domain
 *   logic. Children own their own queries via TanStack Query (chart fetches
 *   OHLCV; MetricsTable uses `useMetricsTableData`).
 *
 * W5-T-06 layout pivot: root changed from `flex` to CSS Grid with a fixed
 *   right-rail width (320px/380px) replacing the former 40% flex share. This
 *   enables the Bloomberg-grade right-rail density target (Δ31, Δ34).
 *
 * WHY THE ORCHESTRATOR IS THIN:
 *   - Children are independently testable (chart, strip, metrics each have
 *     their own props/hooks).
 *   - Re-renders in one half cannot force a re-render of the other half
 *     (React reconciliation stops at the flex boundary because each child
 *     subscribes to its own query).
 *   - The 60/40 split is a single source of truth in this file — future
 *     A/B experiments can flip widths without touching children.
 *
 * WHY SessionStatsStrip pulls O/H/L/V/VWAP from cache HERE (not inside the
 *   strip itself): the integrated `SessionStatsStrip` from T-B-01 is a pure
 *   display component (props-only, no `useQuery`). To honour PLAN-0090's
 *   "strip reads from cache" pattern WITHOUT duplicating its data contract,
 *   the orchestrator does the cache lookup and feeds the last-bar O/H/L/V
 *   in as props. The lookup uses `enabled: false` so we never trigger a
 *   network fetch — we only read whatever OHLCVChart has already cached
 *   under `qk.instruments.ohlcv(instrumentId, "1D")`.
 *
 * LINE LIMIT: orchestrator exemption per PRD §FR-7 — soft cap 200, hard cap
 *   300. Targeting < 200.
 *
 * DESIGN REFERENCE: docs/specs/0088-instrument-detail-page-ground-up-redesign.md §6.7;
 *                   docs/plans/0090-instrument-detail-page-redesign-plan.md T-B-04.
 */

"use client";
// WHY "use client": we call `useQuery` from TanStack Query to peek into the
// client-side cache for the last OHLCV bar. That hook only works in the
// browser. The chart and metrics components are also client components, so
// promoting this orchestrator to "use client" keeps the boundary clean.

import { useQuery } from "@tanstack/react-query";

import { qk } from "@/lib/query/keys";
import { OHLCVChart } from "@/components/instrument/chart/OHLCVChart";
import { SessionStatsStrip } from "@/components/instrument/SessionStatsStrip";
import { MetricsTable } from "@/components/instrument/quote/metrics/MetricsTable";
import type { Fundamentals, OHLCVBar, OHLCVResponse, Quote } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────
//
// WHY these four props specifically:
//   - `instrumentId`: the S3 instrument_id is the cache key shared by all
//     four data sources (chart, snapshot, technicals, share-stats).
//   - `entityId`: reserved for Wave D deep-links (e.g. "Open in Intelligence"
//     CTA). Not used today; kept so the parent doesn't need a refactor when
//     we wire the cross-tab navigation in PLAN-0090 Wave D.
//   - `fundamentals` + `quote`: passed through from the page-bundle so
//     MetricsTable can render the static rows (market cap, beta, etc.) on
//     first paint without awaiting its own queries — those queries still
//     fire to refresh the technicals / share-stats rows after mount.
//   - `initialBars`: lets OHLCVChart show the last 30d 1D bars instantly on
//     first paint (from the page-bundle seed), avoiding the chart skeleton
//     flash for the common case.

export interface QuoteTabProps {
  /** S3 instrument_id — shared cache key for chart + metrics. */
  readonly instrumentId: string;
  /** KG entity_id — reserved for cross-tab deep-links (Wave D). */
  readonly entityId: string;
  /** Page-bundle fundamentals header (null → MetricsTable renders "—" rows). */
  readonly fundamentals: Fundamentals | null;
  /** Latest quote snapshot from page-bundle. */
  readonly quote: Quote | null;
  /** Last 30d 1D bars from the page-bundle, used to skip the chart skeleton. */
  readonly initialBars?: OHLCVBar[];
}

// ── Constants ────────────────────────────────────────────────────────────────
//
// WHY hard-code "1D": SessionStatsStrip only renders the CURRENT SESSION's
// stats, which by definition come from the 1D timeframe's last bar. Higher
// timeframes (1W/1M) would aggregate multiple sessions and mis-label the
// strip. If the user switches OHLCVChart to a different timeframe, that's
// fine — the chart owns its own state; the strip below stays anchored to
// today's session.

const STRIP_TIMEFRAME = "1D" as const;

// ── Component ────────────────────────────────────────────────────────────────

export function QuoteTab({
  instrumentId,
  entityId: _entityId, // Reserved for Wave D; underscore-prefix avoids lint warn.
  fundamentals,
  quote,
  initialBars,
}: QuoteTabProps) {
  // ── Read last OHLCV bar from cache for SessionStatsStrip ───────────────
  // WHY `enabled: false`: we never want this hook to issue a network request.
  // It is a passive subscriber. OHLCVChart owns the active fetch under the
  // same queryKey, so whatever it has loaded (initialBars first, then a
  // freshened fetch) is what we read here. The strip therefore always
  // reflects the chart's freshest data without duplicating the fetch.
  //
  // WHY fall back to `initialBars`: on the very first render before the
  // chart has hydrated the query cache, `cachedOhlcv` is undefined. The
  // page-bundle's `initialBars` is the only source available — using it
  // avoids a "—" flash on every page load for the common case.
  const { data: cachedOhlcv } = useQuery<OHLCVResponse>({
    queryKey: qk.instruments.ohlcv(instrumentId, STRIP_TIMEFRAME),
    enabled: false,
  });

  // Prefer the cached bars (live), then fall back to bundle-seeded bars.
  // WHY array-tail access (not findLast): bars are timestamp-ascending per
  // the S9 OHLCVResponse contract — the last index is the most recent bar.
  const bars: readonly OHLCVBar[] = cachedOhlcv?.bars ?? initialBars ?? [];
  const lastBar = bars.length > 0 ? bars[bars.length - 1] : null;

  // WHY narrow to `lastBar?.x ?? null`: SessionStatsStrip's prop contract
  // is `number | null` (not undefined). Coercing here keeps the strip's
  // type surface clean and avoids defensive checks inside the strip.
  const stripProps = {
    open: lastBar?.open ?? null,
    high: lastBar?.high ?? null,
    low: lastBar?.low ?? null,
    volume: lastBar?.volume ?? null,
    // VWAP is intentionally omitted: the OHLCVBar shape (timestamp/o/h/l/c/v)
    // does not include VWAP — only intraday feeds expose it. The strip's
    // `vwap` prop is optional, so leaving it off hides the column cleanly.
  };

  return (
    // WHY CSS Grid (not flex) — W5-T-06 layout pivot (Δ31):
    //   - `grid-cols-[minmax(0,1fr)_320px]`: left column takes remaining space
    //     (chart+strips); right column is fixed 320px on lg, 380px on xl.
    //     minmax(0,1fr) is the ONLY correct way to make a grid column shrink
    //     below its content width — plain `1fr` still respects min-content.
    //   - `xl:grid-cols-[minmax(0,1fr)_380px]`: wider right rail at 1280px+
    //     per Δ30 (380px breakpoint with 8px padding each side = 364px usable).
    //   - `p-0`: no outer inset — each panel owns its own padding (Δ41).
    //     Previously the legacy flex root had no padding either, so this is a
    //     no-op for existing children; it makes the contract explicit so future
    //     panels don't accidentally add double-padding.
    //   - `h-full overflow-hidden`: fill the tab slot without scrolling the
    //     grid container itself (each column owns its scroll independently).
    <div className="grid grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_380px] h-full overflow-hidden p-0">
      {/* ── LEFT: chart + session stats ────────────────────────────────────
       * WHY `flex flex-col min-w-0`: inner flex column stacks the chart on
       * top of the 22px session strip. `min-w-0` is still needed inside a
       * grid cell because grid cells also default to `min-width: auto`.
       */}
      <div className="flex flex-col min-w-0">
        {/* Chart fills remaining vertical space inside the left column. */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <OHLCVChart instrumentId={instrumentId} initialBars={initialBars} />
        </div>
        {/* Session O/H/L/V strip below the chart — 22px tall, fixed. */}
        <SessionStatsStrip {...stripProps} />
      </div>

      {/* ── RIGHT: metrics table ───────────────────────────────────────────
       * WHY `border-l border-border`: 1px vertical hairline rule between the
       * two grid columns. `border-border` matches the F1 design system token
       * for column dividers (not `border-border/30` which F1 deprecated).
       *
       * WHY `overflow-y-auto`: the metrics table exceeds viewport height on
       * 1080p laptops. The right column scrolls independently so the chart
       * + strips stay locked while the user scrolls metrics.
       */}
      <div className="border-l border-border overflow-y-auto">
        <MetricsTable
          instrumentId={instrumentId}
          fundamentals={fundamentals}
          quote={quote}
        />
      </div>
    </div>
  );
}
