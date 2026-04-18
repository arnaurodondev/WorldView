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
} from "@/lib/utils";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface FundamentalsTabProps {
  instrumentId: string;
  /** Prefetched fundamentals from CompanyOverview — shown while full data loads */
  initialData?: Fundamentals | null;
}

// ── Metric row sub-component ──────────────────────────────────────────────────

/**
 * MetricRow — single label/value pair in a fundamentals section
 *
 * WHY inline: This component is only used inside FundamentalsTab.
 * Exporting it separately would invite misuse in other contexts where
 * the formatting conventions might not apply.
 */
function MetricRow({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-xs tabular-nums text-foreground">
        {value}
        {unit && value !== "—" ? (
          <span className="text-muted-foreground"> {unit}</span>
        ) : null}
      </span>
    </div>
  );
}

// ── Section sub-component ─────────────────────────────────────────────────────

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      {/* Section heading with subtle separator — matches Bloomberg category labels */}
      <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
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
  return (
    <div className="grid grid-cols-1 gap-6 p-4 sm:grid-cols-2">
      {/* ── Valuation ────────────────────────────────────────────────────── */}
      <Section title="Valuation">
        <MetricRow label="Market Cap" value={formatMarketCap(fund.market_cap)} />
        <MetricRow label="P/E Ratio" value={formatRatio(fund.pe_ratio)} />
        <MetricRow label="Forward P/E" value={formatRatio(fund.forward_pe)} />
        <MetricRow label="Price / Book" value={formatRatio(fund.price_to_book)} />
        <MetricRow label="Price / Sales" value={formatRatio(fund.price_to_sales)} />
        <MetricRow label="EV / EBITDA" value={formatRatio(fund.ev_to_ebitda)} />
      </Section>

      {/* ── Profitability ─────────────────────────────────────────────────── */}
      <Section title="Profitability">
        {/* WHY formatPercent with /100: API returns e.g. 0.4523 for 45.23% */}
        <MetricRow label="Gross Margin" value={formatPercent(fund.gross_margin)} />
        <MetricRow label="Operating Margin" value={formatPercent(fund.operating_margin)} />
        <MetricRow label="Net Margin" value={formatPercent(fund.net_margin)} />
        <MetricRow label="ROE" value={formatPercent(fund.roe)} />
        <MetricRow label="ROA" value={formatPercent(fund.roa)} />
      </Section>

      {/* ── Growth ───────────────────────────────────────────────────────── */}
      <Section title="Growth (YoY)">
        <MetricRow label="Revenue Growth" value={formatPercent(fund.revenue_growth_yoy)} />
        <MetricRow label="Earnings Growth" value={formatPercent(fund.earnings_growth_yoy)} />
      </Section>

      {/* ── Dividends ────────────────────────────────────────────────────── */}
      <Section title="Dividends">
        <MetricRow label="Dividend Yield" value={formatPercent(fund.dividend_yield)} />
        <MetricRow label="Payout Ratio" value={formatPercent(fund.payout_ratio)} />
      </Section>

      {/* ── Balance Sheet ─────────────────────────────────────────────────── */}
      <Section title="Balance Sheet">
        <MetricRow label="Debt / Equity" value={formatRatio(fund.debt_to_equity)} />
        <MetricRow label="Current Ratio" value={formatRatio(fund.current_ratio)} />
        <MetricRow label="Quick Ratio" value={formatRatio(fund.quick_ratio)} />
      </Section>

      {/* ── 52-Week Range ─────────────────────────────────────────────────── */}
      <Section title="52-Week Range">
        <MetricRow label="52-Week High" value={formatPrice(fund.week_52_high)} />
        <MetricRow label="52-Week Low" value={formatPrice(fund.week_52_low)} />
        {/* WHY show daily return here: context anchors the 52W range */}
        <MetricRow label="Daily Return" value={formatPercent(fund.daily_return)} />
      </Section>
    </div>
  );
}
