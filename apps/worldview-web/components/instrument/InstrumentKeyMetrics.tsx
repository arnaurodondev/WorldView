/**
 * components/instrument/InstrumentKeyMetrics.tsx — 12-row Overview sidebar metrics panel
 *
 * WHY THIS EXISTS: The Overview tab's right sidebar needs a dense key metrics
 * panel. Bloomberg's DES page shows a compact metrics block immediately alongside
 * the chart — analysts need MktCap, P/E, Yield, ROE, D/E, 52W range, and sector
 * context before drilling into the full Fundamentals tab.
 *
 * WHY 12 METRICS (was 6): The sidebar is now a 280px vertical column with
 * independent scroll (Wave C-1). More metrics fit without crowding; 12 rows
 * provides Bloomberg-grade data density. The 6-metric version was designed for
 * a 3-column grid where vertical space was constrained.
 *
 * WHY OverviewSidebarMetrics (export name, was InstrumentKeyMetrics):
 * The component has moved from the 3-column bottom grid to the right sidebar.
 * The new name reflects its role. The file keeps its original name for minimal
 * git rename disruption (one import site: OverviewLayout.tsx).
 *
 * WHY 22px rows: §0.1 data row height for the Terminal UI v3 design system.
 * All data rows across the entire app use h-[22px] for consistent density.
 *
 * WHY WeekRangeBar in the metrics list: The 52W range is more useful as a
 * visual position indicator than two separate numbers. Analysts scan the bar
 * to see "near lows" vs "near highs" in under a second.
 *
 * WHO USES IT: OverviewLayout right sidebar (Wave C-1)
 * DATA SOURCE: Props from parent — no independent fetch
 * DESIGN REFERENCE: PLAN-0041 §T-C-1-02
 */

// WHY "use client": uses useQuery to fetch the fundamentals snapshot (EPS TTM,
// Beta, Avg Volume). Adding the snapshot fetch here keeps the parent OverviewLayout
// as a pure layout component that doesn't need to know about S3 endpoints.
"use client";

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// eslint-disable-next-line @typescript-eslint/no-unused-vars -- WHY: false positive; DataTimestamp is used inside conditional JSX at the snapshot footer (line ~294). ESLint's TypeScript plugin misses usage inside {condition && (...<DataTimestamp/>...)} patterns in some Next.js versions.
import { DataTimestamp } from "@/components/ui/data-timestamp";
import { formatMarketCap, formatRatio, formatPercent } from "@/lib/utils";
import { WeekRangeBar } from "@/components/instrument/52WeekRangeBar";
import type { Fundamentals, FundamentalsSnapshot, Instrument } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface OverviewSidebarMetricsProps {
  fundamentals: Fundamentals | null;
  /** Instrument metadata — provides sector and industry for the SECTOR row */
  instrument?: Instrument | null;
  /**
   * Current market price — positions the 52W range bar marker.
   * If null (quote not yet loaded), the range bar shows without a marker.
   */
  currentPrice?: number | null;
}

// ── Sub-components ────────────────────────────────────────────────────────────

/**
 * MetricRow — single label/value row at terminal density (22px)
 *
 * WHY border-b border-border/30 last:border-0: hairline dividers between rows
 * without a border below the last row — matches the screener table row pattern.
 */
function MetricRow({
  label,
  value,
  valueClass = "text-foreground",
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center h-[22px] px-2 border-b border-border/30 last:border-0">
      {/* Label — uppercase 10px per §0.1 label typography */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1 truncate">
        {label}
      </span>
      {/* Value — monospace tabular-nums per §0.1 data value typography */}
      <span className={`font-mono text-[11px] tabular-nums truncate max-w-[55%] text-right ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function OverviewSidebarMetrics({
  fundamentals,
  instrument,
  currentPrice,
}: OverviewSidebarMetricsProps) {
  const { accessToken } = useAuth();

  // ── Snapshot query (EPS TTM, Beta, Avg Volume) ────────────────────────────
  // WHY fetch here (not in parent): OverviewLayout is a pure layout orchestrator
  // that passes down pre-fetched CompanyOverview data. The snapshot is a separate
  // S3 endpoint (instrument_fundamentals_snapshot table) populated by the nightly
  // backfill script. Fetching here keeps the parent clean and lets this component
  // degrade gracefully if the snapshot is unavailable.
  // WHY optional chaining on instrument_id: fundamentals may be null while loading.
  const instrumentId = fundamentals?.instrument_id;
  const { data: snapshot } = useQuery<FundamentalsSnapshot>({
    queryKey: ["fundamentals-snapshot", instrumentId],
    queryFn: () => createGateway(accessToken).getFundamentalsSnapshot(instrumentId!),
    // WHY enabled guard: skip query if instrument_id or token is not yet available
    // (CompanyOverview hasn't loaded yet). The ! in queryFn is safe here because
    // enabled prevents execution when instrumentId is falsy.
    enabled: !!accessToken && !!instrumentId,
    // WHY 10min stale: snapshot is populated by a nightly backfill; very stale-tolerant
    staleTime: 10 * 60_000,
  });

  // ── Color helpers ──────────────────────────────────────────────────────────
  // WHY inline helpers (not imported): these thresholds are specific to this component's
  // display context. Sharing with FundamentalsTab would couple two unrelated UI zones.

  // P/E color: Graham/Damodaran — <20 cheap, 20-35 fair, >35 expensive
  const peClass = (pe: number | null) => {
    if (pe == null) return "text-muted-foreground";
    if (pe > 35) return "text-negative";
    if (pe < 20) return "text-positive";
    return "text-warning";
  };

  // ROE color: >15% = strong returns (green), <0% = losing money (red)
  const roeClass = (roe: number | null) => {
    if (roe == null) return "text-muted-foreground";
    if (roe < 0) return "text-negative";
    if (roe > 0.15) return "text-positive";
    return "text-foreground";
  };

  // D/E color: >2 = over-leveraged (red), <0.5 = low leverage (green)
  const deClass = (de: number | null) => {
    if (de == null) return "text-muted-foreground";
    if (de > 2) return "text-negative";
    if (de <= 0.5) return "text-positive";
    return "text-foreground";
  };

  // Daily return color: positive = green, negative = red
  const returnClass = (r: number | null) => {
    if (r == null) return "text-muted-foreground";
    if (r > 0) return "text-positive";
    if (r < 0) return "text-negative";
    return "text-foreground";
  };

  return (
    <div>
      {/* ── Section header ────────────────────────────────────────────────── */}
      {/* WHY h-6 (24px): section headers are taller than data rows (22px) to
          create visual grouping without extra margins. */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          KEY METRICS
        </span>
      </div>

      {/* ── Row 1: Market Cap ─────────────────────────────────────────────── */}
      <MetricRow
        label="MARKET CAP"
        value={formatMarketCap(fundamentals?.market_cap ?? null)}
      />

      {/* ── Row 2: P/E Ratio — amber 20–35, red >35, green <20 ───────────── */}
      <MetricRow
        label="P/E RATIO"
        value={formatRatio(fundamentals?.pe_ratio ?? null)}
        valueClass={peClass(fundamentals?.pe_ratio ?? null)}
      />

      {/* ── Row 3: Forward P/E — same coloring as trailing P/E ───────────── */}
      {/* WHY show FWD P/E separately: forward P/E discounts future earnings
          expectations, not trailing. A stock can have high trailing P/E but low
          FWD P/E if growth is expected — both metrics together tell a fuller story. */}
      <MetricRow
        label="FWD P/E"
        value={formatRatio(fundamentals?.forward_pe ?? null)}
        valueClass={peClass(fundamentals?.forward_pe ?? null)}
      />

      {/* ── Row 4: EPS (TTM) — from instrument_fundamentals_snapshot (PLAN-0050 Wave D) ── */}
      {/* WHY snapshot (not earnings history): the snapshot pre-computes eps_ttm from
          EODHD Highlights at backfill time — one fast lookup vs. summing quarterly
          earnings records. Null = not yet backfilled or ETF with no EPS. */}
      <MetricRow
        label="EPS (TTM)"
        value={snapshot?.eps_ttm != null ? `$${snapshot.eps_ttm.toFixed(2)}` : "—"}
        valueClass={
          snapshot?.eps_ttm != null
            ? snapshot.eps_ttm >= 0 ? "text-positive" : "text-negative"
            : "text-muted-foreground"
        }
      />

      {/* ── Row 5: Dividend Yield — green >3% income threshold ───────────── */}
      <MetricRow
        label="DIV YIELD"
        value={formatPercent(fundamentals?.dividend_yield ?? null)}
        valueClass={
          (fundamentals?.dividend_yield ?? 0) > 0.03
            ? "text-positive"
            : "text-foreground"
        }
      />

      {/* ── Row 6: Beta — from instrument_fundamentals_snapshot (PLAN-0050 Wave D) ── */}
      {/* WHY snapshot: beta is extracted from EODHD Technicals at backfill time.
          <1 = less volatile than market (green), >1.5 = significantly more volatile (amber). */}
      <MetricRow
        label="BETA"
        value={snapshot?.beta != null ? snapshot.beta.toFixed(2) : "—"}
        valueClass={
          snapshot?.beta != null
            ? snapshot.beta > 1.5 ? "text-warning"
            : snapshot.beta < 1.0 ? "text-positive"
            : "text-foreground"
            : "text-muted-foreground"
        }
      />

      {/* ── Row 7: ROE — >15% green, <0% red ────────────────────────────── */}
      <MetricRow
        label="ROE"
        value={formatPercent(fundamentals?.roe ?? null)}
        valueClass={roeClass(fundamentals?.roe ?? null)}
      />

      {/* ── Row 8: Debt/Equity — >2x red, ≤0.5x green ───────────────────── */}
      <MetricRow
        label="DEBT/EQUITY"
        value={formatRatio(fundamentals?.debt_to_equity ?? null)}
        valueClass={deClass(fundamentals?.debt_to_equity ?? null)}
      />

      {/* ── Row 9: 52-Week Range — WeekRangeBar visual ───────────────────── */}
      {/* WHY different from MetricRow: the range bar needs full width for the
          track to be readable. It breaks the label/value alignment pattern but
          provides far more information density than two separate number rows. */}
      <div className="px-2 py-1.5 border-b border-border/30">
        <span className="block text-[10px] uppercase tracking-[0.08em] text-muted-foreground mb-1">
          52W RANGE
        </span>
        <WeekRangeBar
          low={fundamentals?.week_52_low ?? null}
          high={fundamentals?.week_52_high ?? null}
          current={currentPrice ?? null}
          showLabels={true}
        />
      </div>

      {/* ── Row 10: Avg Volume — from instrument_fundamentals_snapshot (PLAN-0050 Wave D) ── */}
      {/* WHY snapshot: avg_volume_30d extracted from EODHD Technicals/ShareStatistics
          at backfill time. Formatted with B/M/K suffix same as market cap for consistency. */}
      <MetricRow
        label="AVG VOLUME"
        value={snapshot?.avg_volume_30d != null ? formatMarketCap(snapshot.avg_volume_30d) : "—"}
        valueClass={snapshot?.avg_volume_30d != null ? "text-foreground" : "text-muted-foreground"}
      />

      {/* ── Row 11: Sector ────────────────────────────────────────────────── */}
      {/* WHY sector in metrics (not just header): analysts drilling into fundamentals
          need sector context alongside ratios. Peer comparison requires knowing
          the sector to benchmark P/E, ROE, D/E against sector averages. */}
      <MetricRow
        label="SECTOR"
        value={instrument?.gics_sector ?? "—"}
      />

      {/* ── Row 12: Daily Return ──────────────────────────────────────────── */}
      <MetricRow
        label="DAY RETURN"
        value={formatPercent(fundamentals?.daily_return ?? null)}
        valueClass={returnClass(fundamentals?.daily_return ?? null)}
      />

      {/* ── T-D-4-05: DataTimestamp footer ───────────────────────────────── */}
      {/* WHY show "as of" timestamp: analysts need to know how stale the snapshot
          data is. The backfill runs nightly, so the data is typically 0–24 hours old.
          Showing the timestamp builds trust and avoids confusion when markets move
          but EPS/Beta hasn't updated (expected behaviour, not a bug).
          WHY only when snapshot.updated_at is available: no timestamp if the instrument
          hasn't been backfilled yet (snapshot is null or updated_at is null). */}
      {snapshot?.updated_at != null && (
        <div className="px-2 py-1 border-t border-border/30 flex items-center gap-1">
          {/* "as of" label — 9px, dimmer than regular muted text */}
          <span className="text-[9px] text-muted-foreground/50 uppercase tracking-[0.06em]">
            as of
          </span>
          <DataTimestamp
            timestamp={snapshot.updated_at}
            format="absolute"
            className="text-[9px] text-muted-foreground/60"
          />
        </div>
      )}
    </div>
  );
}
