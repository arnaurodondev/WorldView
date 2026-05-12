/**
 * components/instrument/FundamentalsTab.tsx — Fundamentals tab orchestrator (9 sections)
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
 * Key-value metric rows are NOT improved by AG Grid. MetricRow is already 22px
 * fixed height (terminal density standard). Decision: P6-3 is N/A.
 *
 * WHY THIS EXISTS: Fundamental analysis is the primary due-diligence step for
 * portfolio managers. They need P/E, margins, debt ratios, and growth metrics
 * before making allocation decisions.
 *
 * WHY TWO-COLUMN LAYOUT (Wave D-2): Left column = scrollable content (metrics,
 * charts, tables). Right 280px sidebar = contextual intelligence (market position,
 * competitors, ownership, top news). Bloomberg DES page uses exactly this split.
 *
 * WHO USES IT: app/(app)/instruments/[entityId]/page.tsx (Fundamentals tab)
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId} + sidebar-specific endpoints
 * DESIGN REFERENCE: PRD-0028 §6.5 Instrument Detail Fundamentals tab, State C-3;
 *                   PRD-0031 §9 Wave 5 FundamentalsTab 9 sections; PLAN-0041 Wave D-1/D-2
 *
 * SUB-COMPONENTS (extracted for PLAN-0089 D-3):
 *   - fundamentals/FundamentalsMetricsGrid.tsx — 9-section metric grid
 *   - fundamentals/fundamentals-helpers.ts     — getMetricClass, getMarginClass
 */

"use client";
// WHY "use client": uses useQuery (state), though the component itself has no
// browser-only APIs — "use client" is needed because useQuery requires React context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/utils";
import type { Fundamentals, FundamentalsSnapshot, Instrument } from "@/types/api";
import { AnalystConsensusStrip } from "@/components/instrument/AnalystConsensusStrip";
import { RevenueTrendSparklines } from "@/components/instrument/RevenueTrendSparklines";
import { MarketPositionPanel } from "@/components/instrument/MarketPositionPanel";
import { PeerComparisonPanel } from "@/components/instrument/PeerComparisonPanel";
import { OwnershipSnapshotPanel } from "@/components/instrument/OwnershipSnapshotPanel";
// PLAN-0088 Wave G-3: short-interest row (Float / Short Float % / Short Ratio / Short Int).
// Pulls from /v1/fundamentals/{id}/share-statistics — same endpoint as OwnershipSnapshotPanel.
import { ShortInterestRow } from "@/components/instrument/ShortInterestRow";
import { FundamentalsTopNews } from "@/components/instrument/FundamentalsTopNews";
import { EarningsHistoryChart } from "@/components/instrument/EarningsHistoryChart";
import { InsiderTransactionsTable } from "@/components/instrument/InsiderTransactionsTable";
import { TechnicalSnapshot } from "@/components/instrument/TechnicalSnapshot";
import { IncomeStatementFY } from "@/components/instrument/IncomeStatementFY";
// PLAN-0088 Wave G-4: analyst price-target distribution sparkline.
import { AnalystTargetSparkline } from "@/components/instrument/AnalystTargetSparkline";
import { FundamentalsMetricsGrid } from "./fundamentals/FundamentalsMetricsGrid";

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
  // not tracked, ETF with no fundamentals, etc.).
  //
  // WHY exchange === "CC" check: EODHD does not provide financial statements for
  // crypto assets (no income statement, no balance sheet, no P/E).
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

  // ── Render metrics grid ────────────────────────────────────────────────────
  // WHY grid-cols-[1fr_280px] (Wave D-2): Two-column layout — left content column
  // (scrollable metrics + charts + tables) + right 280px sidebar (market position,
  // competitors, ownership, news). Matches the Overview tab's right sidebar width
  // for visual consistency across tabs.
  return (
    <div className="grid grid-cols-[1fr_280px] min-h-0">
      {/* ── LEFT COLUMN: scrollable fundamentals content ──────────────────── */}
      <div className="overflow-y-auto border-r border-border">
        {/* ── Full-width sections ABOVE the grid ────────────────────────────
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

        {/* ── 9-section metrics grid (extracted to FundamentalsMetricsGrid) ── */}
        <FundamentalsMetricsGrid
          fund={fund}
          snapshot={snapshot}
          instrumentId={instrumentId}
          currentPrice={currentPrice}
        />

        {/* ── D-3 Charts & Tables ────────────────────────────────────────────
            WHY below the metric grid (not above): the chart/table panels are
            supplementary detail; the metric grid is primary. Bloomberg DES places
            its EPS history chart below the main fundamentals table for the same reason.
            WHY space-y-2 p-3: matches the metric grid container padding so the
            left column has a uniform 12px gutter between the grid bottom edge and
            the chart panels. */}
        <div className="space-y-2 p-3">
          {/* ── PLAN-0088 Wave G-1: FY-column income statement ────────────── */}
          <IncomeStatementFY instrumentId={instrumentId} />

          {/* ── EPS Trend chart ───────────────────────────────────────────── */}
          <EarningsHistoryChart instrumentId={instrumentId} />

          {/* ── Insider activity table ──────────────────────────────────────── */}
          <InsiderTransactionsTable instrumentId={instrumentId} />

          {/* ── Technical indicators ────────────────────────────────────────── */}
          <TechnicalSnapshot
            instrumentId={instrumentId}
            currentPrice={currentPrice ?? undefined}
          />
        </div>

        {/* ── Data quality footer ──────────────────────────────────────────────
            WHY this footer: Bloomberg terminals display data source + timestamp
            on every data panel. Analysts need to know when the data was last
            refreshed to assess if a stale fundamental is distorting the picture. */}
        <p className="mx-4 mt-4 border-t border-border/40 pt-2 text-[10px] text-muted-foreground/70">
          Data sourced from S3 fundamentals pipeline · Updated {fund.updated_at ? formatRelativeTime(fund.updated_at) : "—"}
        </p>
      </div>

      {/* ── RIGHT SIDEBAR: contextual intelligence ────────────────────────────
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
        {/* ── Analyst Target Distribution (PLAN-0088 Wave G-4) ──────────────
            WHY first in sidebar: the analyst target distribution is the most
            directly actionable signal. AnalystConsensusStrip above the grid
            shows the absolute target; this visual distribution shows WHERE
            current price sits within the analyst range — complementary info.
            WHY pass fund + currentPrice via props: no additional network round-trip. */}
        <AnalystTargetSparkline
          fundamentals={fund}
          currentPrice={currentPrice}
        />

        {/* ── Market Position ────────────────────────────────────────────── */}
        <MarketPositionPanel
          instrument={instrument ?? null}
          fundamentals={fund}
        />

        {/* ── Peer Comparison ────────────────────────────────────────────── */}
        {/* WHY only render when entityId available: PeerComparisonPanel needs
            entity_id for the knowledge graph query. */}
        {entityId && (
          <PeerComparisonPanel
            entityId={entityId}
            instrument={instrument ?? null}
            currentMarketCap={fund.market_cap ?? null}
            currentPeRatio={fund.pe_ratio ?? null}
            currentDailyReturn={fund.daily_return ?? null}
          />
        )}

        {/* ── Ownership Snapshot ─────────────────────────────────────────── */}
        <OwnershipSnapshotPanel instrumentId={instrumentId} />

        {/* ── Short Interest Row (PLAN-0088 Wave G-3) ──────────────────────
            WHY between Ownership and TopNews: short-interest is structurally
            an extension of share statistics — same source endpoint. */}
        <ShortInterestRow instrumentId={instrumentId} />

        {/* ── Top News ───────────────────────────────────────────────────── */}
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
