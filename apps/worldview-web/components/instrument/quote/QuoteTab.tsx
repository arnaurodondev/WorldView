/**
 * components/instrument/quote/QuoteTab.tsx — Quote tab orchestrator (PLAN-0090 T-B-04).
 *
 * WHY THIS EXISTS (PRD-0088 §6.7 / PLAN-0090 T-B-04):
 *   The Instrument Detail redesign replaces the legacy `OverviewLayout` blob
 *   with a 3-tab structure (Quote / Financials / Intelligence). The Quote tab
 *   is the trader's first impression: chart on the left (flex-1), fixed-width
 *   metrics table on the right (380px). This orchestrator owns ONLY the layout
 *   wiring — no data fetching, no domain logic. Children own their own
 *   queries via TanStack Query (chart fetches OHLCV; MetricsTable uses
 *   `useMetricsTableData`).
 *
 * PLAN-0099 W4 LAYOUT CHANGE:
 *   Old layout: flex-row, 60% chart / 40% metrics.
 *   New layout: CSS grid 2-col [1fr 380px]:
 *     - Left column: flex-col with chart (flex-1) + session strip (22px) +
 *       2 placeholder strips (22px each) + CompanyAboutCard (110px) +
 *       BottomTripleStrip (132px).
 *     - Right column: 380px fixed, overflow-y-auto MetricsTable.
 *   entityId is now active (underscore prefix removed) for cross-tab nav.
 *
 * WHY THE ORCHESTRATOR IS THIN:
 *   - Children are independently testable (chart, strip, metrics each have
 *     their own props/hooks).
 *   - Re-renders in one half cannot force a re-render of the other half
 *     (React reconciliation stops at the grid boundary because each child
 *     subscribes to its own query).
 *   - The 380px right-rail width is a single source of truth here — future
 *     A/B experiments can flip widths without touching children.
 *
 * LINE LIMIT: orchestrator exemption per PRD §FR-7 — soft cap 200, hard cap
 *   300. Targeting < 250.
 *
 * DESIGN REFERENCE: docs/specs/0088-instrument-detail-page-ground-up-redesign.md §6.7;
 *                   docs/plans/0090-instrument-detail-page-redesign-plan.md T-B-04.
 *                   PLAN-0099 W4 layout spec.
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
import { CompanyAboutCard } from "@/components/instrument/quote/about/CompanyAboutCard";
import { BottomTripleStrip } from "@/components/instrument/quote/bottom/BottomTripleStrip";
import type { Fundamentals, Instrument, OHLCVBar, OHLCVResponse, Quote, InstrumentPageBundle } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────
//
// WHY these props specifically:
//   - `instrumentId`: S3 instrument_id — cache key for chart + metrics.
//   - `entityId`: KG entity_id — now active (Wave D). Used for CompanyAboutCard
//     and BottomTripleStrip so they can deep-link to the Intelligence tab.
//   - `fundamentals`: static rows (market cap, beta, etc.) for MetricsTable.
//   - `quote`: live quote snapshot for MetricsTable header row.
//   - `initialBars`: seed bars for OHLCVChart first-paint (avoids skeleton flash).
//   - `bundle`: the full page bundle — gives us top_news + overview.instrument
//     for CompanyAboutCard and BottomTripleStrip with zero extra fetches.

export interface QuoteTabProps {
  /** S3 instrument_id — shared cache key for chart + metrics. */
  readonly instrumentId: string;
  /** KG entity_id — active in Wave D (cross-tab deep-links + about card). */
  readonly entityId: string;
  /** Page-bundle fundamentals header (null → MetricsTable renders "—" rows). */
  readonly fundamentals: Fundamentals | null;
  /** Latest quote snapshot from page-bundle. */
  readonly quote: Quote | null;
  /** Last 30d 1D bars from the page-bundle, used to skip the chart skeleton. */
  readonly initialBars?: OHLCVBar[];
  /**
   * Full page bundle — used to extract top_news (WhatsMovingStrip) and
   * overview.instrument (CompanyAboutCard). Optional so existing tests that
   * don't construct a full bundle still compile.
   */
  readonly bundle?: InstrumentPageBundle | null;
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
  entityId,    // Wave D: underscore prefix removed — now actively used.
  fundamentals,
  quote,
  initialBars,
  bundle,
}: QuoteTabProps) {
  // ── Read last OHLCV bar from cache for SessionStatsStrip ───────────────
  // WHY `enabled: false`: we never want this hook to issue a network request.
  // It is a passive subscriber. OHLCVChart owns the active fetch and (Round-1
  // fix) now keys it through the SAME qk.instruments.ohlcv factory — the old
  // ad-hoc ["ohlcv", ...] key meant this subscription never matched and the
  // strip silently never upgraded past the bundle's seed bars.
  // NOTE: the chart fills this "1D" slot whenever a daily-bar period is
  // active (1M/3M/1Y). For intraday periods (1D/1W) the chart writes the
  // "5M"/"1H" slots instead — the strip then falls back to `initialBars`
  // below, whose last bar is still today's daily candle (correct session
  // O/H/L/V semantics; a 5-minute candle would NOT be).
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

  // Instrument for CompanyAboutCard — extracted from bundle.overview.instrument.
  // WHY separate from `fundamentals`: the Instrument type carries the profile
  // fields (sector/industry/country/description) that the about card needs.
  // The `fundamentals` prop carries financial metrics for MetricsTable, not profile.
  const instrument: Instrument | null = bundle?.overview?.instrument ?? null;

  // Top news for BottomTripleStrip/WhatsMovingStrip.
  // WHY from bundle: the page-bundle already includes top_news (limit=5).
  // No extra fetch needed — zero-cost data.
  const topNews = bundle?.top_news ?? null;

  return (
    // WHY `grid grid-cols-[1fr_380px]`: 2-column CSS grid.
    //   - Left column gets all remaining horizontal space (1fr).
    //   - Right column is a fixed 380px — matches the MetricsTable's natural
    //     density and prevents it from compressing on wide viewports.
    // WHY `h-full overflow-hidden`: fills the tab pane and clips content;
    //   each column owns its own scroll container so neither can scroll the page.
    <div className="grid grid-cols-[1fr_380px] h-full overflow-hidden">

      {/* ── LEFT column: chart stack ──────────────────────────────────────
       * WHY `flex flex-col min-w-0 overflow-hidden`: stacks all left-column
       * children vertically. `min-w-0` prevents the flex item from exceeding
       * its grid cell on narrow viewports (flex items default to min-width:auto).
       * `overflow-hidden` clips any child that extends past the column edge.
       */}
      <div className="flex flex-col min-w-0 overflow-hidden">
        {/* Chart: flex-1 so it fills all vertical space not claimed by the strips. */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <OHLCVChart instrumentId={instrumentId} initialBars={initialBars} />
        </div>

        {/* Session stats strip: 22px, shows today's O/H/L/V from chart cache. */}
        <SessionStatsStrip {...stripProps} />

        {/* Multi-Period Returns placeholder: B-Q-3 backend endpoint pending.
            WHY inline div (not extracted component): a placeholder this small
            doesn't warrant its own file. Extracted once B-Q-3 lands. */}
        <div className="h-[22px] flex items-center px-3 border-t border-border/30 text-[10px] text-muted-foreground/50 font-mono flex-shrink-0">
          RETURNS · Backend endpoint pending (B-Q-3)
        </div>

        {/* Intraday Stats placeholder: B-Q-2 backend endpoint pending. */}
        <div className="h-[22px] flex items-center px-3 border-t border-border/30 text-[10px] text-muted-foreground/50 font-mono flex-shrink-0">
          INTRADAY STATS · Backend endpoint pending (B-Q-2)
        </div>

        {/* Company About card: sector/industry/HQ/description, 110px tall. */}
        <div className="flex-shrink-0">
          <CompanyAboutCard instrument={instrument} />
        </div>

        {/* Bottom triple strip: peers / price-levels / what's-moving, 132px tall. */}
        <div className="flex-shrink-0">
          <BottomTripleStrip
            instrumentId={instrumentId}
            entityId={entityId}
            topNews={topNews}
          />
        </div>
      </div>

      {/* ── RIGHT column: 380px metrics rail ──────────────────────────────
       * WHY `flex-shrink-0 border-l border-border overflow-y-auto`:
       *   - `flex-shrink-0`: the grid cell is already fixed at 380px; the inner
       *     div must not shrink further when content overflows.
       *   - `border-l border-border`: 1px separator between chart and metrics.
       *   - `overflow-y-auto`: metrics table exceeds viewport height on small
       *     screens — the right column owns its scroll bar independently.
       */}
      <div className="flex-shrink-0 border-l border-border overflow-y-auto">
        <MetricsTable
          instrumentId={instrumentId}
          fundamentals={fundamentals}
          quote={quote}
        />
      </div>
    </div>
  );
}
