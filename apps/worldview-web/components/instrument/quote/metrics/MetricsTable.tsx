/**
 * components/instrument/quote/metrics/MetricsTable.tsx — right-rail STATISTICS table
 *
 * WHY THIS EXISTS: PRD-0088 §6.7.2 / PLAN-0090 T-B-03 specify a Finviz-density
 * stats panel on the right rail of the Quote tab. Every row is a 22px
 * MetricRow that fuses four S9 sources (Fundamentals, FundamentalsSnapshot,
 * TechnicalsData, ShareStatisticsData) into a single scrollable column —
 * "one glance, one grid".
 *
 * ── WAVE-2 REDESIGN (2026-06-10) ─────────────────────────────────────────────
 *   1. SECTIONED: the anonymous hairline dividers are replaced with the house
 *      accent-bar section headers (2px primary left bar + uppercase label —
 *      same pattern as DenseMetricsGrid) so the analyst can land on
 *      VALUATION / PROFITABILITY / OWNERSHIP / TECHNICALS without counting rows.
 *   2. GROWTH rows added (rev/EPS YoY) — the data was already in the
 *      Fundamentals shape but never rendered.
 *   3. The analyst row is now a real consensus block (coloured Buy/Hold/Sell
 *      counts + sample size, "No analyst coverage" when empty) instead of the
 *      cryptic "0B · 0H · 0S" — see AnalystMiniBar.
 *
 * DATA PATH (Wave-2 fix): useMetricsTableData remains the SOLE data hook, but
 * its fundamentals leg now finds the cache PRE-SEEDED by InstrumentPageClient
 * (bundle.fundamentals → transformFundamentalsSections) so every row paints
 * on first render with zero extra round-trips. The hook's own fetch is the
 * refresh path, gated on the auth token (the pre-fix 401 race left the whole
 * VALUATION block permanently "—").
 *
 * COLOUR THRESHOLDS: all helpers map 1:1 to PRD-0088 FR-10 (see per-row WHY).
 * DESIGN REF: PRD-0088 §6.7.2, PLAN-0090 §T-B-03, DS §15 (accent-bar headers).
 */

"use client";

import { useMetricsTableData } from "@/components/instrument/hooks/useMetricsTableData";
import { MetricRow, type MetricValueColor } from "./MetricRow";
import { WeekRangeBar } from "./WeekRangeBar";
import { AnalystMiniBar } from "./AnalystMiniBar";
import { formatMarketCap, formatPercent, formatPrice, formatRatio, formatVolume } from "@/lib/utils";
import type { Fundamentals, Quote, ShareStatisticsData, TechnicalsData } from "@/types/api";

interface MetricsTableProps {
  instrumentId: string;
  // WHY the prop is OPTIONAL: the page-bundle's slim overview.fundamentals
  // (5 fields) acts as a first-paint seed; the hook's full Fundamentals shape
  // takes precedence as soon as it lands in cache (which, post Wave-2, is
  // immediately — InstrumentPageClient seeds the cache from the bundle's raw
  // all-sections leg before this component's first query read).
  fundamentals?: Fundamentals | null;
  quote: Quote | null;
}

// ── Threshold colour helpers (PRD-0088 FR-10) ──────────────────────────────
// WHY tiny pure helpers: each row's threshold logic lives in ONE place so the
// spec maps 1:1 to source. Null inputs return "default" — we never colour
// missing data (that would mis-signal).
// NOTE on percentages: gross_margin/roe/dividend_yield/short_percent are
// stored as decimals (0.15 = 15%), so thresholds use decimal form too.

/** FR-10 P/E: amber >30, red >50. */
const peColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v > 50 ? "negative" : v > 30 ? "amber" : "default";

/** FR-10 ROE: green >15%, red <0. */
const roeColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v < 0 ? "negative" : v > 0.15 ? "positive" : "default";

/** FR-10 Beta: amber >1.5, red >2. */
const betaColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v > 2 ? "negative" : v > 1.5 ? "amber" : "default";

/** FR-10 Debt/Equity: amber >1x, red >2x. */
const debtColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v > 2 ? "negative" : v > 1 ? "amber" : "default";

/** FR-10 Short %: amber >10%, red >20% (decimal). */
const shortColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v > 0.2 ? "negative" : v > 0.1 ? "amber" : "default";

/** FR-10 Net margin: green >20%, red <0 (decimal). */
const netMarginColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v < 0 ? "negative" : v > 0.2 ? "positive" : "default";

/** Sign colour — EPS/ROA/growth positive/negative split. */
const signColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v >= 0 ? "positive" : "negative";

/** Price-vs-MA trend: green when current >= MA (uptrend), red when below. */
const trendColor = (p: number | null, m: number | null): MetricValueColor =>
  p == null || m == null ? "default" : p >= m ? "positive" : "negative";

// ── Section header (house accent-bar pattern) ───────────────────────────────
//
// WHY this exact recipe: mirrors DenseMetricsGrid's group header (2px primary
// left accent + bg-muted/20 + 10px uppercase tracking) so the Quote rail and
// the Financials grid share one visual vocabulary. h-5 (20px) keeps the rail
// on its 22px row rhythm without reading as a data row.

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center h-5 px-3 mt-1 border-y border-border/40 border-l-2 border-l-primary bg-muted/20">
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground">{label}</span>
    </div>
  );
}

export function MetricsTable({ instrumentId, fundamentals: fundamentalsProp, quote }: MetricsTableProps) {
  // WHY one hook: all four sub-resources share a single loading surface;
  // undefined fields render "—" via MetricValue automatically.
  const {
    fundamentals: fundamentalsFromHook,
    snapshot,
    technicals: technicalsResp,
    shareStats: shareStatsResp,
  } = useMetricsTableData(instrumentId);
  // WHY hook-wins coalesce: the hook reads the cache entry that
  // InstrumentPageClient seeds with the FULL transformed Fundamentals shape;
  // the prop is the slim 5-field bundle header kept purely as a first-paint
  // fallback for callers that render before the seed effect runs (tests).
  const fundamentals: Fundamentals | null = fundamentalsFromHook ?? fundamentalsProp ?? null;

  // WHY records[0].data cast: getTechnicals/getShareStatistics return a raw
  // FundamentalsSectionResponse envelope; the typed shape lives on records[0]
  // per the EODHD section convention. Cast once so the rows stay terse.
  const technicals = (technicalsResp?.records?.[0]?.data ?? null) as TechnicalsData | null;
  const shareStats = (shareStatsResp?.records?.[0]?.data ?? null) as ShareStatisticsData | null;

  const price = quote?.price ?? null;
  // WHY string-key access AND PascalCase: TechnicalsData mirrors the
  // EODHD-verbatim payload. Keys begin with digits ("50DayMA") so they can't
  // be JS identifiers — bracket access is mandatory.
  const ma50 = technicals?.["50DayMA"] ?? null;
  const ma200 = technicals?.["200DayMA"] ?? null;
  // WHY raw-percent normalization for ownership fields: ShareStatisticsData
  // returns PercentInsiders / PercentInstitutions as already-multiplied
  // magnitudes (65.35 = 65.35%) per EODHD. formatPercent itself multiplies by
  // 100, so divide by 100 first to keep the round-trip honest.
  const pctInsiders = shareStats?.PercentInsiders != null ? shareStats.PercentInsiders / 100 : null;
  const pctInstitutions =
    shareStats?.PercentInstitutions != null ? shareStats.PercentInstitutions / 100 : null;
  // ShortPercent is already a decimal (0.0092 = 0.92%) per EODHD — pass through.
  const shortPct = technicals?.ShortPercent ?? null;
  // Arrow suffix — visual trend cue (PRD §6.7.2 technicals rows).
  const arrow = (p: number | null, m: number | null) =>
    p == null || m == null ? "" : p >= m ? " ↑" : " ↓";

  // Analyst target upside vs current price — null when either side missing.
  const target = fundamentals?.analyst_target_price ?? null;
  const upside = target != null && price != null && price > 0 ? (target - price) / price : null;

  return (
    <div className="w-full flex flex-col">
      {/* Rail title — 28px (h-7), 10px caps per PRD §6.7.2. */}
      <div className="flex items-center h-7 px-3 border-b border-border/50 bg-card/50 text-[10px] uppercase tracking-wide text-muted-foreground">
        Statistics
      </div>

      {/* ── VALUATION ──────────────────────────────────────────────────────── */}
      <SectionHeader label="Valuation" />
      <MetricRow label="MARKET CAP" value={formatMarketCap(fundamentals?.market_cap ?? null)} />
      <MetricRow label="P/E" value={formatRatio(fundamentals?.pe_ratio ?? null, "")} color={peColor(fundamentals?.pe_ratio)} />
      <MetricRow label="FWD P/E" value={formatRatio(fundamentals?.forward_pe ?? null, "")} color={peColor(fundamentals?.forward_pe)} />
      <MetricRow label="EPS TTM" value={formatPrice(snapshot?.eps_ttm ?? null)} color={signColor(snapshot?.eps_ttm)} />
      <MetricRow label="P/S" value={formatRatio(fundamentals?.price_to_sales ?? null, "")} />
      <MetricRow label="P/B" value={formatRatio(fundamentals?.price_to_book ?? null, "")} />
      <MetricRow label="EV/EBITDA" value={formatRatio(fundamentals?.ev_to_ebitda ?? null, "")} />

      {/* ── PROFITABILITY (incl. growth — same analytical question: "is the
             business getting better?") ──────────────────────────────────────── */}
      <SectionHeader label="Profitability" />
      <MetricRow label="GROSS MARGIN" value={formatPercent(fundamentals?.gross_margin ?? null)} />
      <MetricRow label="OPER MARGIN" value={formatPercent(fundamentals?.operating_margin ?? null)} />
      <MetricRow label="NET MARGIN" value={formatPercent(fundamentals?.net_margin ?? null)} color={netMarginColor(fundamentals?.net_margin)} />
      <MetricRow label="ROE" value={formatPercent(fundamentals?.roe ?? null)} color={roeColor(fundamentals?.roe)} />
      <MetricRow label="ROA" value={formatPercent(fundamentals?.roa ?? null)} color={signColor(fundamentals?.roa)} />
      {/* Wave-2: growth rows — the Fundamentals shape always carried these
          (QuarterlyRevenueGrowthYOY / QuarterlyEarningsGrowthYOY) but the old
          table never rendered them. Decimal form → formatPercent. */}
      <MetricRow label="REV GROWTH YOY" value={formatPercent(fundamentals?.revenue_growth_yoy ?? null)} color={signColor(fundamentals?.revenue_growth_yoy)} />
      <MetricRow label="EPS GROWTH YOY" value={formatPercent(fundamentals?.earnings_growth_yoy ?? null)} color={signColor(fundamentals?.earnings_growth_yoy)} />

      {/* ── LEVERAGE & YIELD ──────────────────────────────────────────────── */}
      <SectionHeader label="Leverage & Yield" />
      <MetricRow label="DEBT/EQUITY" value={formatRatio(fundamentals?.debt_to_equity ?? null)} color={debtColor(fundamentals?.debt_to_equity)} />
      <MetricRow label="CURRENT RATIO" value={formatRatio(fundamentals?.current_ratio ?? null)} />
      <MetricRow label="DIV YIELD" value={formatPercent(fundamentals?.dividend_yield ?? null)} />
      <MetricRow label="PAYOUT RATIO" value={formatPercent(fundamentals?.payout_ratio ?? null)} />
      <MetricRow label="BETA" value={snapshot?.beta != null ? snapshot.beta.toFixed(2) : null} color={betaColor(snapshot?.beta)} />

      {/* ── 52W RANGE — two rows + the position bar ───────────────────────── */}
      <SectionHeader label="52-Week Range" />
      <MetricRow label="52W HIGH" value={formatPrice(fundamentals?.week_52_high ?? null)} />
      <MetricRow label="52W LOW" value={formatPrice(fundamentals?.week_52_low ?? null)} />
      <WeekRangeBar high={fundamentals?.week_52_high ?? null} low={fundamentals?.week_52_low ?? null} current={price} />

      {/* ── OWNERSHIP ─────────────────────────────────────────────────────── */}
      <SectionHeader label="Ownership" />
      <MetricRow label="AVG VOL 30D" value={formatVolume(snapshot?.avg_volume_30d ?? null)} />
      {/* SHORT %: ShortPercent is decimal-form per EODHD — feed directly. */}
      <MetricRow label="SHORT %" value={formatPercent(shortPct)} color={shortColor(shortPct)} />
      {/* INST/INSIDER OWN: normalized above (raw% ÷ 100) before formatPercent. */}
      <MetricRow label="INST OWN" value={formatPercent(pctInstitutions)} />
      <MetricRow label="INSIDER OWN" value={formatPercent(pctInsiders)} />

      {/* ── TECHNICALS — MA values with ↑/↓ vs current price ──────────────── */}
      <SectionHeader label="Technicals" />
      <MetricRow label="MA 50" value={ma50 != null ? `${formatPrice(ma50)}${arrow(price, ma50)}` : null} color={trendColor(price, ma50)} />
      <MetricRow label="MA 200" value={ma200 != null ? `${formatPrice(ma200)}${arrow(price, ma200)}` : null} color={trendColor(price, ma200)} />

      {/* ── CONSENSUS — coloured Buy/Hold/Sell counts + 12-month target ───── */}
      <SectionHeader label="Analyst Consensus" />
      <AnalystMiniBar
        strongBuy={fundamentals?.analyst_strong_buy_count ?? null}
        buy={fundamentals?.analyst_buy_count ?? null}
        hold={fundamentals?.analyst_hold_count ?? null}
        sell={fundamentals?.analyst_sell_count ?? null}
        strongSell={fundamentals?.analyst_strong_sell_count ?? null}
      />
      <MetricRow
        label="TARGET"
        value={target != null ? `${formatPrice(target)}${upside != null ? ` (${formatPercent(upside)})` : ""}` : null}
        color={upside != null ? (upside >= 0 ? "positive" : "negative") : "default"}
      />
    </div>
  );
}
