/**
 * components/instrument/quote/QuoteTab.tsx — Quote tab orchestrator
 *
 * WHY THIS EXISTS (PRD-0088 §6.7): the Quote tab is the trader's first
 * impression — chart on the left (dominant), statistics rail on the right.
 * This orchestrator owns ONLY layout wiring — no data fetching, no domain
 * logic. Children own their own queries via TanStack Query.
 *
 * ── WAVE-2 LAYOUT REBUILD (2026-06-10) ───────────────────────────────────────
 * Replaces the PLAN-0099 W4 layout that carried two "backend endpoint
 * pending" placeholder rows and a 2/3-placeholder bottom strip. New stack:
 *
 *   ┌────────────────────────────────────────────┬──────────────┐
 *   │ OHLCVChart (flex-1 — all remaining height) │ STATISTICS   │
 *   ├────────────────────────────────────────────┤ rail (380px, │
 *   │ KeyStatsBar          (22px)                │ scrolls,     │
 *   │ IntradayStatsStrip   (22px — B-Q-2 live)   │ sectioned)   │
 *   │ ReturnsStrip         (22px — B-Q-3 live)   │ + Company    │
 *   ├──────────────┬──────────────┬──────────────┤   About card │
 *   │ PeersTable   │ PriceLevels  │ What's Moving│   below it   │
 *   │ (B-Q-1 live) │ (B-Q-4 live) │ (bundle news)│              │
 *   └──────────────┴──────────────┴──────────────┘──────────────┘
 *
 * KEY DECISIONS:
 *   - SessionStatsStrip (last-chart-bar O/H/L/V) is REPLACED by
 *     IntradayStatsStrip: the dedicated endpoint is strictly richer
 *     (prev-close, real VWAP + source, volume-vs-30d ratio) and decouples
 *     session stats from whichever bar resolution the chart happens to show.
 *   - CompanyAboutCard moved from the left column to the BOTTOM OF THE RIGHT
 *     RAIL: the rail scrolls anyway, and reclaiming its 110px gives the chart
 *     ~25% more height at 1440×900 — chart + rail stay above the fold.
 *   - BottomTripleStrip (placeholder orchestrator) is gone; the bottom row is
 *     composed inline here — it is pure layout, three cells, no logic.
 *
 * WHY THE ORCHESTRATOR IS THIN: children are independently testable, and
 * re-renders in one cell cannot force a re-render of the others (each child
 * subscribes to its own query).
 *
 * DESIGN REFERENCE: docs/specs/0088-instrument-detail-page-ground-up-redesign.md
 * §6.7; Wave-2 quote-tab redesign 2026-06-10.
 */

"use client";
// WHY "use client": children are client components (charts, query hooks);
// keeping the orchestrator client-side keeps the boundary in one place.

import { OHLCVChart } from "@/components/instrument/chart/OHLCVChart";
import { KeyStatsBar } from "@/components/instrument/quote/stats/KeyStatsBar";
import { IntradayStatsStrip } from "@/components/instrument/quote/strips/IntradayStatsStrip";
import { ReturnsStrip } from "@/components/instrument/quote/strips/ReturnsStrip";
import { PeersTable } from "@/components/instrument/quote/strips/PeersTable";
import { PriceLevelsPanel } from "@/components/instrument/quote/strips/PriceLevelsPanel";
import { WhatsMovingStrip } from "@/components/instrument/quote/bottom/WhatsMovingStrip";
import { MetricsTable } from "@/components/instrument/quote/metrics/MetricsTable";
import { CompanyAboutCard } from "@/components/instrument/quote/about/CompanyAboutCard";
import type { Fundamentals, Instrument, OHLCVBar, Quote, InstrumentPageBundle } from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────
//
// WHY these props specifically:
//   - `instrumentId`: S3 instrument_id — cache key for chart + strips + rail.
//   - `entityId`: KG entity_id — reserved for cross-tab deep-links.
//   - `fundamentals`/`quote`: slim page-bundle legs for first-paint seeds.
//   - `initialBars`: seed bars for OHLCVChart first paint (skips skeleton).
//   - `bundle`: the full page bundle — top_news + overview.instrument with
//     zero extra fetches.

export interface QuoteTabProps {
  /** S3 instrument_id — shared cache key for chart + strips + metrics. */
  readonly instrumentId: string;
  /** KG entity_id — reserved for cross-tab deep-links. */
  readonly entityId: string;
  /** Page-bundle fundamentals header (first-paint seed for the rail). */
  readonly fundamentals: Fundamentals | null;
  /** Latest quote snapshot from page-bundle. */
  readonly quote: Quote | null;
  /** Last 30d 1D bars from the page-bundle, used to skip the chart skeleton. */
  readonly initialBars?: OHLCVBar[];
  /** Full page bundle — top_news + overview.instrument extraction. */
  readonly bundle?: InstrumentPageBundle | null;
}

export function QuoteTab({
  instrumentId,
  // entityId is currently consumed only for prop-compat with the page shell;
  // kept in the contract because cross-tab deep-links (Wave-3) need it and
  // removing/re-adding a prop churns every call site and test twice.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  entityId: _entityId,
  fundamentals,
  quote,
  initialBars,
  bundle,
}: QuoteTabProps) {
  // Instrument profile for CompanyAboutCard — from bundle.overview.instrument.
  // WHY separate from `fundamentals`: the Instrument type carries the profile
  // fields (sector/industry/country/description); fundamentals carries metrics.
  const instrument: Instrument | null = bundle?.overview?.instrument ?? null;

  // Top news for the What's Moving cell — already in the bundle, zero fetches.
  const topNews = bundle?.top_news ?? null;

  return (
    // WHY `grid grid-cols-[1fr_380px]`: left column takes all remaining width;
    // the right rail is fixed 380px (matches MetricsTable's natural density).
    // WHY `h-full overflow-hidden`: fills the tab pane; each column owns its
    // own scroll container so neither can scroll the page.
    <div className="grid grid-cols-[1fr_380px] h-full overflow-hidden">

      {/* ── LEFT column: chart + strips ─────────────────────────────────────
       * `min-w-0` prevents the flex item exceeding its grid cell (flex items
       * default to min-width:auto); `overflow-hidden` clips overshoot. */}
      <div className="flex flex-col min-w-0 overflow-hidden">
        {/* Chart: flex-1 — every pixel not claimed by the fixed strips below.
            This is the page's centrepiece; post pane-rebuild it renders the
            price pane across the full slot with a volume overlay. */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <OHLCVChart instrumentId={instrumentId} initialBars={initialBars} />
        </div>

        {/* Key stats (22px): MKT CAP / P/E / EPS / DIV YLD / BETA — passive
            cache subscriptions + bundle seeds, zero extra fetches. */}
        <KeyStatsBar
          instrumentId={instrumentId}
          fundamentals={fundamentals}
          snapshot={bundle?.fundamentals_snapshot ?? null}
        />

        {/* Session stats (22px): O/H/L/PREV/VWAP/VOL/vs-30D from the dedicated
            intraday-stats endpoint (replaces the last-chart-bar strip). */}
        <IntradayStatsStrip instrumentId={instrumentId} />

        {/* Multi-period returns (22px): 1D…5Y colour-coded ribbon. */}
        <ReturnsStrip instrumentId={instrumentId} />

        {/* ── Bottom strip: peers / price levels / what's moving ────────────
         * WHY h-[168px]: 20px header + 8 × ~16px peer rows + padding — the
         * spec's 8-row peers budget sets the row height for all 3 cells.
         * WHY grid-cols-[1.3fr_1fr_1fr]: the peers table carries 6 columns,
         * the other two cells are compact — give peers the extra width. */}
        <div className="grid grid-cols-[1.3fr_1fr_1fr] h-[168px] border-t border-border overflow-hidden flex-shrink-0">
          <div className="border-r border-border overflow-hidden">
            <PeersTable instrumentId={instrumentId} />
          </div>
          <div className="border-r border-border overflow-hidden">
            <PriceLevelsPanel instrumentId={instrumentId} />
          </div>
          <div className="overflow-hidden">
            <WhatsMovingStrip data={topNews} />
          </div>
        </div>
      </div>

      {/* ── RIGHT rail: 380px statistics + company profile ──────────────────
       * The rail owns ONE scroll container for both children — the metrics
       * sections and the about card scroll together as a single column.
       * WHY the about card lives here now: see the module doc (reclaims
       * 110px of chart height while keeping the profile one scroll away). */}
      <div className="flex flex-col border-l border-border overflow-y-auto">
        <MetricsTable
          instrumentId={instrumentId}
          fundamentals={fundamentals}
          quote={quote}
        />
        <CompanyAboutCard instrument={instrument} />
      </div>
    </div>
  );
}
