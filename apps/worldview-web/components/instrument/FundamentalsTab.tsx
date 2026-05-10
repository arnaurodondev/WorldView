/**
 * components/instrument/FundamentalsTab.tsx — Fundamentals metrics grid (9 sections)
 *
 * NOTE — PLAN-0071 Phase 6 P6-3 Assessment (2026-05-05):
 * P6-3 specified "Migrate financial statements table to AG Grid (Income Statement /
 * Balance Sheet / Cash Flow tabs)". After reading this file in full, P6-3 is NOT
 * APPLICABLE to this component. Here is why:
 *
 * This component contains NO multi-column time-series financial statement grids.
 * There are no "FY2022 / FY2023 / FY2024" column headers. All financial data
 * is displayed as single label+value MetricRow pairs (e.g., "Gross Margin: 45.2%").
 *
 * The appropriate AG Grid use cases are:
 *   1. Multi-column tabular data with sortable/filterable columns (screener ✅ done).
 *   2. Rows of securities/positions with live-updating cells (holdings ✅ done).
 *
 * Key-value metric rows are NOT improved by AG Grid:
 *   - MetricRow is already 22px fixed height (terminal density standard).
 *   - Section cards (Valuation, Profitability, etc.) group metrics correctly.
 *   - No benefit from AG Grid column features on a label+single-value layout.
 *   - Adding AG Grid would increase bundle size and complexity for zero UX benefit.
 *
 * Revenue trend and EPS history (time-series data) are handled separately by
 * RevenueTrendSparklines (sparkline chart) and EarningsHistoryChart (bar chart).
 * Both are more appropriate than a grid for historical financial trend display.
 *
 * Decision: P6-3 is N/A. Current MetricRow display is correct and optimal.
 *
 * WHY THIS EXISTS: Fundamental analysis is the primary due-diligence step for
 * portfolio managers. They need P/E, margins, debt ratios, and growth metrics
 * before making allocation decisions. Bloomberg users expect dense tabular
 * data — not summary cards with large whitespace.
 *
 * WHY 9 SECTIONS (was 6): Wave 5 adds Analyst Consensus + Revenue Trend (full-width
 * above the grid) and Debt & Credit + Cash Flow (in the grid). This matches
 * Bloomberg DES page density for institutional use.
 *
 * WHY SECTIONS: Finance data has natural groupings (Valuation / Profitability /
 * Growth / Dividends / Balance Sheet). Grouping reduces cognitive load for
 * analysts who only care about one category at a time.
 *
 * WHY bg-card SECTIONS (Wave D-1): Each section is now an elevated card
 * (bg-card border rounded-[2px]) instead of a flat border-b divider. Cards
 * create visual hierarchy and let analysts scan 9 sections without the flat-
 * spreadsheet effect. Bloomberg DES uses section boxes for the same reason.
 *
 * WHY TWO-COLUMN LAYOUT (Wave D-2): Left column = scrollable content (metrics,
 * charts, tables). Right 280px sidebar = contextual intelligence (market position,
 * competitors, ownership, top news). Bloomberg DES page uses exactly this split —
 * left for depth, right for context. The 280px fixed width matches the Overview tab's
 * right sidebar so visual hierarchy is consistent across tabs.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Fundamentals tab)
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId} + sidebar-specific endpoints
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail Fundamentals tab, State C-3;
 *                   PRD-0031 §9 Wave 5 FundamentalsTab 9 sections; PLAN-0041 Wave D-1/D-2
 */

"use client";
// WHY "use client": uses useQuery (state), though the component itself has no
// browser-only APIs — "use client" is needed because useQuery requires React context.

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
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
import type { Fundamentals, FundamentalsSnapshot, Instrument } from "@/types/api";
import { AnalystConsensusStrip } from "@/components/instrument/AnalystConsensusStrip";
import { RevenueTrendSparklines } from "@/components/instrument/RevenueTrendSparklines";
import { WeekRangeBar } from "@/components/instrument/52WeekRangeBar";
import { MarketPositionPanel } from "@/components/instrument/MarketPositionPanel";
import { PeerComparisonPanel } from "@/components/instrument/PeerComparisonPanel";
import { OwnershipSnapshotPanel } from "@/components/instrument/OwnershipSnapshotPanel";
// PLAN-0088 Wave G-3: short-interest row (Float / Short Float % / Short Ratio
// / Short Int). The Fundamentals tab previously had no short-side data despite
// it being the single most-watched sentiment signal post-earnings. The row
// pulls from /v1/fundamentals/{id}/share-statistics — same endpoint that
// OwnershipSnapshotPanel uses for share counts/insider %, so no additional
// network round-trips beyond TanStack Query's per-key cache.
import { ShortInterestRow } from "@/components/instrument/ShortInterestRow";
import { FundamentalsTopNews } from "@/components/instrument/FundamentalsTopNews";
import { EarningsHistoryChart } from "@/components/instrument/EarningsHistoryChart";
import { InsiderTransactionsTable } from "@/components/instrument/InsiderTransactionsTable";
import { TechnicalSnapshot } from "@/components/instrument/TechnicalSnapshot";
// WHY FundamentalSparkline (T-E-5-03): inline sparklines on major metric rows add
// temporal context — a P/E compressing from 42→34 is a very different picture than
// "P/E: 34" alone. T-E-5-03 requires timeseries gateway calls for key valuation
// and profitability metrics.
import { FundamentalSparkline } from "@/components/instrument/FundamentalSparkline";

// ── Props ─────────────────────────────────────────────────────────────────────

interface FundamentalsTabProps {
  instrumentId: string;
  /** Prefetched fundamentals from CompanyOverview — shown while full data loads */
  initialData?: Fundamentals | null;
  /**
   * Current market price — positions the 52W range bar marker in the 52-Week Range section.
   * Optional: if null, the range bar renders without a marker (track only).
   */
  currentPrice?: number | null;
  /**
   * Entity ID (not instrument_id) — used by the right sidebar panels for graph,
   * news, and entity-based queries. ADR-F-12: entity_id is the stable cross-system
   * identifier; instrument_id can change on exchange migration.
   */
  entityId?: string | null;
  /**
   * Instrument metadata — passed to the right sidebar for market position (sector,
   * industry, exchange) and peer comparison (sector fallback, current ticker row).
   */
  instrument?: Instrument | null;
  /**
   * Callback to switch the parent tab to the News tab.
   * Passed down to FundamentalsTopNews in the sidebar "→ More news" link.
   */
  onViewAllNews?: () => void;
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

// ── Per-ticker missing-value placeholder (PLAN-0053 T-C-3-03) ────────────────
//
// WHY a dedicated component: NULL snapshot fields are common (EODHD doesn't
// always populate cash-flow values for ADRs / smaller-caps). Showing a bare
// "—" gives the user no signal about WHY — they'd reasonably wonder if the
// page is broken. This component renders "—" with a hover tooltip that
// distinguishes "missing for this ticker" from "globally unavailable" (the
// latter renders as "n/a" — see credit_rating handling below).
//
// WHY native `title` attribute (not a shadcn Tooltip): keeps the component
// dependency-free and works under SSR without hydration friction. The text
// is read by screen readers and standard browser hover.
function MissingValue() {
  return (
    <span
      className="cursor-help text-muted-foreground"
      title="Not available for this ticker"
    >
      —
    </span>
  );
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
    // WHY h-[22px] items-center (T-B-2-04): replaces py-1 items-baseline for
    // consistent terminal-standard 22px row height. Fixed height ensures the
    // section cards don't vary in height between sections with different metric counts.
    // items-center (not items-baseline) aligns label and value vertically at midpoint
    // — with fixed-height rows there is no baseline to align to.
    <div className="flex h-[22px] items-center justify-between gap-4">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
      <span className="font-mono text-[11px] tabular-nums">
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
 * Section — groups related metrics as an elevated card (Wave D-1)
 *
 * WHY bg-card border rounded-[2px] (was flat div): Elevated cards create visual
 * hierarchy so analysts can instantly distinguish the 9 section groups in the
 * dense metric grid. The old flat border-b divider blended sections into a single
 * spreadsheet; cards give each group a clear boundary — same visual pattern as
 * Bloomberg DES section boxes.
 *
 * WHY bg-muted/30 on header: Subtle header tinting distinguishes section title
 * from the data rows below without overpowering the dark terminal background.
 *
 * WHY overflow-hidden: The rounded-[2px] corner clip requires overflow-hidden on
 * the parent; otherwise, the child rows render over the corners.
 *
 * WHY px-2 py-1 in rows (kept): MetricRow already uses py-1 — the card provides
 * the outer border so internal row spacing remains unchanged.
 */
function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">
      {/* Card header — subtle bg differentiates title row from data rows */}
      <div className="border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          {title}
        </span>
      </div>
      <div className="px-2 divide-y divide-border/40">{children}</div>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function FundamentalsTab({
  instrumentId,
  initialData,
  currentPrice,
  entityId,
  instrument,
  onViewAllNews,
}: FundamentalsTabProps) {
  const { accessToken } = useAuth();

  const { data: fund, isLoading, isError, refetch } = useQuery({
    queryKey: ["fundamentals", instrumentId],
    queryFn: () => createGateway(accessToken).getFundamentals(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    // WHY 5min stale: fundamentals update once/day; no need to refetch aggressively
    staleTime: 5 * 60_000,
    placeholderData: initialData ?? undefined,
  });

  // WHY separate snapshot query: The 10 derived metrics (eps_ttm, beta, avg_volume_30d,
  // FCF, interest coverage, net_debt_to_ebitda, etc.) are stored in the
  // instrument_fundamentals_snapshot table and served from a dedicated S3 endpoint.
  // They are NOT part of the main Fundamentals response (which comes from EODHD
  // highlights/technicals JSONB sections). Keeping them separate allows the main
  // fundamentals data to continue loading even if the snapshot hasn't been backfilled.
  // WHY no error handling / loading guard: snapshot failures are non-fatal — the
  // component renders gracefully with "—" for any null/missing snapshot fields.
  const { data: snapshot } = useQuery<FundamentalsSnapshot>({
    queryKey: ["fundamentals-snapshot", instrumentId],
    queryFn: () => createGateway(accessToken).getFundamentalsSnapshot(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    // WHY 10min stale: snapshot is updated by a nightly backfill; very stale-tolerant.
    staleTime: 10 * 60_000,
  });

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading && !fund) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-1">
            <Skeleton className="h-3 w-24" />
            {Array.from({ length: 3 }).map((_, j) => (
              <Skeleton key={j} className="h-3 w-full" />
            ))}
          </div>
        ))}
      </div>
    );
  }

  // ── Error state (network / API failure) ───────────────────────────────────
  // WHY separate from no-data: isError means the request failed (500, 503, network
  // timeout). !fund means the request succeeded but returned no data (instrument
  // not tracked, ETF with no fundamentals, etc.). These are different root causes
  // and require different user-facing messages. A trader needs to know "is this a
  // system problem?" vs "does this instrument simply not have fundamentals?"
  //
  // WHY exchange === "CC" check: EODHD does not provide financial statements for
  // crypto assets (no income statement, no balance sheet, no P/E). Crypto instruments
  // have exchange="CC" in the DB. Showing "Failed to load" for a 404 on crypto is
  // misleading — show a friendly explanation instead.
  if (isError) {
    if (instrument?.exchange === "CC") {
      return (
        <div className="px-2 py-3 text-[11px] text-muted-foreground">
          Fundamental financial data (P/E, revenue, margins) is not available for
          cryptocurrency assets. EODHD does not publish financial statements for digital assets.
        </div>
      );
    }
    return (
      <div className="px-2 py-3 text-[11px] text-destructive/80">
        Failed to load fundamentals — check connection or retry.
        <button onClick={() => refetch()} className="text-[10px] text-primary ml-2">Retry</button>
      </div>
    );
  }

  // ── No-data state (instrument lacks fundamental coverage) ─────────────────
  if (!fund) {
    return (
      <div className="px-2 py-3 text-[11px] text-muted-foreground">
        No fundamental data available for this instrument.
      </div>
    );
  }

  // ── PLAN-0053 T-C-3-03: coverage-aware rendering ─────────────────────────
  // Compute the % of NULL fields in the snapshot (the 10 frontend-displayed
  // metrics: eps_ttm, beta, avg_volume_30d, operating_cash_flow, capex,
  // free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda,
  // credit_rating). When >30% are NULL we render a banner explaining that
  // EODHD has limited coverage for this specific ticker.  WHY 30%: the
  // threshold above which the page reads as "mostly empty" rather than
  // "a few gaps" — confirmed visually in Wave A QA.
  const SNAPSHOT_FIELDS = [
    "eps_ttm",
    "beta",
    "avg_volume_30d",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "fcf_margin",
    "interest_coverage",
    "net_debt_to_ebitda",
    "credit_rating",
  ] as const;
  // WHY snapshot guard: when the snapshot query is in flight (snapshot=undefined)
  // we skip the coverage banner entirely — we don't want to flash "limited
  // coverage" while the data is still loading.
  const nullFieldCount = snapshot
    ? SNAPSHOT_FIELDS.filter((f) => snapshot[f as keyof FundamentalsSnapshot] == null).length
    : 0;
  const coverageRatio = snapshot ? nullFieldCount / SNAPSHOT_FIELDS.length : 0;
  // WHY > 0.3 (not >=): a ticker with exactly 30% nulls (3/10) is borderline;
  // we only flag tickers that are MEANINGFULLY incomplete (4+ nulls).
  const showCoverageBanner = snapshot != null && coverageRatio > 0.3;

  // ── Render metrics grid ────────────────────────────────────────────────────
  // WHY grid-cols-[1fr_280px] (Wave D-2): Two-column layout — left content column
  // (scrollable metrics + charts + tables) + right 280px sidebar (market position,
  // competitors, ownership, news). Matches the Overview tab's right sidebar width
  // for visual consistency across tabs.
  return (
    <div className="grid grid-cols-[1fr_280px] min-h-0">
      {/* ── LEFT COLUMN: scrollable fundamentals content ──────────────────── */}
      <div className="overflow-y-auto border-r border-border">
        {/* ── PLAN-0053 T-C-3-03: coverage banner ───────────────────────────
            Surfaces a one-line warning when >30% of snapshot fields are NULL
            for this specific ticker — typically because EODHD has limited
            data coverage (smaller-caps, ADRs, recent IPOs). Helps the user
            distinguish "system is slow" from "this ticker just doesn't have
            full data". The Alpha Vantage fallback (T-C-3-02) reduces this
            for eps_ttm + beta but doesn't cover the cash-flow fields. */}
        {showCoverageBanner && (
          <div
            role="status"
            className="border-b border-warning/30 bg-warning/10 px-3 py-1.5 text-[11px] text-warning"
          >
            <AlertTriangle className="h-3 w-3 text-warning shrink-0 inline mr-1" strokeWidth={1.5} /><span className="font-mono uppercase tracking-wider text-[10px] mr-2">Limited coverage</span>
            Coverage for this ticker is limited ({nullFieldCount} of {SNAPSHOT_FIELDS.length} key
            metrics unavailable from current data providers).
          </div>
        )}
        {/* ── Full-width sections ABOVE the grid ──────────────────────────────
            WHY above the grid (not in it): Analyst Consensus and Revenue Trend
            are macro-level summaries that should appear before the detail metrics.
            Bloomberg DES page shows consensus ratings at the top. */}
        <div className="border-b border-border">
          <AnalystConsensusStrip fundamentals={fund} currentPrice={currentPrice} />
        </div>
        <div className="border-b border-border">
          {/* WHY instrumentId (not fundamentals): RevenueTrendSparklines now fetches its own
              timeseries data from the S9 /v1/fundamentals/timeseries endpoint (Wave D-1). */}
          <RevenueTrendSparklines instrumentId={instrumentId} />
        </div>

        {/* ── Metric grid ─────────────────────────────────────────────────────
            WHY gap-2 p-3 (was gap-6 p-4): tighter spacing increases data density.
            gap-6 (24px) between sections is too wide for a terminal grid; gap-2 (8px)
            keeps sections close while the section border/header provides visual separation.
            p-3 (12px) is the standard terminal panel padding per design system. */}
        {/* WHY no lg:grid-cols-3 (T-B-2-04): a 3-column layout makes sections too narrow
            (<200px each at 1280px viewport) causing metric label truncation and value
            overlap. md:grid-cols-2 is the maximum density that keeps all rows readable. */}
        <div className="grid grid-cols-2 gap-2 p-3">
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
          {/* WHY FundamentalSparkline for pe_ratio (T-E-5-03): a trailing P/E
              sparkline tells analysts whether the multiple is expanding (growth story)
              or compressing (value trap). This inline sparkline uses getFundamentalsTimeseries
              and is the T-E-5-03 contract: sparklines on key valuation metrics. */}
          <div className="py-1">
            <FundamentalSparkline instrumentId={instrumentId} metric="pe_ratio" height={32} />
          </div>

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
          {/* WHY FundamentalSparkline for roe (T-E-5-03): ROE trend shows whether
              returns on equity are improving or deteriorating — directional context
              critical for capital allocation decisions. */}
          <div className="py-1">
            <FundamentalSparkline instrumentId={instrumentId} metric="roe" height={32} />
          </div>

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
          {/* ── Visual range bar (Wave D-1) ─────────────────────────────────
              WHY WeekRangeBar above numeric rows: the visual position of the
              current price within the year's range is the most valuable insight —
              a bar encodes "near lows" vs "near highs" faster than two numbers.
              The numeric high/low rows below provide the exact values for precision. */}
          <div className="py-2">
            <WeekRangeBar
              low={fund.week_52_low}
              high={fund.week_52_high}
              current={currentPrice ?? null}
              showLabels={true}
            />
          </div>

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
              <MissingValue />
            )}
          </MetricRow>
        </Section>

        {/* ── Debt & Credit ────────────────────────────────────────────────
            WHY add this section: debt sustainability is a key risk signal.
            Interest coverage and Net Debt/EBITDA are the primary screens used
            by credit analysts to assess default risk.
            Fields sourced from instrument_fundamentals_snapshot (backfilled nightly).
            Null means: data not yet backfilled OR genuinely unavailable for this
            instrument (e.g. ETFs with no income statements). PLAN-0050 Wave D. */}
        <Section title="Debt &amp; Credit">
          {/* Interest Coverage: ebit / interest_expense — >3x = safe (green), <1.5x = distress (red).
              A ratio below 1.0 means the company cannot cover interest from operating income.
              WHY getMarginClass (not getMetricClass): higher coverage = safer = green (higher is better). */}
          <MetricRow label="Interest Coverage">
            {snapshot?.interest_coverage != null ? (
              <span className={getMarginClass(snapshot.interest_coverage, 3.0, 1.5)}>
                {formatRatio(snapshot.interest_coverage)}x
              </span>
            ) : (
              <MissingValue />
            )}
          </MetricRow>

          {/* Net Debt/EBITDA: lower is better — <2x conservative (green), >4x = leveraged (red).
              Negative value means net cash (no net debt) — always green. */}
          <MetricRow label="Net Debt / EBITDA">
            {snapshot?.net_debt_to_ebitda != null ? (
              <span className={
                snapshot.net_debt_to_ebitda < 0
                  ? "text-positive"
                  : getMetricClass(snapshot.net_debt_to_ebitda, 2.0, 4.0)
              }>
                {formatRatio(snapshot.net_debt_to_ebitda)}x
              </span>
            ) : (
              <MissingValue />
            )}
          </MetricRow>

          {/* Credit Rating: S&P/Moody's credit rating string (e.g. "A+", "BBB-").
              Always null until a credit data provider is integrated — EODHD does not
              expose ratings via their standard fundamentals API.
              PLAN-0053 T-C-3-03: render "n/a" (not "—") with an explainer tooltip so
              users distinguish "globally unavailable" from "missing for this ticker".
              The "n/a" form is conventional in financial data tools for "not
              applicable / not exposed by data source" — distinct from "—" which
              means "we expected this value but it's missing for this row". */}
          <MetricRow label="Credit Rating">
            {snapshot?.credit_rating != null ? (
              <span className="text-foreground font-mono text-[11px]">
                {snapshot.credit_rating}
              </span>
            ) : (
              <span
                className="cursor-help text-muted-foreground"
                title="Limited coverage — credit ratings not available from current data provider"
              >
                n/a
              </span>
            )}
          </MetricRow>
        </Section>

        {/* ── Cash Flow ────────────────────────────────────────────────────
            WHY add this section: cash flow metrics are the most manipulation-
            resistant fundamentals (earnings can be smoothed; cash flows are real).
            FCF margin is Warren Buffett's preferred screening metric.
            Fields sourced from instrument_fundamentals_snapshot (backfilled nightly
            from EODHD cash flow statements). PLAN-0050 Wave D. */}
        <Section title="Cash Flow">
          {/* Operating Cash Flow: cash generated from operations (before capex).
              Raw dollar value — large-cap companies have OCF in billions. */}
          <MetricRow label="Operating CF">
            {snapshot?.operating_cash_flow != null ? (
              <span className={snapshot.operating_cash_flow >= 0 ? "text-positive" : "text-negative"}>
                {formatMarketCap(snapshot.operating_cash_flow)}
              </span>
            ) : (
              <MissingValue />
            )}
          </MetricRow>

          {/* CapEx: stored as negative value from EODHD (cash outflow). Display absolute value
              with red coloring (it's a cost, but normal — only extreme capex relative to OCF is bad).
              WHY formatMarketCap: same dollar-suffix format as market cap (B/M/K). */}
          <MetricRow label="CapEx">
            {snapshot?.capex != null ? (
              <span className="text-foreground">
                {formatMarketCap(Math.abs(snapshot.capex))}
              </span>
            ) : (
              <MissingValue />
            )}
          </MetricRow>

          {/* Free Cash Flow: operating_cash_flow - |capex|. Positive = value-generative. */}
          <MetricRow label="Free Cash Flow">
            {snapshot?.free_cash_flow != null ? (
              <span className={snapshot.free_cash_flow >= 0 ? "text-positive" : "text-negative"}>
                {formatMarketCap(snapshot.free_cash_flow)}
              </span>
            ) : (
              <MissingValue />
            )}
          </MetricRow>

          {/* FCF Margin: free_cash_flow / revenue. >15% = strong (green), <5% = thin (amber), <0% = burning cash (red).
              WHY getMarginClass: higher FCF margin = more value generated = green (higher is better). */}
          <MetricRow label="FCF Margin">
            {snapshot?.fcf_margin != null ? (
              <span className={getMarginClass(snapshot.fcf_margin, 0.15, 0.05)}>
                {formatPercent(snapshot.fcf_margin)}
              </span>
            ) : (
              <MissingValue />
            )}
          </MetricRow>
        </Section>
      </div>

        {/* ── D-3 Charts & Tables ───────────────────────────────────────────
            WHY below the metric grid (not above): the chart/table panels are
            supplementary detail; the metric grid is primary. Bloomberg DES places
            its EPS history chart below the main fundamentals table for the same reason.
            WHY space-y-2 p-3: matches the metric grid container padding so the
            left column has a uniform 12px gutter between the grid bottom edge and
            the chart panels. */}
        <div className="space-y-2 p-3">
          {/* ── EPS Trend chart ───────────────────────────────────────────
              WHY first: EPS history is the most important trailing indicator in
              fundamental analysis — analysts check EPS growth before P/E.
              Bloomberg DES shows EPS history below the metrics grid. */}
          <EarningsHistoryChart instrumentId={instrumentId} />

          {/* ── Insider activity table ────────────────────────────────────
              WHY second: insider transactions complement EPS (did executives
              buy after a strong earnings print?). The two panels together tell
              the story of both business performance and management conviction. */}
          <InsiderTransactionsTable instrumentId={instrumentId} />

          {/* ── Technical indicators ──────────────────────────────────────
              WHY last: technicals are secondary to fundamentals on a fundamentals
              tab. Beta / MA / short interest are reference numbers, not the
              primary analysis surface — traders who need technicals use the
              Overview tab's price chart.
              WHY currentPrice (T-B-2-06): passed so TechnicalSnapshot can color-code
              50DayMA and 200DayMA relative to current price (bull green / bear red).
              Uses `fund.daily_return` field context — the instrument price is in the
              FundamentalsTab's parent props as `currentPrice`. */}
          <TechnicalSnapshot
            instrumentId={instrumentId}
            currentPrice={currentPrice ?? undefined}
          />
        </div>

        {/* ── Data quality footer ───────────────────────────────────────────
            WHY this footer: Bloomberg terminals display data source + timestamp
            on every data panel. Analysts need to know when the data was last
            refreshed to assess if a stale fundamental is distorting the picture
            (e.g., during earnings season). The muted/50 opacity keeps it clearly
            subordinate to the data above — it's reference info, not a headline. */}
        <p className="mx-4 mt-4 border-t border-border/40 pt-2 text-[10px] text-muted-foreground/70">
          Data sourced from S3 fundamentals pipeline · Updated {fund.updated_at ? formatRelativeTime(fund.updated_at) : "—"}
        </p>
      </div>

      {/* ── RIGHT SIDEBAR: contextual intelligence ──────────────────────────
          WHY 280px fixed width (not percentage): matches the Overview tab's right
          sidebar width. The two tabs feel visually consistent — same proportions.
          WHY overflow-y-auto: sidebar panels can overflow the viewport height on
          small screens; independent scroll prevents layout collapse.

          Panel order rationale (Bloomberg DES convention):
          1. Market Position — classification context (sector/cap tier)
          2. Peer Comparison — relative valuation benchmarks
          3. Ownership Snapshot — governance and float context
          4. Top News — current catalyst narrative */}
      <div className="overflow-y-auto divide-y divide-border/30">
        {/* ── Market Position ──────────────────────────────────────────── */}
        <MarketPositionPanel
          instrument={instrument ?? null}
          fundamentals={fund}
        />

        {/* ── Peer Comparison ──────────────────────────────────────────── */}
        {/* WHY only render when entityId available: PeerComparisonPanel needs
            entity_id for the knowledge graph query. Without it, only the sector
            fallback would run but sector comes from instrument which may also be
            null — skip entirely to avoid a broken empty panel. */}
        {entityId && (
          <PeerComparisonPanel
            entityId={entityId}
            instrument={instrument ?? null}
            currentMarketCap={fund.market_cap ?? null}
            currentPeRatio={fund.pe_ratio ?? null}
            currentDailyReturn={fund.daily_return ?? null}
          />
        )}

        {/* ── Ownership Snapshot ───────────────────────────────────────── */}
        <OwnershipSnapshotPanel instrumentId={instrumentId} />

        {/* ── Short Interest Row (PLAN-0088 Wave G-3) ──────────────────── */}
        {/* WHY between Ownership and TopNews: short-interest is structurally
            an extension of share statistics — same source endpoint
            (share-statistics), same "who owns / who's betting against"
            theme. Placing it after the ownership panel keeps the share-
            structure section coherent before the news block reorients the
            reader to qualitative signal. */}
        <ShortInterestRow instrumentId={instrumentId} />

        {/* ── Top News ─────────────────────────────────────────────────── */}
        {entityId && (
          <FundamentalsTopNews
            entityId={entityId}
            onViewAllNews={onViewAllNews}
          />
        )}
      </div>
    </div>
  );
}
