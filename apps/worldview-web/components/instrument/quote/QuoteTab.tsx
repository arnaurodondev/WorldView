/**
 * components/instrument/quote/QuoteTab.tsx — Quote tab orchestrator (W5-T-25)
 *
 * WHY THIS EXISTS (PRD-0088 §6.7 / PLAN-0090 T-B-04):
 *   The Instrument Detail redesign gives traders a Bloomberg-grade Quote tab:
 *   chart + strips on the left (minmax(0,1fr)); right rail 320px/380px fixed.
 *   This orchestrator owns ONLY the layout wiring — no domain logic.
 *
 * W5-T-06 layout pivot: root changed from `flex` to CSS Grid with fixed
 *   right-rail width (320px/380px). This is the T-25 full wiring pass that
 *   adds all new W5 components into the two grid columns.
 *
 * LEFT COLUMN (chart side):
 *   1. OHLCVChart                  — OHLCV candlestick + toolbars
 *   2. MultiPeriodReturnsStrip     — 7-period return band (data-table-grid)
 *   3. IntradayStatsBand           — VWAP/ATR/RSI/GAP/PREM/SI (data-table-grid)
 *   4. SessionStatsStrip           — O/H/L/V from last 1D bar
 *
 * RIGHT COLUMN (scrollable rail):
 *   1. MetricsTable                — 24-cell grid + 52W + ownership + MA + analyst
 *   2. CompanyAboutCard            — sector/industry/HQ/founded/description
 *   3. InsiderActivityList         — top-5 insider transactions (from bundle)
 *   4. EarningsMiniList            — last-4 annual EPS records
 *   5. RelatedHeadlinesList        — top-5 entity-tagged news
 *   6. BottomTripleStrip           — Peers | PriceLevels | WhatsMoving
 *
 * DATA WIRING:
 *   - useQuoteSidebarData: peers, intradayStats, multiPeriodReturns, priceLevels,
 *     ownership, earningsHistory (6 parallel TanStack Query calls).
 *   - Strips (left) and mini-cards (right) receive data + isLoading via props.
 *   - SessionStatsStrip reads from OHLCV cache (enabled:false, no extra fetch).
 *   - Bundle fields (insider, top_news, instrument, fundamentals) passed as props.
 *
 * ORCHESTRATOR EXEMPTION: soft cap 200 LOC, hard cap 300 per PRD §FR-7.
 */

"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { qk } from "@/lib/query/keys";
import { OHLCVChart } from "@/components/instrument/chart/OHLCVChart";
import { SessionStatsStrip } from "@/components/instrument/SessionStatsStrip";
import { MetricsTable } from "@/components/instrument/quote/metrics/MetricsTable";
import { MultiPeriodReturnsStrip } from "@/components/instrument/quote/strips/MultiPeriodReturnsStrip";
import { IntradayStatsBand } from "@/components/instrument/quote/strips/IntradayStatsBand";
import { CompanyAboutCard } from "@/components/instrument/quote/about/CompanyAboutCard";
import { InsiderActivityList } from "@/components/instrument/quote/insider/InsiderActivityList";
import { EarningsMiniList } from "@/components/instrument/quote/earnings/EarningsMiniList";
import { RelatedHeadlinesList } from "@/components/instrument/quote/news/RelatedHeadlinesList";
import { BottomTripleStrip } from "@/components/instrument/quote/bottom/BottomTripleStrip";
import { useQuoteSidebarData } from "@/components/instrument/hooks/useQuoteSidebarData";
import type {
  Fundamentals,
  Instrument,
  OHLCVBar,
  OHLCVResponse,
  Quote,
  FundamentalsSectionResponse,
  RankedNewsResponse,
} from "@/types/api";

// ── Props ────────────────────────────────────────────────────────────────────

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
  /** Page-bundle Instrument (for CompanyAboutCard). */
  readonly instrument?: Instrument | null;
  /** Page-bundle insider transactions (for InsiderActivityList). */
  readonly insiderData?: FundamentalsSectionResponse | null;
  /** Page-bundle top news (for RelatedHeadlinesList + WhatsMovingStrip). */
  readonly topNews?: RankedNewsResponse | null;
}

// ── Constants ────────────────────────────────────────────────────────────────

// WHY hard-code "1D": SessionStatsStrip shows current session stats from the
// 1D timeframe's last bar. Higher timeframes aggregate multiple sessions.
const STRIP_TIMEFRAME = "1D" as const;

// ── Component ────────────────────────────────────────────────────────────────

export function QuoteTab({
  instrumentId,
  entityId: _entityId,
  fundamentals,
  quote,
  initialBars,
  instrument,
  insiderData,
  topNews,
}: QuoteTabProps) {
  const qc = useQueryClient();

  // ── Read last OHLCV bar from cache for SessionStatsStrip ─────────────────
  // WHY `enabled: false`: passive subscriber — OHLCVChart owns the fetch.
  const { data: cachedOhlcv } = useQuery<OHLCVResponse>({
    queryKey: qk.instruments.ohlcv(instrumentId, STRIP_TIMEFRAME),
    enabled: false,
  });

  const bars: readonly OHLCVBar[] = cachedOhlcv?.bars ?? initialBars ?? [];
  const lastBar = bars.length > 0 ? bars[bars.length - 1] : null;

  const stripProps = {
    open: lastBar?.open ?? null,
    high: lastBar?.high ?? null,
    low: lastBar?.low ?? null,
    volume: lastBar?.volume ?? null,
  };

  // WHY lastBarTs: intradayStats queryKey includes the last bar timestamp so a
  // new 5m candle invalidates only intradayStats, not peers / levels (Δ28).
  const lastBarTs = lastBar?.timestamp;

  // ── Parallel sidebar data (6 queries) ────────────────────────────────────
  const sidebar = useQuoteSidebarData(instrumentId, lastBarTs);

  // ── Shift+R: cascade-invalidate all qk.instruments.detail(id) sub-keys (Δ38) ──
  // WHY window-scoped + modifier guard: same pattern as OHLCVChart timeframe
  // chords. Fires only when Shift held and key is "R"; ignores modifier combos.
  const instrumentIdForEffect = useMemo(() => instrumentId, [instrumentId]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.shiftKey || e.key !== "R") return;
      const target = e.target as HTMLElement | null;
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable) return;
      void qc.invalidateQueries({ queryKey: qk.instruments.detail(instrumentIdForEffect) });
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [qc, instrumentIdForEffect]);

  return (
    // CSS Grid (T-06 layout pivot, Δ31): left = minmax(0,1fr); right = 320px/380px.
    <div className="grid grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_380px] h-full overflow-hidden p-0">

      {/* ── LEFT: chart + strips ──────────────────────────────────────────── */}
      <div className="flex flex-col min-w-0 overflow-hidden">
        {/* Chart fills remaining vertical space inside the left column. */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <OHLCVChart instrumentId={instrumentId} initialBars={initialBars} />
        </div>

        {/* Multi-period returns strip (7 periods, data-table-grid 20px). */}
        <MultiPeriodReturnsStrip
          data={sidebar.multiPeriodReturns}
          isLoading={sidebar.isLoading}
        />

        {/* Intraday stats band (VWAP/ATR/RSI/GAP/PREM/SI, data-table-grid 20px). */}
        <IntradayStatsBand
          data={sidebar.intradayStats}
          isLoading={sidebar.isLoading}
        />

        {/* Session O/H/L/V strip — 20px, reads last 1D bar from OHLCV cache. */}
        <SessionStatsStrip {...stripProps} />
      </div>

      {/* ── RIGHT: scrollable metrics rail ───────────────────────────────────
       * WHY overflow-y-auto: metrics table exceeds viewport height on 1080p.
       * The right column scrolls independently, keeping the chart locked.
       * WHY border-l border-border: 1px vertical hairline rule.
       */}
      {/* WHY min-h-0: grid item default min-height=auto lets content expand past the
          grid track, making overflow-y-auto a no-op. min-h-0 caps the track height. */}
      <div className="border-l border-border overflow-y-auto flex flex-col min-h-0">
        {/* Statistics (MetricsTable with 3x MetricGrid4Col + trailing rows). */}
        <MetricsTable
          instrumentId={instrumentId}
          fundamentals={fundamentals}
          quote={quote}
        />

        {/* Company About: sector/industry/HQ/founded/description. */}
        <CompanyAboutCard
          instrument={instrument ?? null}
        />

        {/* Insider Activity: top-5 from bundle.insider (zero extra fetch). */}
        <InsiderActivityList
          data={insiderData}
        />

        {/* Annual EPS: last-4 annual records from earningsHistory query. */}
        <EarningsMiniList
          data={sidebar.earningsHistory}
          isLoading={sidebar.isLoading}
        />

        {/* Related Headlines: top-5 from top_news bundle seed. */}
        <RelatedHeadlinesList
          data={topNews}
        />

        {/* Bottom triple strip: Peers | PriceLevels | WhatsMoving.
            WHY no mt-auto wrapper (Δ42 density fix): mt-auto pushed the strip to
            the bottom of the overflow-y-auto container, making it fall below the
            fold when the content above it exceeded ~780px at 900px viewport. The
            strip must be in-flow and visible above-fold for the Δ42 density gate. */}
        <BottomTripleStrip
          peers={sidebar.peers}
          priceLevels={sidebar.priceLevels}
          topNews={topNews}
          currentPrice={quote?.price}
          isLoadingPeers={sidebar.errors.peers ? undefined : sidebar.isLoading}
          isLoadingLevels={sidebar.errors.priceLevels ? undefined : sidebar.isLoading}
          isErrorPeers={sidebar.errors.peers}
          isErrorLevels={sidebar.errors.priceLevels}
        />
      </div>
    </div>
  );
}
