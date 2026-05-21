/**
 * components/instrument/quote/metrics/MetricsTable.tsx — right-rail STATISTICS table
 *
 * WHY THIS EXISTS: PRD-0088 §6.7.2 / PLAN-0090 T-B-03 specify a Finviz-density
 * 26-row + 5-divider stats panel on the right 40% of the Quote tab. Every row
 * is a 22px MetricRow that fuses four S9 sources (Fundamentals,
 * FundamentalsSnapshot, TechnicalsData, ShareStatisticsData) into a single
 * scrollable column — "one glance, one grid".
 *
 * W5-T-15 refactor: the first 24 metric rows replaced by 3 × MetricGrid4Col
 * blocks (VALUATION / MARGINS / LEVERAGE+YIELD — 8 cells each, 4 cols × 2 rows).
 * WHY 4-col grid: halves vertical height vs the old single-column rows, reaching
 * Δ37 density target (24 cells above-fold on 1080p). Remaining rows (52W,
 * ownership, MA, analyst) stay as MetricRow for their unique sub-components
 * (WeekRangeBar, AnalystMiniBar).
 *
 * WHY no inline useQuery: PLAN-0090 T-A-03 mandates `useMetricsTableData` as
 * the SOLE data hook. Inline queries would duplicate keys with the Financials
 * tab and break TanStack Query's dedup contract.
 *
 * COLOUR THRESHOLDS: all helpers map 1:1 to PRD-0088 FR-10 (see per-row WHY).
 * DESIGN REF: PRD-0088 §6.7.2, PLAN-0090 §T-B-03; W5-T-15.
 */

"use client";

import { useMetricsTableData } from "@/components/instrument/hooks/useMetricsTableData";
import { MetricRow, type MetricValueColor } from "./MetricRow";
import { MetricGroupDivider } from "./MetricGroupDivider";
import { MetricGrid4Col } from "./MetricGrid4Col";
import { WeekRangeBar } from "./WeekRangeBar";
import { AnalystMiniBar } from "./AnalystMiniBar";
import { formatMarketCap, formatPercent, formatPrice, formatRatio, formatVolume } from "@/lib/utils";
import type { Fundamentals, Quote, ShareStatisticsData, TechnicalsData } from "@/types/api";

interface MetricsTableProps {
  instrumentId: string;
  // WHY no longer reads fundamentals from a prop (PLAN-0090 follow-up 2026-05-20):
  // the page-bundle overview.fundamentals only carries 5 fields. We now pull the
  // full Fundamentals shape from useMetricsTableData (which calls getFundamentals
  // directly, sharing the cache key with the Financials tab). The prop is kept
  // OPTIONAL for migration safety — if a caller passes one, it acts as a fast-path
  // seed but the hook's value takes precedence as soon as it resolves.
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

/** Sign colour — EPS/ROA positive/negative split. */
const signColor = (v: number | null | undefined): MetricValueColor =>
  v == null ? "default" : v >= 0 ? "positive" : "negative";

/** Price-vs-MA trend: green when current >= MA (uptrend), red when below. */
const trendColor = (p: number | null, m: number | null): MetricValueColor =>
  p == null || m == null ? "default" : p >= m ? "positive" : "negative";

export function MetricsTable({ instrumentId, fundamentals: fundamentalsProp, quote }: MetricsTableProps) {
  // WHY one hook: all four sub-resources share a single loading surface;
  // undefined fields render "—" via MetricValue automatically.
  const {
    fundamentals: fundamentalsFromHook,
    snapshot,
    technicals: technicalsResp,
    shareStats: shareStatsResp,
  } = useMetricsTableData(instrumentId);
  // WHY hook-wins coalesce: the prop (when provided) is the slim page-bundle
  // shape — only safe to use until the hook's rich /v1/fundamentals/{id} fetch
  // resolves. Once that lands we switch to the full object so the 16 rows that
  // depend on margin/roe/leverage/analyst fields populate.
  const fundamentals: Fundamentals | null = fundamentalsFromHook ?? fundamentalsProp ?? null;

  // WHY records[0].data cast: getTechnicals/getShareStatistics return a raw
  // FundamentalsSectionResponse envelope; the typed shape lives on records[0]
  // per the EODHD section convention. Cast once so 26 rows stay terse.
  const technicals = (technicalsResp?.records?.[0]?.data ?? null) as TechnicalsData | null;
  const shareStats = (shareStatsResp?.records?.[0]?.data ?? null) as ShareStatisticsData | null;

  const price = quote?.price ?? null;
  // WHY string-key access AND PascalCase: TechnicalsData (see types/api.ts)
  // mirrors the EODHD-verbatim payload returned by S9 /v1/fundamentals/{id}/technicals.
  // Keys begin with digits ("50DayMA") so they can't be JS identifiers —
  // bracket access is mandatory. Audit 2026-05-19 confirmed live keys: 50DayMA, 200DayMA.
  const ma50 = technicals?.["50DayMA"] ?? null;
  const ma200 = technicals?.["200DayMA"] ?? null;
  // WHY raw-percent normalization for ownership fields: ShareStatisticsData
  // returns PercentInsiders / PercentInstitutions as already-multiplied magnitudes
  // (1.64 = 1.64%, 65.35 = 65.35%) per EODHD. formatPercent itself multiplies by
  // 100, so we divide by 100 first to keep the round-trip honest.
  const pctInsiders = shareStats?.PercentInsiders != null ? shareStats.PercentInsiders / 100 : null;
  const pctInstitutions =
    shareStats?.PercentInstitutions != null ? shareStats.PercentInstitutions / 100 : null;
  // ShortPercent is already a decimal (0.0092 = 0.92%) per EODHD — pass through.
  const shortPct = technicals?.ShortPercent ?? null;
  // Arrow suffix — visual trend cue (PRD §6.7.2 rows 24/25).
  const arrow = (p: number | null, m: number | null) =>
    p == null || m == null ? "" : p >= m ? " ↑" : " ↓";

  // Analyst target upside vs current price — null when either side missing.
  const target = fundamentals?.analyst_target_price ?? null;
  const upside = target != null && price != null && price > 0 ? (target - price) / price : null;

  return (
    <div className="w-full h-full flex flex-col border-l border-border overflow-y-auto">
      {/* Section header — 28px (h-7), 10px caps per PRD §6.7.2. */}
      <div className="flex items-center h-7 px-3 border-b border-border/50 bg-card/50 text-[10px] uppercase tracking-wide text-muted-foreground">
        Statistics
      </div>

      {/* ── VALUATION block (4 cols × 2 rows = 8 cells) — W5-T-15 (Δ37) ──── */}
      <MetricGrid4Col
        title="Valuation"
        cells={[
          { label: "MKT CAP",  value: formatMarketCap(fundamentals?.market_cap ?? null) },
          { label: "P/E",      value: formatRatio(fundamentals?.pe_ratio ?? null, ""),    color: peColor(fundamentals?.pe_ratio) },
          { label: "FWD P/E",  value: formatRatio(fundamentals?.forward_pe ?? null, ""), color: peColor(fundamentals?.forward_pe) },
          { label: "EPS TTM",  value: formatPrice(snapshot?.eps_ttm ?? null),            color: signColor(snapshot?.eps_ttm) },
          { label: "P/S",      value: formatRatio(fundamentals?.price_to_sales ?? null, "") },
          { label: "P/B",      value: formatRatio(fundamentals?.price_to_book ?? null, "") },
          { label: "EV/EBITDA",value: formatRatio(fundamentals?.ev_to_ebitda ?? null, "") },
          { label: "FCF",      value: formatMarketCap(snapshot?.free_cash_flow ?? null) },
        ]}
      />

      {/* ── MARGINS block (4 cols × 2 rows = 8 cells) ───────────────────── */}
      <MetricGrid4Col
        title="Margins"
        cells={[
          { label: "GROSS",    value: formatPercent(fundamentals?.gross_margin ?? null) },
          { label: "OPER",     value: formatPercent(fundamentals?.operating_margin ?? null) },
          { label: "NET",      value: formatPercent(fundamentals?.net_margin ?? null),  color: netMarginColor(fundamentals?.net_margin) },
          { label: "FCF MGN",  value: formatPercent(snapshot?.fcf_margin ?? null) },
          { label: "ROE",      value: formatPercent(fundamentals?.roe ?? null),         color: roeColor(fundamentals?.roe) },
          { label: "ROA",      value: formatPercent(fundamentals?.roa ?? null),         color: signColor(fundamentals?.roa) },
          { label: "REV GRW",  value: formatPercent(fundamentals?.revenue_growth_yoy ?? null),  color: signColor(fundamentals?.revenue_growth_yoy) },
          { label: "EPS GRW",  value: formatPercent(fundamentals?.earnings_growth_yoy ?? null), color: signColor(fundamentals?.earnings_growth_yoy) },
        ]}
      />

      {/* ── LEVERAGE + YIELD block (4 cols × 2 rows = 8 cells) ──────────── */}
      <MetricGrid4Col
        title="Leverage / Yield"
        cells={[
          { label: "D/E",      value: formatRatio(fundamentals?.debt_to_equity ?? null),  color: debtColor(fundamentals?.debt_to_equity) },
          { label: "CURR",     value: formatRatio(fundamentals?.current_ratio ?? null) },
          { label: "QUICK",    value: formatRatio(fundamentals?.quick_ratio ?? null) },
          { label: "INT COV",  value: snapshot?.interest_coverage != null ? snapshot.interest_coverage.toFixed(1) : null },
          { label: "DIV YLD",  value: formatPercent(fundamentals?.dividend_yield ?? null) },
          { label: "PAYOUT",   value: formatPercent(fundamentals?.payout_ratio ?? null) },
          { label: "BETA",     value: snapshot?.beta != null ? snapshot.beta.toFixed(2) : null, color: betaColor(snapshot?.beta) },
          { label: "SHORT %",  value: formatPercent(shortPct), color: shortColor(shortPct) },
        ]}
      />

      {/* ── 52W RANGE (rows 17-19) — full-width WeekRangeBar at row 19 ────── */}
      <MetricRow label="52W HIGH" value={formatPrice(fundamentals?.week_52_high ?? null)} />
      <MetricRow label="52W LOW" value={formatPrice(fundamentals?.week_52_low ?? null)} />
      <WeekRangeBar high={fundamentals?.week_52_high ?? null} low={fundamentals?.week_52_low ?? null} current={price} />
      <MetricGroupDivider />

      {/* ── OWNERSHIP (rows 20-22) ── SHORT% now in LEV/YIELD grid (Δ40) ─── */}
      <MetricRow label="AVG VOL 30D" value={formatVolume(snapshot?.avg_volume_30d ?? null)} />
      {/* INST/INSIDER OWN: normalized above (raw% ÷ 100) before passing to formatPercent. */}
      <MetricRow label="INST OWN" value={formatPercent(pctInstitutions)} />
      <MetricRow label="INSIDER OWN" value={formatPercent(pctInsiders)} />
      <MetricGroupDivider />

      {/* ── TREND (rows 24-25) — MA values with ↑/↓ vs current price ──────── */}
      <MetricRow label="MA 50" value={ma50 != null ? `${formatPrice(ma50)}${arrow(price, ma50)}` : null} color={trendColor(price, ma50)} />
      <MetricRow label="MA 200" value={ma200 != null ? `${formatPrice(ma200)}${arrow(price, ma200)}` : null} color={trendColor(price, ma200)} />
      <MetricGroupDivider />

      {/* ── CONSENSUS (rows 26-27) — analyst bar + price target ───────────── */}
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
