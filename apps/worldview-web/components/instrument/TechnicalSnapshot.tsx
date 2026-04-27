/**
 * components/instrument/TechnicalSnapshot.tsx — Key technical indicator snapshot
 *
 * WHY THIS EXISTS: Technical indicators complement fundamental data in a complete
 * instrument view. Beta quantifies systematic market risk (how much does this stock
 * amplify/dampen S&P moves?). Moving averages tell traders if price is above or below
 * trend. Short interest signals crowded bearish positions that can cause short squeezes.
 * Bloomberg DES shows technicals in the "Technical Analysis" section below fundamentals.
 *
 * WHY THESE 5 METRICS (Beta, 50DayMA, 200DayMA, Short Ratio, Short %):
 * - Beta: mandatory for any risk-adjusted return calculation (CAPM, Sharpe)
 * - 50DayMA: short-term trend indicator (traders use as dynamic support/resistance)
 * - 200DayMA: long-term trend baseline; price below 200DayMA = bearish territory
 * - Short Ratio: "days to cover" — >10 implies crowded short (potential squeeze)
 * - Short %: absolute short interest as % of float; >5% = meaningful short interest
 *
 * WHY ShortPercent IS A DECIMAL (0.0086 = 0.86%): EODHD returns ShortPercent in
 * fractional form (not pre-multiplied like ownership percentages). 0.0086 means 0.86%.
 * We multiply by 100 to display: `${(ShortPercent * 100).toFixed(2)}%`. This is the
 * OPPOSITE convention from PercentInstitutions (65.325 = 65.325%) — document explicitly
 * to prevent the same confusion that affected Wave D-2 OwnershipSnapshotPanel.
 *
 * WHY PascalCase interface: S3 stores technicals from EODHD as raw PascalCase JSON.
 * Keys like "50DayMA" cannot be valid TypeScript identifiers but are valid quoted
 * interface keys — accessed as `data["50DayMA"]`.
 *
 * WHO USES IT: FundamentalsTab left column (Wave D-3), below InsiderTransactionsTable
 * DATA SOURCE: S9 GET /v1/fundamentals/{instrumentId}/technicals
 * DESIGN REFERENCE: PLAN-0041 §T-D-3-03
 */

"use client";
// WHY "use client": uses useQuery for technicals fetch.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

// ── Props ─────────────────────────────────────────────────────────────────────

interface TechnicalSnapshotProps {
  instrumentId: string;
}

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * S3 technicals record — PascalCase from EODHD.
 *
 * WHY quoted keys ("50DayMA"): TypeScript interface members that start with a
 * digit must be quoted. Access them via bracket notation: `data["50DayMA"]`.
 *
 * WHY ShortPercent decimal: EODHD returns 0.0086 for 0.86% short interest.
 * Multiply by 100 before displaying. Do NOT compare to PercentInstitutions
 * (which is already 65.325 for 65.325%) — the two use different scales.
 */
interface TechnicalsRaw {
  Beta?: number | null;
  "52WeekHigh"?: number | null;
  "52WeekLow"?: number | null;
  "50DayMA"?: number | null;
  "200DayMA"?: number | null;
  ShortRatio?: number | null;
  ShortPercent?: number | null;       // Decimal fraction: 0.0086 = 0.86%
  ShortPercentFloat?: number | null;  // Alternative field name from some instruments
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * getBetaClass — color-code beta by market risk tier.
 *
 * WHY these thresholds:
 * - Beta < 0.5: very low volatility (utilities, defensives). Green = stable.
 * - 0.5–1.2: market-neutral zone. No color = informational.
 * - 1.2–1.8: elevated volatility (growth tech). Warning = watch risk.
 * - Beta > 1.8: high leverage to market moves. Red = significant risk.
 * These map to standard CAPM risk tier conventions (Damodaran 2023).
 */
function getBetaClass(beta: number | null | undefined): string {
  if (beta == null) return "text-muted-foreground";
  if (beta < 0.5) return "text-positive";        // Very low volatility — defensive
  if (beta <= 1.2) return "text-foreground";      // Market-neutral — no signal
  if (beta <= 1.8) return "text-warning";         // Above-market risk — caution
  return "text-negative";                          // High beta — elevated risk
}

/**
 * getShortRatioClass — color-code days-to-cover by squeeze risk.
 *
 * WHY 10 days: the "10-day rule" (Investopedia, Bloomberg) classifies short ratio
 * >10 as a potential squeeze candidate because bears need >2 trading weeks to exit
 * their positions. >20 is severe — any upward catalyst creates forced buying.
 * WHY 5 as amber: 5–10 days indicates meaningful but manageable short interest.
 */
function getShortRatioClass(ratio: number | null | undefined): string {
  if (ratio == null) return "text-muted-foreground";
  if (ratio > 20) return "text-negative";  // Severe squeeze risk
  if (ratio > 10) return "text-warning";   // Elevated short interest
  return "text-foreground";               // Normal — no significant signal
}

/**
 * formatMa — round moving average to 2 decimal places.
 *
 * WHY not formatPrice(): formatPrice() adds a $ prefix and uses 2 decimal places.
 * Moving averages from EODHD have many decimal places (e.g., 260.2392) — we display
 * 2 decimal places for accuracy without the $ prefix (price context is implicit).
 */
function formatMa(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toFixed(2)}`;
}

/**
 * formatShortPct — convert EODHD decimal short percent to display string.
 *
 * WHY * 100: ShortPercent from EODHD is a decimal fraction (0.0086 = 0.86%).
 * This DIFFERS from PercentInstitutions (already multiplied by 100 in EODHD's output).
 * We confirmed this from live data: ShortPercent=0.0086 for AAPL → display as "0.86%".
 */
function formatShortPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

// ── Sub-component ─────────────────────────────────────────────────────────────

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
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1 truncate">
        {label}
      </span>
      <span className={`font-mono text-[11px] tabular-nums text-right ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function TechnicalSnapshot({ instrumentId }: TechnicalSnapshotProps) {
  const { accessToken } = useAuth();
  const gateway = createGateway(accessToken);

  // ── Fetch technicals ───────────────────────────────────────────────────────
  // WHY staleTime 300_000: Technical indicators (MAs, short interest) update
  // daily at market close. 5-minute stale window prevents redundant fetches on
  // rapid page navigation while staying within the same trading session's data.
  const { data, isLoading } = useQuery({
    queryKey: ["technicals", instrumentId],
    queryFn: () => gateway.getTechnicals(instrumentId),
    enabled: !!accessToken && !!instrumentId,
    staleTime: 300_000,
  });

  // ── Extract technicals from first record ─────────────────────────────────
  // WHY records[0]: technicals is a snapshot (single latest record from S3).
  // Multiple records would indicate historical snapshots; we always want the latest.
  const tech = (data?.records?.[0]?.data as TechnicalsRaw | undefined) ?? null;

  // ── Loading state ──────────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            TECHNICALS
          </span>
        </div>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center h-[22px] px-2 gap-2">
            <Skeleton className="h-3 w-20 flex-none" />
            <Skeleton className="h-3 flex-1" />
          </div>
        ))}
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  if (!tech) {
    return (
      <div className="bg-card border border-border rounded-[2px] overflow-hidden">
        <div className="border-b border-border px-2 py-1 bg-muted/30">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
            TECHNICALS
          </span>
        </div>
        <div className="px-2 py-2 text-[11px] font-mono text-muted-foreground">
          Technical data not available
        </div>
      </div>
    );
  }

  // ── Short percent: prefer ShortPercentFloat, fall back to ShortPercent ─────
  // WHY prefer Float: short percent of float is a more meaningful signal than
  // short percent of total shares outstanding (float = actual tradeable shares).
  // Some EODHD records populate ShortPercentFloat; others only have ShortPercent.
  const shortPctValue = tech.ShortPercentFloat ?? tech.ShortPercent ?? null;

  return (
    <div className="bg-card border border-border rounded-[2px] overflow-hidden">
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="border-b border-border px-2 py-1 bg-muted/30">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground font-medium">
          TECHNICALS
        </span>
      </div>

      {/* ── Beta ────────────────────────────────────────────────────────── */}
      {/* WHY first: Beta is the most critical risk metric for portfolio managers.
          It directly affects position sizing in a mean-variance optimized portfolio. */}
      <MetricRow
        label="BETA"
        value={tech.Beta != null ? tech.Beta.toFixed(3) : "—"}
        valueClass={getBetaClass(tech.Beta)}
      />

      {/* ── 50-Day Moving Average ────────────────────────────────────────── */}
      {/* WHY no color: MA value alone (without current price context) has no
          directional signal. Coloring would require the current price prop.
          The value itself is informational — analysts compare it mentally. */}
      <MetricRow
        label="50-DAY MA"
        value={formatMa(tech["50DayMA"])}
      />

      {/* ── 200-Day Moving Average ───────────────────────────────────────── */}
      <MetricRow
        label="200-DAY MA"
        value={formatMa(tech["200DayMA"])}
      />

      {/* ── Short Ratio (days to cover) ──────────────────────────────────── */}
      {/* WHY show ratio not raw short shares: "days to cover" normalizes by
          average daily volume, making it comparable across different cap sizes.
          5M shares short in AAPL (150B shares) = nothing; 5M in a small-cap = massive. */}
      <MetricRow
        label="SHORT RATIO"
        value={tech.ShortRatio != null ? `${tech.ShortRatio.toFixed(2)}d` : "—"}
        valueClass={getShortRatioClass(tech.ShortRatio)}
      />

      {/* ── Short % Float ───────────────────────────────────────────────── */}
      {/* WHY decimal * 100: ShortPercent/ShortPercentFloat is a decimal fraction
          from EODHD (0.0086 = 0.86%). See WHY comment at top of file. */}
      <MetricRow
        label="SHORT % FLOAT"
        value={formatShortPct(shortPctValue)}
      />
    </div>
  );
}
