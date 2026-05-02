/**
 * features/dashboard/lib/movers.ts — Pure ranking + filtering logic for the
 * Watchlist Movers widget (PLAN-0059 E-5).
 *
 * WHY THIS EXISTS: WatchlistMoversWidget held ~80 LOC of inline useMemo blocks
 * doing period-aware row building + sector filtering + abs(%) ranking + 5/5
 * partition. Inlining made the math untestable in isolation — any change
 * required mounting the entire widget with a mocked TanStack Query client.
 * Pulling them out into pure functions lets us drive them with hand-built
 * fixtures and assert against the resulting arrays without rendering.
 *
 * SCOPE: imported by `components/dashboard/WatchlistMoversWidget.tsx` and any
 * future per-watchlist drill-down panel that needs the same ranking rules.
 */

import type { WatchlistMoverEnriched } from "@/types/api";
import type { OHLCVResponse } from "@/types/api";
import { matchesSectorFilter, ALL_SECTORS_VALUE } from "@/lib/sectors";

// ── Types ─────────────────────────────────────────────────────────────────

/**
 * Period selector — same set as PreMarketMoversWidget so users have a
 * consistent mental model: 1D = today's session (live), 1W = trailing 7
 * trading days, 1M = trailing ~21 trading days.
 */
export type WatchlistPeriod = "1D" | "1W" | "1M";

/**
 * WatchlistMover — display shape for one row in the gainers/losers columns.
 *
 * For 1D: every field comes straight from the insights composite endpoint.
 * For 1W/1M: change_pct (and price) is overridden from the per-instrument
 * OHLCV first→last close; sector/news/alerts stay from insights so the
 * badges remain consistent across periods.
 */
export interface WatchlistMover {
  instrumentId: string;
  ticker: string;
  name: string;
  sector: string | null;
  // For 1D: latest live price. For 1W/1M: latest close from OHLCV.
  price: number | null;
  // Percentage change over the selected period (already in percent units,
  // e.g. 2.34 not 0.0234). May be null while we are still loading the
  // backing data for that row.
  changePct: number | null;
  newsCount24h: number;
  hasActiveAlert: boolean;
  topNewsTitle: string | null;
  topNewsUrl: string | null;
}

// ── Builders ──────────────────────────────────────────────────────────────

/**
 * buildMoverRows — combine the insights envelope with the per-instrument
 * OHLCV results into a uniform `WatchlistMover[]` the renderer can consume
 * without branching on period.
 *
 * Behaviour pinned by tests:
 *  - 1D path: returns rows unchanged from insights (price, change_pct,
 *    sector, news, alerts all flow through)
 *  - 1W/1M path: overrides price + changePct from the OHLCV bars; falls
 *    back to {price: null, changePct: null} when bars.length < 2
 *  - "Bad cost basis" guard: when `bars[0].close <= 0` the change_pct is
 *    nulled (avoids division by zero) but `price` still resolves to the
 *    last close so the trader sees the latest mark.
 *
 * The OHLCV array MUST be parallel to the insights array (same length,
 * same order) — the widget's useQueries call enforces this.
 */
export function buildMoverRows(
  enriched: readonly WatchlistMoverEnriched[],
  period: WatchlistPeriod,
  ohlcvByIndex: ReadonlyArray<OHLCVResponse | undefined>,
): WatchlistMover[] {
  return enriched.map((em, idx) => {
    const base: WatchlistMover = {
      instrumentId: em.instrument_id,
      ticker: em.ticker,
      name: em.name,
      sector: em.sector,
      price: em.price,
      changePct: em.change_pct,
      newsCount24h: em.news_count_24h,
      hasActiveAlert: em.has_active_alert,
      topNewsTitle: em.top_news_title,
      topNewsUrl: em.top_news_url,
    };
    if (period === "1D") return base;

    // 1W / 1M: override price + change_pct from OHLCV first→last close.
    const bars = ohlcvByIndex[idx]?.bars ?? [];
    if (bars.length < 2) return { ...base, price: null, changePct: null };
    const first = bars[0]!.close;
    const last = bars[bars.length - 1]!.close;
    if (first <= 0) return { ...base, price: last, changePct: null };
    return {
      ...base,
      price: last,
      changePct: ((last - first) / first) * 100,
    };
  });
}

/**
 * applySectorFilter — filter mover rows by selected sector pill.
 *
 * WHY graceful "still loading" behaviour: rows with `sector === null` are
 * KEPT visible while their sector overview is in flight. Without this guard
 * the user would see the list shrink on every refetch. Once the per-row
 * overview resolves the row either matches or drops out.
 */
export function applySectorFilter(
  rows: readonly WatchlistMover[],
  selectedSector: string,
): WatchlistMover[] {
  if (selectedSector === ALL_SECTORS_VALUE) return [...rows];
  return rows.filter((m) => {
    if (m.sector == null) return true; // sector lookup not loaded yet
    return matchesSectorFilter(m.sector, selectedSector);
  });
}

/**
 * rankByAbsChangePct — sort descending by |change_pct|.
 *
 * Spec: "biggest absolute movers" — a sector full of -4% losers is more
 * interesting to surface than a flat +0.1% gainer. Sorting by abs first then
 * partitioning ensures the top-5 of each side are the most extreme moves.
 *
 * Rows with `changePct == null` sort to the bottom (treated as -1 absolute).
 */
export function rankByAbsChangePct(
  rows: readonly WatchlistMover[],
): WatchlistMover[] {
  return [...rows].sort((a, b) => {
    const aa = a.changePct == null ? -1 : Math.abs(a.changePct);
    const bb = b.changePct == null ? -1 : Math.abs(b.changePct);
    return bb - aa;
  });
}

/**
 * splitGainersLosers — partition the (already-ranked) rows into the top-5
 * gainers and top-5 losers columns.
 *
 * WHY 5 each side: at col-span-5 (~520px) with h-7 (28px) rows the widget
 * fits 5+5 = 10 rows in Row 2's height budget without scrolling.
 *
 * WHY null-changePct rows are dropped: they have no side to belong to —
 * the renderer can't colour them or place them. The ranking step keeps
 * them at the bottom; this step removes them entirely from both columns.
 */
export function splitGainersLosers(
  ranked: readonly WatchlistMover[],
  topN = 5,
): { gainers: WatchlistMover[]; losers: WatchlistMover[] } {
  const gainers = ranked
    .filter((m) => m.changePct != null && m.changePct > 0)
    .slice(0, topN);
  const losers = ranked
    .filter((m) => m.changePct != null && m.changePct < 0)
    .slice(0, topN);
  return { gainers, losers };
}

/**
 * pickFirstWatchlistByCreatedAt — deterministic "default watchlist" picker.
 *
 * WHY first-by-created_at: the spec ("PLAN-0047 Wave A: pick first watchlist
 * by created_at OR a 'default' concept if it exists") — there is no explicit
 * `is_default` flag on the Watchlist type today, so we fall back to the
 * oldest one. That maps to "the watchlist I made first" which for >90% of
 * users is their main / default list.
 *
 * Falls back to ISO-string compare when one of the timestamps fails to
 * parse (shouldn't happen with API responses but defends against malformed
 * fixtures).
 */
export function pickFirstWatchlistByCreatedAt<
  T extends { created_at: string },
>(watchlists: readonly T[] | undefined): T | null {
  if (!watchlists || watchlists.length === 0) return null;
  const sorted = [...watchlists].sort((a, b) => {
    const ta = Date.parse(a.created_at);
    const tb = Date.parse(b.created_at);
    if (!Number.isNaN(ta) && !Number.isNaN(tb)) return ta - tb;
    return a.created_at.localeCompare(b.created_at);
  });
  return sorted[0] ?? null;
}
