/**
 * components/instrument/financials/FlatMetricsGrid.tsx — Finviz-style 3-col fundamentals grid
 *
 * WHY THIS EXISTS: The PRD-0088 instrument-page redesign collapses the existing
 * multi-panel Financials tab (5+ separate cards with headings) into one dense
 * 3-column Finviz-style flat grid. 45 fundamentals fields are grouped into 8
 * section headers (VALUATION / PROFITABILITY / GROWTH / BALANCE SHEET / CASH FLOW /
 * DIVIDENDS / OWNERSHIP / TECHNICALS) and rendered at terminal-grade density
 * (22px rows, monospace tabular-nums values). One screen = the full fundamentals
 * snapshot with zero scrolling for most instruments.
 *
 * WHY 3 columns (not 4 or 2): PRD-0088 §6.8.1 specifies 3 columns explicitly —
 * matches Finviz's reference layout and balances information density against
 * label-truncation risk at the typical viewport widths used by the platform.
 * 4 columns truncates labels; 2 columns adds excessive vertical scroll.
 *
 * WHY group headers as full-width cells (col-span-3): a 3-col grid header row
 * forces the renderer to keep the section break visually unambiguous regardless
 * of how many cells the section contains. Variable section sizes (Valuation has
 * 6, Technicals has 13) would otherwise misalign if headers were single-cell.
 *
 * WHY RSI(14) AND ATR(14) READ FROM CACHE ONLY (no new fetch):
 * Per PLAN-0090 T-C-01, these two technicals are computed from the OHLCV bars
 * that the chart already fetches via qk.instruments.ohlcv(instrumentId, "1D").
 * We attach a useQuery with `enabled: false` so this component participates in
 * the same cache entry without triggering a new network round-trip. If the
 * chart has not mounted yet (cache miss), both values render as "—" — they
 * will populate on the next render after the chart hydrates the cache. This
 * keeps the Financials tab cheap to render and avoids fighting the chart for
 * concurrent OHLCV fetches.
 *
 * WHY DAILY HIGH/LOW NOT INCLUDED: those live on the Quote / OHLCV header bar
 * already (CompactInstrumentHeader / SessionStatsStrip). Including them here
 * would duplicate data the user already sees at the top of the page.
 *
 * WHO USES IT: FinancialsTab (PLAN-0090 Wave B) — the 2nd tab of the instrument
 * detail page rebuild.
 *
 * DATA SOURCES (all passed in as props — no internal fetches except the cache-read above):
 *   - Fundamentals (S9 /v1/fundamentals/{id}) — valuation, profitability, growth, balance, dividends
 *   - FundamentalsSnapshot (S9 /v1/fundamentals/{id}/snapshot) — eps_ttm, beta, avg_vol_30d, ocf, capex, fcf, fcf_margin, interest_cov, nd_to_ebitda, credit_rating
 *   - TechnicalsData (from FundamentalsRecord.data on the technicals_snapshot section) — 52W high/low, 50DMA, 200DMA, shares_short, short_ratio, short_percent
 *   - ShareStatisticsData (from FundamentalsRecord.data on share_statistics) — shares_outstanding, shares_float, percent_insiders, percent_institutions
 *   - DividendsData (from FundamentalsRecord.data on splits-dividends snapshot) — ExDividendDate, DividendDate
 *
 * DESIGN REFERENCE: docs/specs/0088-instrument-detail-page-ground-up-redesign.md §6.8.1
 *                   docs/plans/0090-instrument-detail-page-redesign-plan.md T-C-01
 */

// WHY "use client": this component reads from the TanStack Query cache to derive
// RSI(14) and ATR(14) from already-fetched OHLCV bars. Cache access requires the
// QueryClient context which is a client-only concern.
"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { qk } from "@/lib/query/keys";
import {
  formatMarketCap,
  formatRatio,
  formatPercent,
  formatDate,
  formatVolume,
} from "@/lib/utils";
import { formatPrice } from "@/lib/format";
import type {
  Fundamentals,
  FundamentalsSnapshot,
  TechnicalsData,
  ShareStatisticsData,
  OHLCVResponse,
} from "@/types/api";
import { MetricCell } from "./MetricCell";

// ── Local types ─────────────────────────────────────────────────────────────

/**
 * DividendsData — typed shape of the splits-dividends snapshot record's `data` dict.
 *
 * WHY local (not in types/api.ts): the splits-dividends section is consumed by
 * exactly two components (SplitsDividendsPanel + this grid). Each owns its own
 * local type to avoid coupling unrelated UI zones — same convention used by
 * InstrumentKeyMetrics.tsx for its TechnicalsRaw type.
 *
 * Keys use the PascalCase casing EODHD returns verbatim; quoted because the
 * leading capital and the casing diverges from our snake_case TS convention.
 */
interface DividendsData {
  ExDividendDate?: string | null;
  DividendDate?: string | null;
}

// ── Props ───────────────────────────────────────────────────────────────────

export interface FlatMetricsGridProps {
  /**
   * Instrument identifier — used as the cache key suffix for the cache-only
   * OHLCV read that powers RSI(14) and ATR(14). MUST match the id used by the
   * chart's primary OHLCV fetch so the cache entry is shared.
   */
  instrumentId: string;

  /**
   * Aggregated fundamentals header (S9 /v1/fundamentals/{id}). May be null while
   * the request is in-flight or if the instrument has no fundamentals row yet.
   * Each cell coalesces to "—" when its specific field is null.
   */
  fundamentals: Fundamentals | null;

  /**
   * Derived snapshot (S9 /v1/fundamentals/{id}/snapshot). Carries 10 fields that
   * are too expensive to compute at query time (FCF, interest coverage, etc.).
   */
  snapshot: FundamentalsSnapshot | null;

  /**
   * Raw EODHD technicals snapshot data — extracted from the first record of the
   * technicals_snapshot section. Carries 52W high/low, 50DMA, 200DMA, short
   * statistics. May be null if the technicals section is empty.
   */
  technicals: TechnicalsData | null;

  /**
   * Raw EODHD share-statistics data — extracted from the first record of the
   * share_statistics section. Carries shares outstanding/float and insider/
   * institutional ownership percentages.
   */
  shareStats: ShareStatisticsData | null;

  /**
   * Raw splits-dividends snapshot data carrying ex-date / dividend date.
   * Optional — when null the two date cells render as "—".
   */
  dividends: DividendsData | null;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * SAFE_DASH — single source of truth for the "no data" placeholder.
 *
 * WHY a constant: searching/swapping the placeholder string later is trivial,
 * and using a constant prevents typos (en-dash vs em-dash vs hyphen). The em-dash
 * is the Bloomberg convention for "value not available".
 */
const SAFE_DASH = "—";

/**
 * fmt() — render a number through a formatter, returning the em-dash for null/undefined.
 *
 * WHY a wrapper: most lib/utils formatters already handle null with a dash, but
 * a thin wrapper centralises the contract and lets us swap formatters per-cell
 * with a uniform call site (`fmt(value, formatPercent)`).
 */
function fmt(
  value: number | null | undefined,
  formatter: (v: number | null | undefined) => string,
): string {
  if (value == null) return SAFE_DASH;
  return formatter(value);
}

// ── Threshold-based colour helpers ──────────────────────────────────────────
// WHY inline (not imported): thresholds are specific to this component's
// display context. Sharing with OverviewSidebarMetrics would couple two
// independent UI zones; the sidebar's thresholds may diverge as the design
// evolves. Identical helpers in two files is cheaper than coupled helpers.

/** P/E colour: <20 = cheap (green), 20-35 = fair (warning), >35 = expensive (red). */
function peClass(pe: number | null | undefined): string {
  if (pe == null) return "text-muted-foreground";
  if (pe > 35) return "text-negative";
  if (pe < 20) return "text-positive";
  return "text-warning";
}

/** Margin/return colour: >0 = green, <0 = red, exactly 0 = neutral. */
function signClass(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground";
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-foreground";
}

/** ROE colour: <0 = losing money, >15% = strong returns, else neutral. */
function roeClass(roe: number | null | undefined): string {
  if (roe == null) return "text-muted-foreground";
  if (roe < 0) return "text-negative";
  if (roe > 0.15) return "text-positive";
  return "text-foreground";
}

/** Debt/Equity colour: >2 = over-levered (red), ≤0.5 = low leverage (green). */
function deClass(de: number | null | undefined): string {
  if (de == null) return "text-muted-foreground";
  if (de > 2) return "text-negative";
  if (de <= 0.5) return "text-positive";
  return "text-foreground";
}

/** RSI(14) colour: >70 = overbought (red), <30 = oversold (green), else neutral. */
function rsiClass(rsi: number | null): string {
  if (rsi == null) return "text-muted-foreground";
  if (rsi > 70) return "text-negative";
  if (rsi < 30) return "text-positive";
  return "text-foreground";
}

// ── RSI/ATR derivation from cached OHLCV bars ───────────────────────────────

/**
 * computeRsi14 — Wilder's smoothed RSI over the last 14 daily closes.
 *
 * WHY Wilder's smoothing (not simple SMA): the original Welles Wilder RSI uses
 * an EMA-like smoothing where each subsequent value blends 13/14 of the prior
 * average with 1/14 of the new gain/loss. This is the de-facto standard used by
 * Finviz, TradingView, and every brokerage. A simple SMA over 14 bars would
 * produce values that drift from those reference quotes — confusing for users.
 *
 * Returns null when fewer than 15 bars are available (need 14 deltas → 15 closes).
 */
function computeRsi14(closes: number[]): number | null {
  if (closes.length < 15) return null;
  // First 14 deltas seed the initial avg gain / avg loss (simple mean).
  let gainSum = 0;
  let lossSum = 0;
  for (let i = 1; i <= 14; i++) {
    const delta = closes[i] - closes[i - 1];
    if (delta >= 0) gainSum += delta;
    else lossSum += -delta;
  }
  let avgGain = gainSum / 14;
  let avgLoss = lossSum / 14;
  // Smooth across the remaining bars using Wilder's recurrence.
  for (let i = 15; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1];
    const gain = delta >= 0 ? delta : 0;
    const loss = delta < 0 ? -delta : 0;
    avgGain = (avgGain * 13 + gain) / 14;
    avgLoss = (avgLoss * 13 + loss) / 14;
  }
  // RS = avg gain / avg loss; RSI = 100 - 100/(1+RS).
  // When avgLoss is 0 the asset only rallied → RSI defined as 100.
  if (avgLoss === 0) return 100;
  const rs = avgGain / avgLoss;
  return 100 - 100 / (1 + rs);
}

/**
 * computeAtr14 — Average True Range over the last 14 daily bars (Wilder smoothed).
 *
 * TR_t = max(high_t - low_t, |high_t - close_{t-1}|, |low_t - close_{t-1}|).
 * ATR is the Wilder-smoothed average of TR over a 14-bar window. Same smoothing
 * rationale as RSI above.
 *
 * Returns null when fewer than 15 bars are available (need 14 TRs starting from bar 1).
 */
function computeAtr14(
  highs: number[],
  lows: number[],
  closes: number[],
): number | null {
  if (highs.length < 15 || lows.length < 15 || closes.length < 15) return null;
  // Seed: simple mean of first 14 TR values (bars 1..14).
  let trSum = 0;
  for (let i = 1; i <= 14; i++) {
    const hl = highs[i] - lows[i];
    const hc = Math.abs(highs[i] - closes[i - 1]);
    const lc = Math.abs(lows[i] - closes[i - 1]);
    trSum += Math.max(hl, hc, lc);
  }
  let atr = trSum / 14;
  // Smooth across remaining bars: ATR_t = (ATR_{t-1} * 13 + TR_t) / 14.
  for (let i = 15; i < closes.length; i++) {
    const hl = highs[i] - lows[i];
    const hc = Math.abs(highs[i] - closes[i - 1]);
    const lc = Math.abs(lows[i] - closes[i - 1]);
    const tr = Math.max(hl, hc, lc);
    atr = (atr * 13 + tr) / 14;
  }
  return atr;
}

// ── Component ───────────────────────────────────────────────────────────────

export function FlatMetricsGrid({
  instrumentId,
  fundamentals,
  snapshot,
  technicals,
  shareStats,
  dividends,
}: FlatMetricsGridProps) {
  // ── Cache-only OHLCV read for RSI(14) / ATR(14) ────────────────────────
  // WHY enabled:false: we deliberately do NOT trigger a network fetch from this
  // grid. The chart on the same page fetches OHLCV using the identical query
  // key, and TanStack Query exposes the cached result here regardless of our
  // enabled flag. If the chart has not yet mounted, `data` is undefined and
  // both technicals render as "—" — they will populate on the next render
  // cycle after the chart hydrates the cache.
  // WHY staleTime + gcTime omitted: those are owned by the chart's primary
  // fetch. This consumer only reads; it does not negotiate freshness.
  const { data: ohlcv } = useQuery<OHLCVResponse>({
    queryKey: qk.instruments.ohlcv(instrumentId, "1D"),
    // WHY a non-throwing queryFn that resolves to a stub: TanStack Query requires
    // queryFn to be defined even when enabled:false (otherwise dev-mode warns).
    // The function will never run while enabled is false; the stub satisfies the
    // type checker without making a request. If a future caller flips enabled,
    // the request would 404-ish — making the stub explicit prevents an accidental
    // upgrade to "fetching" mode without thinking.
    queryFn: () => Promise.reject(new Error("cache-only read — chart owns this fetch")),
    enabled: false,
  });

  // Derive RSI/ATR memoised — recompute only when the bars array reference changes.
  // WHY useMemo: the 14-bar window scan is cheap (~tens of ops) but we render on
  // every cache change; memoising removes a tiny re-render cost when fundamentals
  // change but bars do not.
  const { rsi14, atr14 } = useMemo(() => {
    const bars = ohlcv?.bars ?? [];
    if (bars.length < 15) return { rsi14: null, atr14: null };
    const closes = bars.map((b) => b.close);
    const highs = bars.map((b) => b.high);
    const lows = bars.map((b) => b.low);
    return {
      rsi14: computeRsi14(closes),
      atr14: computeAtr14(highs, lows, closes),
    };
  }, [ohlcv?.bars]);

  // ── Render ─────────────────────────────────────────────────────────────
  // WHY grid grid-cols-3 gap-x-4 gap-y-1: PRD-0088 §6.8.1 spec exactly. The
  // gap-x-4 provides horizontal breathing room between columns; gap-y-1 keeps
  // rows tight (we want 22px rows + 4px gap, not generous spacing).
  // WHY border + rounded-sm wrapper: matches the panel chrome used by the rest
  // of the instrument page (TechnicalSnapshot, SplitsDividendsPanel) so the
  // grid does not float without visual containment.
  return (
    <div
      className="grid grid-cols-3 gap-x-4 gap-y-1 border border-border rounded-sm bg-card"
      data-testid="flat-metrics-grid"
    >
      {/* ────────────────────────────────────────────────────────────────────
          GROUP 1 — VALUATION (6 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="VALUATION" isHeader value="" />
      <MetricCell
        label="MKT CAP"
        value={fmt(fundamentals?.market_cap, formatMarketCap)}
      />
      <MetricCell
        label="P/E"
        value={fmt(fundamentals?.pe_ratio, formatRatio)}
        valueClass={peClass(fundamentals?.pe_ratio)}
      />
      <MetricCell
        label="FWD P/E"
        value={fmt(fundamentals?.forward_pe, formatRatio)}
        valueClass={peClass(fundamentals?.forward_pe)}
      />
      <MetricCell
        label="P/B"
        value={fmt(fundamentals?.price_to_book, formatRatio)}
      />
      <MetricCell
        label="P/S"
        value={fmt(fundamentals?.price_to_sales, formatRatio)}
      />
      <MetricCell
        label="EV/EBITDA"
        value={fmt(fundamentals?.ev_to_ebitda, formatRatio)}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 2 — PROFITABILITY (6 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="PROFITABILITY" isHeader value="" />
      <MetricCell
        label="GROSS MARGIN"
        value={fmt(fundamentals?.gross_margin, formatPercent)}
        valueClass={signClass(fundamentals?.gross_margin)}
      />
      <MetricCell
        label="OP MARGIN"
        value={fmt(fundamentals?.operating_margin, formatPercent)}
        valueClass={signClass(fundamentals?.operating_margin)}
      />
      <MetricCell
        label="NET MARGIN"
        value={fmt(fundamentals?.net_margin, formatPercent)}
        valueClass={signClass(fundamentals?.net_margin)}
      />
      <MetricCell
        label="ROE"
        value={fmt(fundamentals?.roe, formatPercent)}
        valueClass={roeClass(fundamentals?.roe)}
      />
      <MetricCell
        label="ROA"
        value={fmt(fundamentals?.roa, formatPercent)}
        valueClass={signClass(fundamentals?.roa)}
      />
      <MetricCell
        label="EPS (TTM)"
        // WHY formatPrice (not formatRatio): EPS is a currency-denominated
        // per-share figure ($2.34), not a unitless ratio.
        value={snapshot?.eps_ttm != null ? formatPrice(snapshot.eps_ttm) : SAFE_DASH}
        valueClass={signClass(snapshot?.eps_ttm)}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 3 — GROWTH (3 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="GROWTH" isHeader value="" />
      <MetricCell
        label="REV GROWTH YOY"
        value={fmt(fundamentals?.revenue_growth_yoy, formatPercent)}
        valueClass={signClass(fundamentals?.revenue_growth_yoy)}
      />
      <MetricCell
        label="EPS GROWTH YOY"
        value={fmt(fundamentals?.earnings_growth_yoy, formatPercent)}
        valueClass={signClass(fundamentals?.earnings_growth_yoy)}
      />
      <MetricCell
        label="FCF MARGIN"
        value={fmt(snapshot?.fcf_margin, formatPercent)}
        valueClass={signClass(snapshot?.fcf_margin)}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 4 — BALANCE SHEET (5 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="BALANCE SHEET" isHeader value="" />
      <MetricCell
        label="DEBT/EQUITY"
        value={fmt(fundamentals?.debt_to_equity, formatRatio)}
        valueClass={deClass(fundamentals?.debt_to_equity)}
      />
      <MetricCell
        label="CURRENT RATIO"
        value={fmt(fundamentals?.current_ratio, formatRatio)}
      />
      <MetricCell
        label="QUICK RATIO"
        value={fmt(fundamentals?.quick_ratio, formatRatio)}
      />
      <MetricCell
        label="NET DEBT/EBITDA"
        value={fmt(snapshot?.net_debt_to_ebitda, formatRatio)}
      />
      <MetricCell
        label="INT COVERAGE"
        value={fmt(snapshot?.interest_coverage, formatRatio)}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 5 — CASH FLOW (4 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="CASH FLOW" isHeader value="" />
      <MetricCell
        label="OP CASH FLOW"
        value={fmt(snapshot?.operating_cash_flow, formatMarketCap)}
      />
      <MetricCell
        label="CAPEX"
        // WHY Math.abs: EODHD returns capex as a negative number (cash outflow).
        // Display as a positive magnitude for readability; the label "CAPEX"
        // makes the sign convention unambiguous.
        value={
          snapshot?.capex != null
            ? formatMarketCap(Math.abs(snapshot.capex))
            : SAFE_DASH
        }
      />
      <MetricCell
        label="FREE CASH FLOW"
        value={fmt(snapshot?.free_cash_flow, formatMarketCap)}
        valueClass={signClass(snapshot?.free_cash_flow)}
      />
      <MetricCell
        label="CREDIT RATING"
        // Credit rating is a string ("A+", "BBB-"), not a numeric — passes through
        // verbatim. Always null until a credit-data provider is integrated.
        value={snapshot?.credit_rating ?? SAFE_DASH}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 6 — DIVIDENDS (4 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="DIVIDENDS" isHeader value="" />
      <MetricCell
        label="DIV YIELD"
        value={fmt(fundamentals?.dividend_yield, formatPercent)}
        valueClass={
          (fundamentals?.dividend_yield ?? 0) > 0.03
            ? "text-positive"
            : "text-foreground"
        }
      />
      <MetricCell
        label="PAYOUT RATIO"
        value={fmt(fundamentals?.payout_ratio, formatPercent)}
      />
      <MetricCell
        label="EX-DIV DATE"
        value={dividends?.ExDividendDate ? formatDate(dividends.ExDividendDate) : SAFE_DASH}
      />
      <MetricCell
        label="DIV PAY DATE"
        value={dividends?.DividendDate ? formatDate(dividends.DividendDate) : SAFE_DASH}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 7 — OWNERSHIP (4 fields)
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="OWNERSHIP" isHeader value="" />
      <MetricCell
        label="SHARES OUT"
        value={fmt(shareStats?.shares_outstanding, formatMarketCap)}
      />
      <MetricCell
        label="FLOAT"
        value={fmt(shareStats?.shares_float, formatMarketCap)}
      />
      <MetricCell
        label="% INSIDERS"
        value={fmt(shareStats?.percent_insiders, formatPercent)}
      />
      <MetricCell
        label="% INSTITUTIONS"
        value={fmt(shareStats?.percent_institutions, formatPercent)}
      />

      {/* ────────────────────────────────────────────────────────────────────
          GROUP 8 — TECHNICALS (13 fields)
          Includes RSI(14) + ATR(14) computed from cached OHLCV bars (no fetch).
          ──────────────────────────────────────────────────────────────────── */}
      <MetricCell label="TECHNICALS" isHeader value="" />
      <MetricCell
        label="BETA"
        // WHY toFixed(2): beta convention is 2 decimals (Yahoo/Finviz/EODHD all use 2dp).
        value={snapshot?.beta != null ? snapshot.beta.toFixed(2) : SAFE_DASH}
      />
      <MetricCell
        label="52W HIGH"
        value={
          technicals?.["52_week_high"] != null
            ? formatPrice(technicals["52_week_high"])
            : fmt(fundamentals?.week_52_high, formatPrice)
        }
      />
      <MetricCell
        label="52W LOW"
        value={
          technicals?.["52_week_low"] != null
            ? formatPrice(technicals["52_week_low"])
            : fmt(fundamentals?.week_52_low, formatPrice)
        }
      />
      <MetricCell
        label="DAY RETURN"
        value={fmt(fundamentals?.daily_return, formatPercent)}
        valueClass={signClass(fundamentals?.daily_return)}
      />
      <MetricCell
        label="50D MA"
        value={
          technicals?.["50_day_ma"] != null
            ? formatPrice(technicals["50_day_ma"])
            : SAFE_DASH
        }
      />
      <MetricCell
        label="200D MA"
        value={
          technicals?.["200_day_ma"] != null
            ? formatPrice(technicals["200_day_ma"])
            : SAFE_DASH
        }
      />
      <MetricCell
        label="RSI(14)"
        // WHY toFixed(1): RSI is conventionally shown to 1 decimal (Finviz/TV).
        value={rsi14 != null ? rsi14.toFixed(1) : SAFE_DASH}
        valueClass={rsiClass(rsi14)}
      />
      <MetricCell
        label="ATR(14)"
        // WHY formatPrice: ATR is a price-magnitude value (same units as price).
        value={atr14 != null ? formatPrice(atr14) : SAFE_DASH}
      />
      <MetricCell
        label="AVG VOL 30D"
        value={fmt(snapshot?.avg_volume_30d, formatVolume)}
      />
      <MetricCell
        label="SHARES SHORT"
        value={fmt(technicals?.shares_short, formatVolume)}
      />
      <MetricCell
        label="SHORT RATIO"
        value={fmt(technicals?.short_ratio, formatRatio)}
      />
      <MetricCell
        label="SHORT %"
        value={fmt(technicals?.short_percent, formatPercent)}
      />
    </div>
  );
}
