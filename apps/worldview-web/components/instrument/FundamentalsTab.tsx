/**
 * components/instrument/FundamentalsTab.tsx — Fundamentals metrics grid
 *
 * WHY THIS EXISTS: Fundamental analysis is the primary due-diligence step for
 * portfolio managers. They need P/E, margins, debt ratios, and growth metrics
 * before making allocation decisions. Bloomberg users expect dense tabular
 * data — not summary cards with large whitespace.
 *
 * WHY SECTIONS: Finance data has natural groupings (Valuation / Profitability /
 * Growth / Dividends / Balance Sheet). Grouping reduces cognitive load for
 * analysts who only care about one category at a time.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Fundamentals tab)
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId}
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail Fundamentals tab, State C-3
 */

"use client";
// WHY "use client": uses useQuery (state), though the component itself has no
// browser-only APIs — "use client" is needed because useQuery requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import {
  formatRatio,
  formatPercent,
  formatMarketCap,
  formatPrice,
  formatRelativeTime,
  priceChangeClass,
} from "@/lib/utils";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface FundamentalsTabProps {
  instrumentId: string;
  /** Prefetched fundamentals from CompanyOverview — shown while full data loads */
  initialData?: Fundamentals | null;
}

// ── Color helpers ─────────────────────────────────────────────────────────────

/**
 * getMetricClass — returns a Tailwind text-color class based on numeric thresholds
 *
 * WHY this pattern: Bloomberg and Finviz both color-code metrics so analysts can
 * scan a dense grid and spot outliers without reading every number. Red/amber/green
 * traffic-light encoding is the finance industry standard.
 *
 * WHY null-safe: The Fundamentals type has many nullable fields (data may not be
 * available for ETFs, SPACs, or recently listed instruments). Missing data must
 * always render as "—" in muted text, never crash.
 *
 * @param value      The raw numeric value to evaluate (null → muted fallback)
 * @param greenBelow If non-null, values BELOW this threshold are colored green
 * @param redAbove   If non-null, values ABOVE this threshold are colored red
 *                   Values between greenBelow and redAbove are amber (cautionary)
 */
function getMetricClass(
  value: number | null,
  greenBelow: number | null,
  redAbove: number | null,
): string {
  if (value == null) return "text-muted-foreground";
  // WHY check redAbove first: it's the stronger signal (analyst concern > praise)
  if (redAbove != null && value > redAbove) return "text-negative";
  if (greenBelow != null && value < greenBelow) return "text-positive";
  // Amber = in-between — not great, not terrible; Tailwind's amber-400 in dark mode
  // WHY amber-400 not amber-500: 500 is too orange against the dark #0A0E14 background
  // WHY text-warning not text-amber-400: --warning (#F59E0B) is the design system
  // token for cautionary signals. Using raw Tailwind amber-400 bypasses the token
  // and breaks if the warning color changes in globals.css.
  return "text-warning";
}

/**
 * getMarginClass — color P&L margin ratios (higher is better)
 *
 * WHY separate from getMetricClass: margins are "higher is better" (the opposite
 * direction from P/E or debt ratios). Separating avoids negating thresholds everywhere.
 *
 * @param value        Raw decimal margin (0.45 = 45%)
 * @param greenAbove   Values ABOVE this are green (good margin)
 * @param redBelow     Values BELOW this are red (poor margin)
 */
function getMarginClass(
  value: number | null,
  greenAbove: number | null,
  redBelow: number | null,
): string {
  if (value == null) return "text-muted-foreground";
  if (greenAbove != null && value > greenAbove) return "text-positive";
  if (redBelow != null && value < redBelow) return "text-negative";
  // WHY text-warning not text-amber-400: --warning (#F59E0B) is the design system
  // token for cautionary signals. Using raw Tailwind amber-400 bypasses the token
  // and breaks if the warning color changes in globals.css.
  return "text-warning";
}

// ── Metric row sub-component ──────────────────────────────────────────────────

/**
 * MetricRow — single label/value pair in a fundamentals section
 *
 * WHY inline: This component is only used inside FundamentalsTab.
 * Exporting it separately would invite misuse in other contexts where
 * the formatting conventions might not apply.
 *
 * WHY valueClass prop: The color of the value depends on domain-specific
 * threshold logic (P/E vs margin vs growth), so callers pass the pre-computed
 * class rather than duplicating threshold logic here. This keeps MetricRow
 * a pure presentation component.
 *
 * WHY children for value: Some rows need compound JSX (e.g., daily_return with
 * a ▲/▼ triangle prefix). Using children instead of a plain string value prop
 * accommodates both simple strings and rich JSX without forking the component.
 */
function MetricRow({
  label,
  children,
  unit,
}: {
  label: string;
  children: React.ReactNode;
  unit?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-xs tabular-nums">
        {children}
        {/* WHY conditional unit: only show unit suffix when there's an actual value,
            not when the value is "—" (the unit would float next to the dash) */}
        {unit ? (
          <span className="text-muted-foreground"> {unit}</span>
        ) : null}
      </span>
    </div>
  );
}

// ── Section sub-component ─────────────────────────────────────────────────────

/**
 * Section — groups related metrics under a labelled heading
 *
 * WHY border-b on h3: The original heading used muted/60 opacity which was too
 * subtle for Bloomberg-density layouts. A bottom border creates a visible shelf
 * that separates the heading from rows without taking up vertical space with a
 * gap. The border uses border/40 to match the surrounding divide lines in MetricRow.
 *
 * WHY pb-1 mb-2: The padding keeps the text visually above the border rule;
 * the margin creates breathing room before the first data row.
 */
function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      {/* Section heading — border-b replaces the old opacity-60 which was too faint */}
      <h3 className="mb-2 border-b border-border/40 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {title}
      </h3>
      <div className="divide-y divide-border/40">{children}</div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FundamentalsTab({ instrumentId, initialData }: FundamentalsTabProps) {
  const { accessToken } = useAuth();

  const { data: fund, isLoading, isError } = useQuery({
    queryKey: ["fundamentals", instrumentId],
    queryFn: () => createGateway(accessToken).getFundamentals(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    // WHY 5min stale: fundamentals update once/day; no need to refetch aggressively
    staleTime: 5 * 60_000,
    placeholderData: initialData ?? undefined,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading && !fund) {
    return (
      <div className="space-y-4 p-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-3 w-24" />
            {Array.from({ length: 3 }).map((_, j) => (
              <Skeleton key={j} className="h-4 w-full" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (isError || !fund) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Fundamentals unavailable. Data may not be loaded yet.
      </div>
    );
  }

  // ── Render metrics grid ────────────────────────────────────────────────────
  // WHY grid-cols-2 lg:grid-cols-3: 2-column layout fills the panel at tablet
  // widths (no wasted whitespace), 3-column at large screens matches Bloomberg
  // DES page density. The old sm:grid-cols-2 left a single-column layout on
  // mobile which felt too sparse for dense financial data.
  return (
    <div className="flex flex-col">
      {/* WHY gap-2 p-3 (was gap-6 p-4): tighter spacing increases data density.
          gap-6 (24px) between sections is too wide for a terminal grid; gap-2 (8px)
          keeps sections close while the section border/header provides visual separation.
          p-3 (12px) is the standard terminal panel padding per design system. */}
      <div className="grid grid-cols-2 gap-2 p-3 lg:grid-cols-3">
        {/* ── Valuation ──────────────────────────────────────────────────── */}
        <Section title="Valuation">
          {/* Market cap: no color threshold — it's a scale metric, not good/bad */}
          <MetricRow label="Market Cap">
            <span className="text-foreground">{formatMarketCap(fund.market_cap)}</span>
          </MetricRow>

          {/* P/E: green <20 (cheap), amber 20-35 (fair), red >35 (expensive)
              These thresholds follow the Graham/Damodaran value investing conventions */}
          <MetricRow label="P/E Ratio">
            <span className={getMetricClass(fund.pe_ratio, 20, 35)}>
              {formatRatio(fund.pe_ratio)}
            </span>
          </MetricRow>

          {/* Forward P/E: same thresholds as trailing P/E */}
          <MetricRow label="Forward P/E">
            <span className={getMetricClass(fund.forward_pe, 20, 35)}>
              {formatRatio(fund.forward_pe)}
            </span>
          </MetricRow>

          {/* Price/Book: green <1 (below book value), amber 1-3, red >3
              WHY 3 as red: P/B > 3 typically signals significant premium to assets */}
          <MetricRow label="Price / Book">
            <span className={getMetricClass(fund.price_to_book, 1, 3)}>
              {formatRatio(fund.price_to_book)}
            </span>
          </MetricRow>

          {/* Price/Sales: no strong threshold consensus — render neutral */}
          <MetricRow label="Price / Sales">
            <span className="text-foreground">{formatRatio(fund.price_to_sales)}</span>
          </MetricRow>

          {/* EV/EBITDA: green <10 (cheap), amber 10-20, red >20
              WHY 10/20: typical LBO/acquisition screening cutoffs */}
          <MetricRow label="EV / EBITDA">
            <span className={getMetricClass(fund.ev_to_ebitda, 10, 20)}>
              {formatRatio(fund.ev_to_ebitda)}
            </span>
          </MetricRow>
        </Section>

        {/* ── Profitability ───────────────────────────────────────────────── */}
        <Section title="Profitability">
          {/* Gross margin: green >40%, amber 20-40%, red <20%
              WHY formatPercent: API returns decimal 0.4523 for 45.23% */}
          <MetricRow label="Gross Margin">
            <span className={getMarginClass(fund.gross_margin, 0.40, 0.20)}>
              {formatPercent(fund.gross_margin)}
            </span>
          </MetricRow>

          {/* Operating margin: green >15%, amber 5-15%, red <5%
              WHY 15%: industry-wide healthy operating leverage benchmark */}
          <MetricRow label="Operating Margin">
            <span className={getMarginClass(fund.operating_margin, 0.15, 0.05)}>
              {formatPercent(fund.operating_margin)}
            </span>
          </MetricRow>

          {/* Net margin: green >10%, amber 3-10%, red <3% */}
          <MetricRow label="Net Margin">
            <span className={getMarginClass(fund.net_margin, 0.10, 0.03)}>
              {formatPercent(fund.net_margin)}
            </span>
          </MetricRow>

          {/* ROE: green >15%, amber 8-15%, red <8%
              WHY 15%: Warren Buffett's minimum return threshold for durable advantage */}
          <MetricRow label="ROE">
            <span className={getMarginClass(fund.roe, 0.15, 0.08)}>
              {formatPercent(fund.roe)}
            </span>
          </MetricRow>

          {/* ROA: green >5%, amber 2-5%, red <2% */}
          <MetricRow label="ROA">
            <span className={getMarginClass(fund.roa, 0.05, 0.02)}>
              {formatPercent(fund.roa)}
            </span>
          </MetricRow>
        </Section>

        {/* ── Growth ─────────────────────────────────────────────────────── */}
        <Section title="Growth (YoY)">
          {/* Revenue growth: green >10%, amber 0-10%, red <0%
              WHY priceChangeClass fallback: growth direction is the primary signal;
              the magnitude thresholds below layer on additional nuance */}
          <MetricRow label="Revenue Growth">
            <span className={getMarginClass(fund.revenue_growth_yoy, 0.10, 0)}>
              {formatPercent(fund.revenue_growth_yoy)}
            </span>
          </MetricRow>

          {/* Earnings growth: same threshold as revenue growth */}
          <MetricRow label="Earnings Growth">
            <span className={getMarginClass(fund.earnings_growth_yoy, 0.10, 0)}>
              {formatPercent(fund.earnings_growth_yoy)}
            </span>
          </MetricRow>
        </Section>

        {/* ── Dividends ──────────────────────────────────────────────────── */}
        <Section title="Dividends">
          {/* Dividend yield: green >3% (income stock), amber 1-3%, neutral <1%
              WHY 3%: classic income threshold used by dividend ETF screeners */}
          <MetricRow label="Dividend Yield">
            <span className={getMarginClass(fund.dividend_yield, 0.03, null)}>
              {formatPercent(fund.dividend_yield)}
            </span>
          </MetricRow>

          {/* Payout ratio: green <50% (sustainable), amber 50-80%, red >80%
              WHY 80% as red: payout > 80% risks dividend cut on an earnings miss */}
          <MetricRow label="Payout Ratio">
            <span className={getMetricClass(fund.payout_ratio, 0.50, 0.80)}>
              {formatPercent(fund.payout_ratio)}
            </span>
          </MetricRow>
        </Section>

        {/* ── Balance Sheet ───────────────────────────────────────────────── */}
        <Section title="Balance Sheet">
          {/* Debt/Equity: green <1.0, amber 1.0-2.0, red >2.0
              WHY 2.0: highly levered territory; default risk increases sharply above 2x */}
          <MetricRow label="Debt / Equity">
            <span className={getMetricClass(fund.debt_to_equity, 1.0, 2.0)}>
              {formatRatio(fund.debt_to_equity)}
            </span>
          </MetricRow>

          {/* Current ratio: green >2.0 (strong liquidity), amber 1.0-2.0, red <1.0
              WHY 1.0 as red: below 1.0 means current liabilities exceed current assets */}
          <MetricRow label="Current Ratio">
            <span className={getMarginClass(fund.current_ratio, 2.0, 1.0)}>
              {formatRatio(fund.current_ratio)}
            </span>
          </MetricRow>

          {/* Quick ratio: green >1.0, amber 0.5-1.0, red <0.5
              WHY: quick ratio excludes inventory — stricter liquidity measure */}
          <MetricRow label="Quick Ratio">
            <span className={getMarginClass(fund.quick_ratio, 1.0, 0.5)}>
              {formatRatio(fund.quick_ratio)}
            </span>
          </MetricRow>
        </Section>

        {/* ── 52-Week Range ───────────────────────────────────────────────── */}
        <Section title="52-Week Range">
          {/* 52W High/Low: no directional coloring — they're reference values, not signals */}
          <MetricRow label="52-Week High">
            <span className="text-foreground">{formatPrice(fund.week_52_high)}</span>
          </MetricRow>
          <MetricRow label="52-Week Low">
            <span className="text-foreground">{formatPrice(fund.week_52_low)}</span>
          </MetricRow>

          {/* Daily return: ▲/▼ triangle prefix + priceChangeClass from lib/utils
              WHY show here: context anchors the 52W range — the triangle direction
              tells the analyst at a glance whether today's move is notable vs range */}
          <MetricRow label="Daily Return">
            {fund.daily_return != null ? (
              <span className={priceChangeClass(fund.daily_return)}>
                {/* WHY Unicode triangle: standard Bloomberg visual for direction;
                    avoids an SVG icon which would misalign in monospace tabular context */}
                {fund.daily_return >= 0 ? "▲" : "▼"}{" "}
                {formatPercent(fund.daily_return)}
              </span>
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </MetricRow>
        </Section>
      </div>

      {/* ── Data quality footer ─────────────────────────────────────────────
          WHY this footer: Bloomberg terminals display data source + timestamp
          on every data panel. Analysts need to know when the data was last
          refreshed to assess if a stale fundamental is distorting the picture
          (e.g., during earnings season). The muted/50 opacity keeps it clearly
          subordinate to the data above — it's reference info, not a headline. */}
      <p className="mx-4 mt-4 border-t border-border/40 pt-2 text-[10px] text-muted-foreground/50">
        Data sourced from S3 fundamentals pipeline · Updated {formatRelativeTime(fund.updated_at)}
      </p>
    </div>
  );
}
