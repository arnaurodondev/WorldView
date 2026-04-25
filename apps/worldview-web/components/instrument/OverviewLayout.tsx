/**
 * components/instrument/OverviewLayout.tsx — 5-zone instrument overview layout
 *
 * WHY THIS EXISTS: Replaces the old ad-hoc overview layout (OHLCVChart | EntityGraphPanel
 * in a 2-column grid) with a structured 5-zone layout:
 *   1. OHLCVChart (full width) — price chart with built-in timeframe selector
 *   2. SessionStatsStrip (full width, 20px) — O/H/L/V/VWAP from last bar
 *   3. 3-column lower grid: KeyMetrics | TopNews | EntityGraph
 *
 * WHY KEEP OHLCV FULL WIDTH: The chart is the primary analysis surface. A full-width
 * chart gives analysts the maximum horizontal canvas for pattern recognition.
 *
 * WHY 3-COLUMN LOWER GRID (3fr:3fr:4fr): The entity graph (zone 3) needs slightly
 * more width for the SVG radial layout to be legible. Key metrics and news are
 * purely textual so they share equal width.
 *
 * WHY SessionStatsStrip BETWEEN chart and lower grid: The strip at 20px is the
 * Bloomberg convention — O/H/L/V appears immediately below the chart canvas, not
 * in a separate panel. It is part of the chart visual, not a data section.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Overview tab content)
 * DATA SOURCE: Props from CompanyOverview + child components fetch their own data
 * DESIGN REFERENCE: PRD-0031 §9 OverviewLayout, Wave 5
 */

// WHY no top-level "use client": OHLCVChart, SessionStatsStrip, EntityGraphPanel
// and InstrumentTopNews are all already "use client" — this parent is a pure
// composition shell. The parent page.tsx is "use client" already.

import { OHLCVChart } from "@/components/instrument/OHLCVChart";
import { SessionStatsStrip } from "@/components/instrument/SessionStatsStrip";
import { InstrumentKeyMetrics } from "@/components/instrument/InstrumentKeyMetrics";
import { InstrumentTopNews } from "@/components/instrument/InstrumentTopNews";
import { EntityGraphPanel } from "@/components/instrument/EntityGraphPanel";
import type { OHLCVBar, Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewLayoutProps {
  instrumentId: string;
  entityId: string;
  centerLabel: string;         // ticker for graph center node label
  initialBars?: OHLCVBar[];    // from CompanyOverview for initial chart render
  fundamentals: Fundamentals | null;
  onViewAllNews: () => void;   // callback to switch parent to News tab
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OverviewLayout({
  instrumentId,
  entityId,
  centerLabel,
  initialBars,
  fundamentals,
  onViewAllNews,
}: OverviewLayoutProps) {
  // Derive SessionStatsStrip props from the last OHLCV bar.
  // WHY last bar: the most recent bar represents the current/last session's OHLCV.
  // WHY optional chaining: initialBars may be undefined (no CompanyOverview data yet).
  const lastBar = initialBars?.[initialBars.length - 1] ?? null;

  return (
    <div className="flex flex-col min-h-0">

      {/* ── Zone 1: Price chart (full width) ─────────────────────────────── */}
      {/* WHY no padding: OHLCVChart fills its container edge-to-edge.
          The chart controls provide their own internal padding. */}
      <OHLCVChart
        instrumentId={instrumentId}
        initialBars={initialBars}
      />

      {/* ── Zone 2: Session stats strip (full width, 20px) ───────────────── */}
      {/* WHY between chart and lower grid: Bloomberg convention places O/H/L/V
          immediately below the chart canvas, not in a separate section. */}
      <SessionStatsStrip
        open={lastBar?.open ?? null}
        high={lastBar?.high ?? null}
        low={lastBar?.low ?? null}
        volume={lastBar?.volume ?? null}
      />

      {/* ── Zone 3-4-5: 3-column lower grid ─────────────────────────────── */}
      {/* WHY grid-cols-[3fr_3fr_4fr]: entity graph (right) needs more width
          for the SVG radial layout to be legible. Key metrics and news are
          textual so they share equal width (3fr each). */}
      {/* WHY border-t: visually separates the stats strip from the lower grid */}
      <div className="grid grid-cols-[3fr_3fr_4fr] min-h-0 border-t border-border">

        {/* Zone 3: Key Metrics panel (left column) */}
        {/* WHY border-r: hairline separator between columns */}
        <div className="border-r border-border">
          <InstrumentKeyMetrics fundamentals={fundamentals} />
        </div>

        {/* Zone 4: Top News panel (center column) */}
        <div className="border-r border-border">
          <InstrumentTopNews
            entityId={entityId}
            onViewAll={onViewAllNews}
          />
        </div>

        {/* Zone 5: Entity Graph panel (right column) */}
        {/* WHY last:border-0 not needed (no border-r on last column):
            the parent grid container provides the outer right border. */}
        <div>
          <EntityGraphPanel
            entityId={entityId}
            centerLabel={centerLabel}
          />
        </div>
      </div>
    </div>
  );
}
