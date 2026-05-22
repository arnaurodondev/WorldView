/**
 * components/instrument/financials/DenseMetricsGrid.tsx — 6-col dense snapshot grid
 *
 * WHY THIS EXISTS: The Financials tab redesign (iter-2) replaces the 3-col
 * FlatMetricsGrid with a 6-column Bloomberg-grade density layout. 40 cells
 * in 8 sections give analysts the full fundamentals snapshot in one screen
 * without scrolling — matching Finviz's "Stats" block in terms of information
 * per pixel. The 6-col layout fits the ~800px left column comfortably at 11px
 * monospace and is the first element visible when the Financials tab opens.
 *
 * WHY data-table-grid="dense": The F1 §16.3 CSS variable driver sets
 * --row-h: 18px (vs default 20px) and --cell-px: 6px. The MetricCell primitive
 * reads --cell-px for horizontal padding, giving tighter cells without explicit
 * px-* overrides on every cell.
 *
 * WHY F1 MetricCell (no fork): All metric cells are identical in structure
 * (label above, value below, color intent). Forking a DenseMetricCell would
 * add ~60 LOC of duplication and diverge styling from the Quote tab grid.
 *
 * WHO USES IT: FinancialsTab.tsx — Block 1 of the left column.
 * DATA SOURCE: Props from useFinancialsTabData (instrumentId → S9 fundamentals,
 *   snapshot, technicals, shareStats, splitsDividends).
 * DESIGN REFERENCE: docs/designs/0089/06-instrument-financials.md §4.1
 *   40 cells: VALUATION 6 / PROFITABILITY 6 / GROWTH 3 / BALANCE SHEET 4 /
 *             CASH FLOW 3 / DIVIDENDS 4 / OWNERSHIP (4+3 SHORTS) / TECHNICALS 6
 */

// WHY no "use client": pure presentational — receives all data as props.
// No hooks, no browser APIs. Server-safe for future RSC migration.

import { MetricCell } from "@/components/primitives/MetricCell";
import {
  formatMarketCap,
  formatRatio,
  formatPercent,
  formatDate,
  formatVolume,
  formatPrice,
} from "@/lib/utils";
import type {
  Fundamentals,
  FundamentalsSnapshot,
  TechnicalsData,
  ShareStatisticsData,
} from "@/types/api";

// ── Local types ──────────────────────────────────────────────────────────────

interface DividendsData {
  ExDividendDate?: string | null;
  DividendDate?: string | null;
}

// ── Props ────────────────────────────────────────────────────────────────────

export interface DenseMetricsGridProps {
  fundamentals: Fundamentals | null;
  snapshot: FundamentalsSnapshot | null;
  // WHY PascalCase: TechnicalsData mirrors EODHD verbatim (52WeekHigh, etc.)
  technicals: TechnicalsData | null;
  shareStats: ShareStatisticsData | null;
  dividends: DividendsData | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const DASH = "—";

function fmt(v: number | null | undefined, f: (n: number | null | undefined) => string): string {
  return v == null ? DASH : f(v);
}

type CellColor = "positive" | "negative" | "warning" | "muted" | "default";

function signColor(v: number | null | undefined): CellColor {
  if (v == null) return "muted";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "default";
}

function peColor(pe: number | null | undefined): CellColor {
  if (pe == null) return "muted";
  if (pe > 35) return "negative";
  if (pe < 20) return "positive";
  return "warning";
}

function deColor(de: number | null | undefined): CellColor {
  if (de == null) return "muted";
  if (de > 2) return "negative";
  if (de <= 0.5) return "positive";
  return "default";
}

// ── Section header row — full-width, col-span-6 ───────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    // WHY col-span-6: section header spans all 6 columns. Border-b matches the
    // default data-table-grid row divider but uses the stronger border-border
    // (not /30) so the section break is unmistakably visible when scanning.
    <div
      className="col-span-6 flex items-center border-b border-border bg-muted/20 h-[var(--row-h,18px)] px-[var(--cell-px,6px)]"
      data-metric-section={label}
    >
      <span className="text-[9px] uppercase tracking-widest text-muted-foreground/70 font-medium">
        {label}
      </span>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export function DenseMetricsGrid({
  fundamentals,
  snapshot,
  technicals,
  shareStats,
  dividends,
}: DenseMetricsGridProps) {
  return (
    // WHY data-table-grid="dense": sets --row-h: 18px and --cell-px: 6px via F1
    // §16.3 CSS. All 40 MetricCell children pick up 6px horizontal padding from
    // --cell-px, tighter than the 8px default.
    // WHY grid-cols-6: 6 equal columns, each MetricCell occupies one slot.
    // WHY gap-0: no gap between cells — dividers come from data-table-grid CSS.
    <div
      data-table-grid="dense"
      data-testid="dense-metrics-grid"
      className="grid grid-cols-6 border border-border"
    >

      {/* ── VALUATION (6 cells) ─────────────────────────────────────────── */}
      <SectionHeader label="VALUATION" />
      <MetricCell label="MKT CAP" value={fmt(fundamentals?.market_cap, formatMarketCap)} />
      <MetricCell label="P/E" value={fmt(fundamentals?.pe_ratio, formatRatio)} color={peColor(fundamentals?.pe_ratio)} />
      <MetricCell label="FWD P/E" value={fmt(fundamentals?.forward_pe, formatRatio)} color={peColor(fundamentals?.forward_pe)} />
      <MetricCell label="P/B" value={fmt(fundamentals?.price_to_book, formatRatio)} />
      <MetricCell label="P/S" value={fmt(fundamentals?.price_to_sales, formatRatio)} />
      <MetricCell label="EV/EBITDA" value={fmt(fundamentals?.ev_to_ebitda, formatRatio)} />

      {/* ── PROFITABILITY (6 cells) ─────────────────────────────────────── */}
      <SectionHeader label="PROFITABILITY" />
      <MetricCell label="GROSS MGN" value={fmt(fundamentals?.gross_margin, formatPercent)} color={signColor(fundamentals?.gross_margin)} />
      <MetricCell label="OP MGN" value={fmt(fundamentals?.operating_margin, formatPercent)} color={signColor(fundamentals?.operating_margin)} />
      <MetricCell label="NET MGN" value={fmt(fundamentals?.net_margin, formatPercent)} color={signColor(fundamentals?.net_margin)} />
      <MetricCell label="ROE" value={fmt(fundamentals?.roe, formatPercent)} color={signColor(fundamentals?.roe)} />
      <MetricCell label="ROA" value={fmt(fundamentals?.roa, formatPercent)} color={signColor(fundamentals?.roa)} />
      <MetricCell label="EPS TTM" value={snapshot?.eps_ttm != null ? formatPrice(snapshot.eps_ttm) : DASH} color={signColor(snapshot?.eps_ttm)} />

      {/* ── GROWTH (3 cells + 3 empty) ──────────────────────────────────── */}
      <SectionHeader label="GROWTH" />
      <MetricCell label="REV YOY" value={fmt(fundamentals?.revenue_growth_yoy, formatPercent)} color={signColor(fundamentals?.revenue_growth_yoy)} />
      <MetricCell label="EPS YOY" value={fmt(fundamentals?.earnings_growth_yoy, formatPercent)} color={signColor(fundamentals?.earnings_growth_yoy)} />
      <MetricCell label="FCF MGN" value={fmt(snapshot?.fcf_margin, formatPercent)} color={signColor(snapshot?.fcf_margin)} />
      {/* WHY empty placeholders (not null): keeps the 6-col grid aligned. A cell
          omitted from the grid flow would cause the next section header to fall
          mid-row, breaking the 6-col visual rhythm. */}
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── BALANCE SHEET (4 cells + 2 empty) ──────────────────────────── */}
      <SectionHeader label="BALANCE SHEET" />
      <MetricCell label="D/E" value={fmt(fundamentals?.debt_to_equity, formatRatio)} color={deColor(fundamentals?.debt_to_equity)} />
      <MetricCell label="CURR RATIO" value={fmt(fundamentals?.current_ratio, formatRatio)} />
      <MetricCell label="QUICK RATIO" value={fmt(fundamentals?.quick_ratio, formatRatio)} />
      <MetricCell label="ND/EBITDA" value={fmt(snapshot?.net_debt_to_ebitda, formatRatio)} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── CASH FLOW (3 cells + 3 empty) ──────────────────────────────── */}
      <SectionHeader label="CASH FLOW" />
      <MetricCell label="OP CF" value={fmt(snapshot?.operating_cash_flow, formatMarketCap)} />
      <MetricCell label="CAPEX" value={snapshot?.capex != null ? formatMarketCap(Math.abs(snapshot.capex)) : DASH} />
      <MetricCell label="FCF" value={fmt(snapshot?.free_cash_flow, formatMarketCap)} color={signColor(snapshot?.free_cash_flow)} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── DIVIDENDS (4 cells + 2 empty) ───────────────────────────────── */}
      <SectionHeader label="DIVIDENDS" />
      <MetricCell label="DIV YIELD" value={fmt(fundamentals?.dividend_yield, formatPercent)} color={(fundamentals?.dividend_yield ?? 0) > 0.03 ? "positive" : "default"} />
      <MetricCell label="PAYOUT" value={fmt(fundamentals?.payout_ratio, formatPercent)} />
      <MetricCell label="EX-DIV" value={dividends?.ExDividendDate ? formatDate(dividends.ExDividendDate) : DASH} />
      <MetricCell label="PAY DATE" value={dividends?.DividendDate ? formatDate(dividends.DividendDate) : DASH} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── OWNERSHIP (4 + 3 SHORTS sub-row = 7 cells + 5 empty) ────────── */}
      <SectionHeader label="OWNERSHIP" />
      {/* WHY PascalCase keys: ShareStatisticsData mirrors EODHD verbatim.
          SharesOutstanding, SharesFloat, PercentInsiders, PercentInstitutions
          are the real field names (audit 2026-05-19, Δ23). */}
      <MetricCell label="SHARES OUT" value={fmt(shareStats?.SharesOutstanding, formatMarketCap)} />
      <MetricCell label="FLOAT" value={fmt(shareStats?.SharesFloat, formatMarketCap)} />
      {/* WHY ÷ 100: PercentInsiders is raw-percent (1.64 = 1.64%); formatPercent
          multiplies by 100 — divide first to preserve the true magnitude. */}
      <MetricCell label="% INSIDERS" value={shareStats?.PercentInsiders != null ? formatPercent(shareStats.PercentInsiders / 100) : DASH} />
      <MetricCell label="% INSTIT" value={shareStats?.PercentInstitutions != null ? formatPercent(shareStats.PercentInstitutions / 100) : DASH} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      {/* SHORTS sub-row */}
      <MetricCell label="SHARES SHORT" value={fmt(technicals?.SharesShort, formatVolume)} />
      <MetricCell label="SHORT RATIO" value={fmt(technicals?.ShortRatio, formatRatio)} />
      <MetricCell label="SHORT %" value={fmt(technicals?.ShortPercent, formatPercent)} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── TECHNICALS-LITE (6 cells) ────────────────────────────────────── */}
      {/* WHY no INT COVERAGE / CREDIT RATING / DAY RETURN / RSI / ATR:
          Corners audit Δ (design doc §5): RSI/ATR are OHLCV-derived and belong
          in the chart section. INT COVERAGE and CREDIT RATING stay in FlatMetricsGrid
          which remains for the legacy quote tab. Day return is in the live header. */}
      <SectionHeader label="TECHNICALS" />
      <MetricCell label="BETA" value={snapshot?.beta != null ? snapshot.beta.toFixed(2) : DASH} />
      {/* WHY PascalCase: TechnicalsData mirrors EODHD verbatim (52WeekHigh,
          50DayMA, 200DayMA). Falls back to aggregate fundamentals if absent. */}
      <MetricCell label="52W HIGH" value={technicals?.["52WeekHigh"] != null ? formatPrice(technicals["52WeekHigh"]) : fmt(fundamentals?.week_52_high, formatPrice)} />
      <MetricCell label="52W LOW" value={technicals?.["52WeekLow"] != null ? formatPrice(technicals["52WeekLow"]) : fmt(fundamentals?.week_52_low, formatPrice)} />
      <MetricCell label="50D MA" value={technicals?.["50DayMA"] != null ? formatPrice(technicals["50DayMA"]) : DASH} />
      <MetricCell label="200D MA" value={technicals?.["200DayMA"] != null ? formatPrice(technicals["200DayMA"]) : DASH} />
      <MetricCell label="AVG VOL 30D" value={fmt(snapshot?.avg_volume_30d, formatVolume)} />

    </div>
  );
}
