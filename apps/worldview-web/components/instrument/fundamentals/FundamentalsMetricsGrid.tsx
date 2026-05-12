/**
 * components/instrument/fundamentals/FundamentalsMetricsGrid.tsx
 * — 9-section metric grid for fundamental analysis (Valuation / Profitability / Growth /
 *   Dividends / Balance Sheet / 52-Week Range / Debt & Credit / Cash Flow)
 *
 * WHY EXTRACTED: FundamentalsTab.tsx was 928 lines. The metric grid itself is the
 * largest single region. Extracting it to its own file makes each file ≤400 lines
 * and separates data fetching (FundamentalsTab) from metric rendering (this file).
 *
 * WHY 9 SECTIONS: Wave 5 adds Analyst Consensus + Revenue Trend (full-width above
 * the grid) and Debt & Credit + Cash Flow (in the grid). Matches Bloomberg DES density.
 *
 * COLOR CODING:
 *   getMetricClass(v, greenBelow, redAbove) — lower is better (P/E, debt ratios)
 *   getMarginClass(v, greenAbove, redBelow) — higher is better (margins, ROE)
 *
 * WHO USES IT: FundamentalsTab.tsx — never directly by pages.
 */

import { AlertTriangle } from "lucide-react";
import {
  formatRatio,
  formatPercent,
  formatMarketCap,
  formatPrice,
  priceChangeClass,
} from "@/lib/utils";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";
import { FundamentalSparkline } from "@/components/instrument/FundamentalSparkline";
import { WeekRangeBar } from "@/components/instrument/52WeekRangeBar";
import { getMetricClass, getMarginClass } from "./fundamentals-helpers";

// ── MissingValue ──────────────────────────────────────────────────────────────
// WHY native title: keeps the component dependency-free; works under SSR without
// hydration friction. Distinguishes "missing for this ticker" from "globally unavailable".
function MissingValue() {
  return (
    <span className="cursor-help text-muted-foreground" title="Not available for this ticker">—</span>
  );
}

// ── MetricRow ─────────────────────────────────────────────────────────────────
// WHY h-[22px]: terminal-standard row height. WHY children (not value prop):
// some rows need compound JSX (e.g., daily_return ▲/▼ triangle prefix).
function MetricRow({ label, children, unit }: { label: string; children: React.ReactNode; unit?: string }) {
  return (
    <div className="flex h-[22px] items-center justify-between gap-4">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
      <span className="font-mono text-[11px] tabular-nums">
        {children}
        {unit ? <span className="text-muted-foreground"> {unit}</span> : null}
      </span>
    </div>
  );
}

// ── Section ───────────────────────────────────────────────────────────────────
// WHY bg-card border rounded-[2px]: elevated cards create visual hierarchy so analysts
// can distinguish 9 section groups in the dense metric grid — same pattern as Bloomberg
// DES section boxes. WHY overflow-hidden: rounded corner clip needs this on parent.
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">
      <div className="border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">{title}</span>
      </div>
      <div className="px-2 divide-y divide-border/40">{children}</div>
    </div>
  );
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface FundamentalsMetricsGridProps {
  fund: Fundamentals;
  snapshot?: FundamentalsSnapshot;
  instrumentId: string;
  currentPrice?: number | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FundamentalsMetricsGrid({
  fund,
  snapshot,
  instrumentId,
  currentPrice,
}: FundamentalsMetricsGridProps) {
  // ── PLAN-0053 T-C-3-03: coverage banner (>30% null snapshot fields) ────────
  const SNAPSHOT_FIELDS = ["eps_ttm", "beta", "avg_volume_30d", "operating_cash_flow", "capex",
    "free_cash_flow", "fcf_margin", "interest_coverage", "net_debt_to_ebitda", "credit_rating"] as const;
  const nullFieldCount = snapshot
    ? SNAPSHOT_FIELDS.filter((f) => snapshot[f as keyof FundamentalsSnapshot] == null).length
    : 0;
  const showCoverageBanner = snapshot != null && nullFieldCount / SNAPSHOT_FIELDS.length > 0.3;

  return (
    <>
      {showCoverageBanner && (
        <div role="status" className="border-b border-warning/30 bg-warning/10 px-3 py-1.5 text-[11px] text-warning">
          <AlertTriangle className="h-3 w-3 text-warning shrink-0 inline mr-1" strokeWidth={1.5} />
          <span className="font-mono uppercase tracking-wider text-[10px] mr-2">Limited coverage</span>
          Coverage for this ticker is limited ({nullFieldCount} of {SNAPSHOT_FIELDS.length} key
          metrics unavailable from current data providers).
        </div>
      )}

      {/* ── Metric grid — md:grid-cols-2 is max density keeping all rows readable ── */}
      <div className="grid grid-cols-2 gap-2 p-3">

        {/* ── Valuation ────────────────────────────────────────────────────── */}
        <Section title="Valuation">
          {/* Market cap: scale metric — no directional color */}
          <MetricRow label="Market Cap">
            <span className="text-foreground">{formatMarketCap(fund.market_cap)}</span>
          </MetricRow>
          {/* P/E: green <20 (cheap), amber 20-35 (fair), red >35 (expensive) — Graham/Damodaran */}
          <MetricRow label="P/E Ratio">
            <span className={getMetricClass(fund.pe_ratio, 20, 35)}>{formatRatio(fund.pe_ratio)}</span>
          </MetricRow>
          {/* Sparkline: trailing P/E trend tells analysts whether multiple is expanding or compressing */}
          <div className="py-1"><FundamentalSparkline instrumentId={instrumentId} metric="pe_ratio" height={32} /></div>
          <MetricRow label="Forward P/E">
            <span className={getMetricClass(fund.forward_pe, 20, 35)}>{formatRatio(fund.forward_pe)}</span>
          </MetricRow>
          {/* P/B: green <1 (below book value), amber 1-3, red >3 (significant premium) */}
          <MetricRow label="Price / Book">
            <span className={getMetricClass(fund.price_to_book, 1, 3)}>{formatRatio(fund.price_to_book)}</span>
          </MetricRow>
          <MetricRow label="Price / Sales">
            <span className="text-foreground">{formatRatio(fund.price_to_sales)}</span>
          </MetricRow>
          {/* EV/EBITDA: green <10, amber 10-20, red >20 — LBO/acquisition screening cutoffs */}
          <MetricRow label="EV / EBITDA">
            <span className={getMetricClass(fund.ev_to_ebitda, 10, 20)}>{formatRatio(fund.ev_to_ebitda)}</span>
          </MetricRow>
        </Section>

        {/* ── Profitability ─────────────────────────────────────────────────── */}
        <Section title="Profitability">
          {/* Gross margin: green >40%, amber 20-40%, red <20% */}
          <MetricRow label="Gross Margin">
            <span className={getMarginClass(fund.gross_margin, 0.40, 0.20)}>{formatPercent(fund.gross_margin)}</span>
          </MetricRow>
          {/* Operating margin: green >15%, amber 5-15%, red <5% */}
          <MetricRow label="Operating Margin">
            <span className={getMarginClass(fund.operating_margin, 0.15, 0.05)}>{formatPercent(fund.operating_margin)}</span>
          </MetricRow>
          {/* Net margin: green >10%, amber 3-10%, red <3% */}
          <MetricRow label="Net Margin">
            <span className={getMarginClass(fund.net_margin, 0.10, 0.03)}>{formatPercent(fund.net_margin)}</span>
          </MetricRow>
          {/* ROE: green >15%, amber 8-15%, red <8% — Buffett's minimum durable advantage threshold */}
          <MetricRow label="ROE">
            <span className={getMarginClass(fund.roe, 0.15, 0.08)}>{formatPercent(fund.roe)}</span>
          </MetricRow>
          {/* ROE sparkline: trend shows whether returns are improving or deteriorating */}
          <div className="py-1"><FundamentalSparkline instrumentId={instrumentId} metric="roe" height={32} /></div>
          {/* ROA: green >5%, amber 2-5%, red <2% */}
          <MetricRow label="ROA">
            <span className={getMarginClass(fund.roa, 0.05, 0.02)}>{formatPercent(fund.roa)}</span>
          </MetricRow>
        </Section>

        {/* ── Growth (YoY) ─────────────────────────────────────────────────── */}
        <Section title="Growth (YoY)">
          {/* Revenue growth: green >10%, amber 0-10%, red <0% */}
          <MetricRow label="Revenue Growth">
            <span className={getMarginClass(fund.revenue_growth_yoy, 0.10, 0)}>{formatPercent(fund.revenue_growth_yoy)}</span>
          </MetricRow>
          <MetricRow label="Earnings Growth">
            <span className={getMarginClass(fund.earnings_growth_yoy, 0.10, 0)}>{formatPercent(fund.earnings_growth_yoy)}</span>
          </MetricRow>
        </Section>

        {/* ── Dividends ────────────────────────────────────────────────────── */}
        <Section title="Dividends">
          {/* Dividend yield: green >3% (income stock), amber 1-3%, neutral <1% */}
          <MetricRow label="Dividend Yield">
            <span className={getMarginClass(fund.dividend_yield, 0.03, null)}>{formatPercent(fund.dividend_yield)}</span>
          </MetricRow>
          {/* Payout ratio: green <50% (sustainable), amber 50-80%, red >80% (risks cut on earnings miss) */}
          <MetricRow label="Payout Ratio">
            <span className={getMetricClass(fund.payout_ratio, 0.50, 0.80)}>{formatPercent(fund.payout_ratio)}</span>
          </MetricRow>
        </Section>

        {/* ── Balance Sheet ─────────────────────────────────────────────────── */}
        <Section title="Balance Sheet">
          {/* Debt/Equity: green <1.0, amber 1.0-2.0, red >2.0 (default risk increases sharply) */}
          <MetricRow label="Debt / Equity">
            <span className={getMetricClass(fund.debt_to_equity, 1.0, 2.0)}>{formatRatio(fund.debt_to_equity)}</span>
          </MetricRow>
          {/* Current ratio: green >2.0 (strong liquidity), amber 1.0-2.0, red <1.0 */}
          <MetricRow label="Current Ratio">
            <span className={getMarginClass(fund.current_ratio, 2.0, 1.0)}>{formatRatio(fund.current_ratio)}</span>
          </MetricRow>
          {/* Quick ratio: green >1.0, amber 0.5-1.0, red <0.5 — excludes inventory */}
          <MetricRow label="Quick Ratio">
            <span className={getMarginClass(fund.quick_ratio, 1.0, 0.5)}>{formatRatio(fund.quick_ratio)}</span>
          </MetricRow>
        </Section>

        {/* ── 52-Week Range ─────────────────────────────────────────────────── */}
        <Section title="52-Week Range">
          {/* WHY WeekRangeBar above numeric rows: visual position encodes "near lows vs highs"
              faster than two numbers — same convention as Bloomberg's range track bar. */}
          <div className="py-2">
            <WeekRangeBar low={fund.week_52_low} high={fund.week_52_high} current={currentPrice ?? null} showLabels={true} />
          </div>
          <MetricRow label="52-Week High">
            <span className="text-foreground">{formatPrice(fund.week_52_high)}</span>
          </MetricRow>
          <MetricRow label="52-Week Low">
            <span className="text-foreground">{formatPrice(fund.week_52_low)}</span>
          </MetricRow>
          {/* Daily return: ▲/▼ triangle prefix — Bloomberg convention for direction */}
          <MetricRow label="Daily Return">
            {fund.daily_return != null ? (
              <span className={priceChangeClass(fund.daily_return)}>
                {fund.daily_return >= 0 ? "▲" : "▼"}{" "}{formatPercent(fund.daily_return)}
              </span>
            ) : <MissingValue />}
          </MetricRow>
        </Section>

        {/* ── Debt & Credit ─────────────────────────────────────────────────── */}
        {/* WHY this section: interest coverage and Net Debt/EBITDA are the primary
            credit analyst screens for default risk. PLAN-0050 Wave D. */}
        <Section title="Debt &amp; Credit">
          {/* Interest Coverage: >3x = safe (green), <1.5x = distress (red) */}
          <MetricRow label="Interest Coverage">
            {snapshot?.interest_coverage != null ? (
              <span className={getMarginClass(snapshot.interest_coverage, 3.0, 1.5)}>
                {formatRatio(snapshot.interest_coverage)}x
              </span>
            ) : <MissingValue />}
          </MetricRow>
          {/* Net Debt/EBITDA: <2x conservative (green), >4x leveraged (red); negative = net cash */}
          <MetricRow label="Net Debt / EBITDA">
            {snapshot?.net_debt_to_ebitda != null ? (
              <span className={snapshot.net_debt_to_ebitda < 0
                ? "text-positive"
                : getMetricClass(snapshot.net_debt_to_ebitda, 2.0, 4.0)}>
                {formatRatio(snapshot.net_debt_to_ebitda)}x
              </span>
            ) : <MissingValue />}
          </MetricRow>
          {/* Credit Rating: PLAN-0053 T-C-3-03: "n/a" (not "—") for globally unavailable data */}
          <MetricRow label="Credit Rating">
            {snapshot?.credit_rating != null ? (
              <span className="text-foreground font-mono text-[11px]">{snapshot.credit_rating}</span>
            ) : (
              <span className="cursor-help text-muted-foreground"
                title="Limited coverage — credit ratings not available from current data provider">
                n/a
              </span>
            )}
          </MetricRow>
        </Section>

        {/* ── Cash Flow ─────────────────────────────────────────────────────── */}
        {/* WHY this section: cash flows are the most manipulation-resistant
            fundamentals (earnings can be smoothed; cash flows are real). PLAN-0050 Wave D. */}
        <Section title="Cash Flow">
          {/* Operating Cash Flow: raw dollar value from operations (before capex) */}
          <MetricRow label="Operating CF">
            {snapshot?.operating_cash_flow != null ? (
              <span className={snapshot.operating_cash_flow >= 0 ? "text-positive" : "text-negative"}>
                {formatMarketCap(snapshot.operating_cash_flow)}
              </span>
            ) : <MissingValue />}
          </MetricRow>
          {/* CapEx: stored as negative by EODHD — display absolute value */}
          <MetricRow label="CapEx">
            {snapshot?.capex != null ? (
              <span className="text-foreground">{formatMarketCap(Math.abs(snapshot.capex))}</span>
            ) : <MissingValue />}
          </MetricRow>
          {/* Free Cash Flow: operating_cash_flow - |capex|; positive = value-generative */}
          <MetricRow label="Free Cash Flow">
            {snapshot?.free_cash_flow != null ? (
              <span className={snapshot.free_cash_flow >= 0 ? "text-positive" : "text-negative"}>
                {formatMarketCap(snapshot.free_cash_flow)}
              </span>
            ) : <MissingValue />}
          </MetricRow>
          {/* FCF Margin: >15% = strong (green), <5% = thin (amber), <0% = burning cash (red) */}
          <MetricRow label="FCF Margin">
            {snapshot?.fcf_margin != null ? (
              <span className={getMarginClass(snapshot.fcf_margin, 0.15, 0.05)}>
                {formatPercent(snapshot.fcf_margin)}
              </span>
            ) : <MissingValue />}
          </MetricRow>
        </Section>

      </div>
    </>
  );
}
