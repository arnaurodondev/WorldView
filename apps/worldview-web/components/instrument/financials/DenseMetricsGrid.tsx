/**
 * components/instrument/financials/DenseMetricsGrid.tsx — 6-col dense snapshot grid
 *
 * WHY THIS EXISTS: The Financials tab redesign (iter-2) replaces the 3-col
 * FlatMetricsGrid with a 6-column Bloomberg-grade density layout. 39 cells
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
 *   39 cells: VALUATION 6 / PROFITABILITY 6 / GROWTH 3 / BALANCE SHEET 4 /
 *             CASH FLOW 3 / DIVIDENDS 4 / OWNERSHIP (4+3 SHORTS) / TECHNICALS 6
 */

// WHY no "use client": pure presentational — receives all data as props.
// No hooks, no browser APIs. Server-safe for future RSC migration.

import { MetricCell } from "@/components/primitives/MetricCell";
import {
  formatMarketCap,
  formatRatio,
  formatPercent,
  formatPercentUnsigned,
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

// COLOUR SEMANTICS (UI roadmap 2026-06-19 item #1 / A1): teal/red are reserved
// for *directional* values only (growth-over-time here). Non-directional LEVELS
// — valuation multiples (P/E, FWD P/E), profitability levels (margins, ROE,
// ROA, EPS), leverage (D/E), risk (Beta), ownership/short %, div yield — render
// neutral. "Cheap vs rich" / "good vs bad" judgements belong in peer-percentile
// heat (roadmap B3), not bull/bear colour, which must mean "moved up/down".
// The peColor/deColor threshold helpers were intentionally removed.

/**
 * Sign colour — ONLY for directional rate-of-change values (growth YoY): a
 * positive value means "grew", negative means "shrank". Null → muted.
 */
function signColor(v: number | null | undefined): CellColor {
  if (v == null) return "muted";
  if (v > 0) return "positive";
  if (v < 0) return "negative";
  return "default";
}

// ── Section header row — full-width, col-span-6 ───────────────────────────

function SectionHeader({ label }: { label: string }) {
  return (
    // WHY col-span-6: section header spans all 6 columns. Border-b matches the
    // default data-table-grid row divider but uses the stronger border-border
    // (not /30) so the section break is unmistakably visible when scanning.
    // WHY border-l-2 border-l-primary (Round-1): a 2px yellow accent bar on
    // the left edge makes section starts scannable in peripheral vision —
    // text-only headers at 9px blur into the data rows when skimming a
    // 39-cell grid. border-l-primary resolves through the --primary CSS var
    // (Terminal Dark trading yellow), never a hardcoded hex (DESIGN_SYSTEM §2).
    <div
      className="col-span-6 flex items-center border-b border-border border-l-2 border-l-primary bg-muted/20 h-[var(--row-h,18px)] px-[var(--cell-px,6px)]"
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
    // §16.3 CSS. All 39 MetricCell children pick up 6px horizontal padding from
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
      {/* P/E + FWD P/E: non-directional valuation levels → neutral (item #1). */}
      <MetricCell label="P/E" value={fmt(fundamentals?.pe_ratio, formatRatio)} />
      <MetricCell label="FWD P/E" value={fmt(fundamentals?.forward_pe, formatRatio)} />
      <MetricCell label="P/B" value={fmt(fundamentals?.price_to_book, formatRatio)} />
      <MetricCell label="P/S" value={fmt(fundamentals?.price_to_sales, formatRatio)} />
      <MetricCell label="EV/EBITDA" value={fmt(fundamentals?.ev_to_ebitda, formatRatio)} />

      {/* ── PROFITABILITY (6 cells) ─────────────────────────────────────── */}
      <SectionHeader label="PROFITABILITY" />
      {/* Margins / ROE / ROA / EPS are non-directional QUALITY levels → neutral,
          and unsigned (no "+" on an absolute level — item #1 + F-3 fix). */}
      <MetricCell label="GROSS MGN" value={fmt(fundamentals?.gross_margin, formatPercentUnsigned)} />
      <MetricCell label="OP MGN" value={fmt(fundamentals?.operating_margin, formatPercentUnsigned)} />
      <MetricCell label="NET MGN" value={fmt(fundamentals?.net_margin, formatPercentUnsigned)} />
      <MetricCell label="ROE" value={fmt(fundamentals?.roe, formatPercentUnsigned)} />
      <MetricCell label="ROA" value={fmt(fundamentals?.roa, formatPercentUnsigned)} />
      <MetricCell label="EPS TTM" value={snapshot?.eps_ttm != null ? formatPrice(snapshot.eps_ttm) : DASH} />

      {/* ── GROWTH (3 cells + 3 empty) ──────────────────────────────────── */}
      <SectionHeader label="GROWTH" />
      {/* REV YOY / EPS YOY are DIRECTIONAL (rate-of-change): keep teal/red +
          signed % so the sign and colour reinforce "grew vs shrank". */}
      <MetricCell label="REV YOY" value={fmt(fundamentals?.revenue_growth_yoy, formatPercent)} color={signColor(fundamentals?.revenue_growth_yoy)} />
      <MetricCell label="EPS YOY" value={fmt(fundamentals?.earnings_growth_yoy, formatPercent)} color={signColor(fundamentals?.earnings_growth_yoy)} />
      {/* FCF MGN is a margin LEVEL, not a direction → neutral, unsigned. */}
      <MetricCell label="FCF MGN" value={fmt(snapshot?.fcf_margin, formatPercentUnsigned)} />
      {/* WHY empty placeholders (not null): keeps the 6-col grid aligned. A cell
          omitted from the grid flow would cause the next section header to fall
          mid-row, breaking the 6-col visual rhythm. */}
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── BALANCE SHEET (4 cells + 2 empty) ──────────────────────────── */}
      <SectionHeader label="BALANCE SHEET" />
      {/* D/E is a non-directional leverage level → neutral (item #1). */}
      <MetricCell label="D/E" value={fmt(fundamentals?.debt_to_equity, formatRatio)} />
      <MetricCell label="CURR RATIO" value={fmt(fundamentals?.current_ratio, formatRatio)} />
      <MetricCell label="QUICK RATIO" value={fmt(fundamentals?.quick_ratio, formatRatio)} />
      <MetricCell label="ND/EBITDA" value={fmt(snapshot?.net_debt_to_ebitda, formatRatio)} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── CASH FLOW (3 cells + 3 empty) ──────────────────────────────── */}
      <SectionHeader label="CASH FLOW" />
      <MetricCell label="OP CF" value={fmt(snapshot?.operating_cash_flow, formatMarketCap)} />
      <MetricCell label="CAPEX" value={snapshot?.capex != null ? formatMarketCap(Math.abs(snapshot.capex)) : DASH} />
      {/* FCF is DIRECTIONAL in sign: negative free cash flow (cash burn) is a
          genuine red flag, positive is a green one — keep the sign colour. */}
      <MetricCell label="FCF" value={fmt(snapshot?.free_cash_flow, formatMarketCap)} color={signColor(snapshot?.free_cash_flow)} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />

      {/* ── DIVIDENDS (4 cells + 2 empty) ───────────────────────────────── */}
      <SectionHeader label="DIVIDENDS" />
      {/* DIV YIELD is an allocation-style LEVEL, not a direction → neutral,
          unsigned (a ">3% → green" threshold is editorial, not directional). */}
      <MetricCell label="DIV YIELD" value={fmt(fundamentals?.dividend_yield, formatPercentUnsigned)} />
      {/* PAYOUT is a ratio level → unsigned (no "+" on an absolute level). */}
      <MetricCell label="PAYOUT" value={fmt(fundamentals?.payout_ratio, formatPercentUnsigned)} />
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
      {/* Ownership %s are absolute LEVELS → unsigned (a "+1.64%" insider-own
          reads as a move; it is not — F-3 sign-on-levels fix). */}
      <MetricCell label="% INSIDERS" value={shareStats?.PercentInsiders != null ? formatPercentUnsigned(shareStats.PercentInsiders / 100) : DASH} />
      <MetricCell label="% INSTIT" value={shareStats?.PercentInstitutions != null ? formatPercentUnsigned(shareStats.PercentInstitutions / 100) : DASH} />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      <div className="h-[var(--row-h,18px)]" aria-hidden />
      {/* SHORTS sub-row */}
      <MetricCell label="SHARES SHORT" value={fmt(technicals?.SharesShort, formatVolume)} />
      <MetricCell label="SHORT RATIO" value={fmt(technicals?.ShortRatio, formatRatio)} />
      {/* SHORT % is a level → unsigned. */}
      <MetricCell label="SHORT %" value={fmt(technicals?.ShortPercent, formatPercentUnsigned)} />
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
