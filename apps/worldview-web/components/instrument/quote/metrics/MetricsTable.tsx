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
import { formatMarketCap, formatPercent, formatPercentUnsigned, formatPrice, formatRatio, formatVolume } from "@/lib/utils";
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

// ── Colour helpers ─────────────────────────────────────────────────────────
//
// COLOUR SEMANTICS (UI roadmap 2026-06-19 item #1 / A1): teal (positive) and
// red (negative) are reserved STRICTLY for *directional* values — things that
// genuinely move up or down: price change, returns, P&L, and rate-of-change
// (growth YoY). They are NOT applied to non-directional *levels* (valuation
// multiples like P/E, profitability levels like margins / ROE / ROA, leverage
// ratios like D/E, risk levels like Beta / Short %, ownership %). Painting a
// P/E red ("expensive") or a margin green ("good") miscommunicates: those are
// editorial judgements, not directions, and they dilute the red/green that
// matters for actual moves. Non-directional metrics now render in neutral
// `text-foreground` (the MetricRow/MetricValue "default" colour). Peer-percentile
// conditional formatting (roadmap B3) is the correct future home for "cheap vs
// rich" context — not bull/bear colour.
//
// WHY pure helpers remain: the directional ones still benefit from one place
// each. Null inputs return "default" — we never colour missing data.

/**
 * Sign colour — ONLY for directional values (a positive value means "up/grew",
 * a negative value means "down/shrank"). Used for growth-YoY rates here.
 */
const signColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v >= 0 ? "positive" : "negative";

/**
 * Price-vs-MA trend: green when current >= MA (uptrend), red when below.
 * Directional: it encodes whether price is above or below its moving average.
 */
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
      {/* P/E + FWD P/E are non-directional VALUATION levels → neutral (item #1).
          A red P/E read as "this looks broken"; "cheap vs rich" context belongs
          in peer-percentile heat (roadmap B3), not bull/bear colour. */}
      <MetricRow label="P/E" value={formatRatio(fundamentals?.pe_ratio ?? null, "")} />
      <MetricRow label="FWD P/E" value={formatRatio(fundamentals?.forward_pe ?? null, "")} />
      {/* EPS TTM is an absolute level (a $ amount), not a delta → neutral. */}
      <MetricRow label="EPS TTM" value={formatPrice(snapshot?.eps_ttm ?? null)} />
      <MetricRow label="P/S" value={formatRatio(fundamentals?.price_to_sales ?? null, "")} />
      <MetricRow label="P/B" value={formatRatio(fundamentals?.price_to_book ?? null, "")} />
      <MetricRow label="EV/EBITDA" value={formatRatio(fundamentals?.ev_to_ebitda ?? null, "")} />

      {/* ── PROFITABILITY (incl. growth — same analytical question: "is the
             business getting better?") ──────────────────────────────────────── */}
      <SectionHeader label="Profitability" />
      {/* Margins / ROE / ROA are non-directional QUALITY levels → neutral, and
          formatted UNSIGNED (a "+" prefix is for deltas, not absolute levels —
          item #1 + the F-3 sign-on-levels fix). */}
      <MetricRow label="GROSS MARGIN" value={formatPercentUnsigned(fundamentals?.gross_margin ?? null)} />
      <MetricRow label="OPER MARGIN" value={formatPercentUnsigned(fundamentals?.operating_margin ?? null)} />
      <MetricRow label="NET MARGIN" value={formatPercentUnsigned(fundamentals?.net_margin ?? null)} />
      <MetricRow label="ROE" value={formatPercentUnsigned(fundamentals?.roe ?? null)} />
      <MetricRow label="ROA" value={formatPercentUnsigned(fundamentals?.roa ?? null)} />
      {/* Wave-2: growth rows — these ARE directional (a rate-of-change over a
          year: positive = grew, negative = shrank). They keep teal/red + the
          signed formatter so the +/- and the colour reinforce the direction. */}
      <MetricRow label="REV GROWTH YOY" value={formatPercent(fundamentals?.revenue_growth_yoy ?? null)} color={signColor(fundamentals?.revenue_growth_yoy)} />
      <MetricRow label="EPS GROWTH YOY" value={formatPercent(fundamentals?.earnings_growth_yoy ?? null)} color={signColor(fundamentals?.earnings_growth_yoy)} />

      {/* ── LEVERAGE & YIELD ──────────────────────────────────────────────── */}
      <SectionHeader label="Leverage & Yield" />
      {/* Leverage / yield are non-directional levels → neutral, unsigned %. */}
      <MetricRow label="DEBT/EQUITY" value={formatRatio(fundamentals?.debt_to_equity ?? null)} />
      <MetricRow label="CURRENT RATIO" value={formatRatio(fundamentals?.current_ratio ?? null)} />
      <MetricRow label="DIV YIELD" value={formatPercentUnsigned(fundamentals?.dividend_yield ?? null)} />
      <MetricRow label="PAYOUT RATIO" value={formatPercentUnsigned(fundamentals?.payout_ratio ?? null)} />
      {/* Beta is a risk LEVEL, not a direction → neutral. */}
      <MetricRow label="BETA" value={snapshot?.beta != null ? snapshot.beta.toFixed(2) : null} />

      {/* ── 52W RANGE — two rows + the position bar ───────────────────────── */}
      <SectionHeader label="52-Week Range" />
      <MetricRow label="52W HIGH" value={formatPrice(fundamentals?.week_52_high ?? null)} />
      <MetricRow label="52W LOW" value={formatPrice(fundamentals?.week_52_low ?? null)} />
      <WeekRangeBar high={fundamentals?.week_52_high ?? null} low={fundamentals?.week_52_low ?? null} current={price} />

      {/* ── OWNERSHIP ─────────────────────────────────────────────────────── */}
      <SectionHeader label="Ownership" />
      <MetricRow label="AVG VOL 30D" value={formatVolume(snapshot?.avg_volume_30d ?? null)} />
      {/* SHORT % / ownership %s are non-directional LEVELS → neutral, unsigned
          (an ownership % is an absolute level — a "+" would mis-read as a move,
          F-3). SHORT %: ShortPercent is decimal-form per EODHD — feed directly. */}
      <MetricRow label="SHORT %" value={formatPercentUnsigned(shortPct)} />
      {/* INST/INSIDER OWN: normalized above (raw% ÷ 100) before formatting. */}
      <MetricRow label="INST OWN" value={formatPercentUnsigned(pctInstitutions)} />
      <MetricRow label="INSIDER OWN" value={formatPercentUnsigned(pctInsiders)} />

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
