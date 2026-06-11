/**
 * features/portfolio/lib/sector-stats.ts — PURE sector-level statistics
 * derived from the server sector-breakdown + live holdings/quotes.
 * (2026-06-10 sprint, Wave 2 portfolio surface.)
 *
 * WHY THIS EXISTS: the upgraded Sector Exposure panel shows, per sector,
 * the portfolio weight (server-computed) AND the day's P&L for that sector
 * (live, client-computed: Σ quote.change × qty over the segment's
 * instruments). The join is by exact instrument ID — the sector-breakdown
 * segments now carry `instrument_ids` (2026-06-10 sprint gap #2), so no
 * name aliasing is involved here at all.
 *
 * BENCHMARK GAP (flagged honestly): no S9 endpoint exposes SPY/benchmark
 * sector weights today, so a portfolio-vs-SPY weight comparison cannot be
 * rendered from real data. The panel shows weight + day-change instead and
 * carries a one-line caption naming the gap. NEVER fabricate benchmark
 * weights from a hardcoded table — index compositions drift quarterly.
 *
 * DESIGN RULES: pure functions, null over fake numbers (a sector whose
 * segment has no instrument_ids — old S9 build — gets dayChangeValue=null,
 * rendered as "—").
 *
 * WHO USES IT: SectorExposurePanel (Holdings overview) and its tests.
 */

import type { Holding, SectorBreakdownSegment } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Minimal quote shape needed for day-change math (subset of Quote). */
export interface SectorQuote {
  change: number | null | undefined;
}

/** One row of the Sector Exposure panel. */
export interface SectorStatRow {
  /** Sector label as the server emitted it (EODHD taxonomy). */
  sector: string;
  /** Portfolio weight fraction [0,1] — straight from the server segment. */
  weight: number;
  /** Number of holdings in the sector (server-side count). */
  count: number;
  /** Sector market value in portfolio currency (server-side). */
  marketValue: number;
  /**
   * Today's P&L for the sector in $: Σ quote.change × holding.quantity over
   * the segment's instrument_ids. null when the segment carries no
   * instrument_ids (older S9 build) or NO quote in the set has a change yet
   * — "we don't know" must render as "—", never $0.00.
   */
  dayChangeValue: number | null;
  /**
   * Day change as a fraction of the sector's yesterday-close value
   * (dayChange / (marketValue − dayChange)). null when dayChangeValue is
   * null or the base is non-positive (degenerate; avoids ±Infinity).
   */
  dayChangePct: number | null;
}

// ── Computation ───────────────────────────────────────────────────────────────

/**
 * computeSectorStats — join server segments with live quotes by exact ID.
 *
 * @param segments  sector-breakdown segments (already sorted largest-first
 *                  by the server — order is preserved)
 * @param holdings  current holdings (for per-instrument quantity)
 * @param quotes    live quotes keyed by instrument_id
 */
export function computeSectorStats(
  segments: readonly SectorBreakdownSegment[],
  holdings: readonly Holding[],
  quotes: Record<string, SectorQuote>,
): SectorStatRow[] {
  // O(1) quantity lookup — segments reference holdings by instrument_id.
  const qtyById = new Map<string, number>();
  for (const h of holdings) qtyById.set(h.instrument_id, h.quantity);

  return segments.map((seg) => {
    let dayChange = 0;
    let seen = false; // distinguishes "no data" from a genuine $0.00 flat day

    for (const id of seg.instrument_ids ?? []) {
      const change = quotes[id]?.change;
      const qty = qtyById.get(id);
      // Both sides must be real: a quote without a change (pre-open) or an
      // ID with no holding row (sold today, stale cache) contributes nothing
      // — and does NOT flip `seen`, so an all-unknown sector stays null.
      if (change != null && qty != null) {
        dayChange += change * qty;
        seen = true;
      }
    }

    const dayChangeValue = seen ? dayChange : null;
    // Yesterday's close base = today's value − today's change. Guard the
    // denominator: a brand-new position whose entire value IS today's change
    // would otherwise divide by ≤0 and show a nonsense percentage.
    const base = seg.market_value - (dayChangeValue ?? 0);
    const dayChangePct =
      dayChangeValue != null && base > 0 ? dayChangeValue / base : null;

    return {
      sector: seg.sector,
      weight: seg.weight,
      count: seg.count,
      marketValue: seg.market_value,
      dayChangeValue,
      dayChangePct,
    };
  });
}

/**
 * sectorIdMapFromSegments — sector label → instrument_ids lookup used by the
 * donut-driven holdings filter (exact-ID matching, sprint gap #2).
 *
 * Segments without instrument_ids are simply absent from the map — the
 * filter falls back to the legacy alias matching for those labels.
 */
export function sectorIdMapFromSegments(
  segments: readonly SectorBreakdownSegment[] | undefined,
): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const seg of segments ?? []) {
    if (seg.instrument_ids && seg.instrument_ids.length > 0) {
      map[seg.sector] = seg.instrument_ids;
    }
  }
  return map;
}
