/**
 * components/instrument/InstrumentKeyMetrics.tsx — 6-row key metrics panel
 *
 * WHY THIS EXISTS: The Overview tab's 3-column lower grid needs a compact key
 * metrics panel (left column) showing the 6 most analyst-critical fundamentals.
 * Bloomberg's DES page shows this summary block immediately below the chart.
 *
 * WHY 6 METRICS (not all fundamentals): Overview is a "10-second scan" — analysts
 * look for MktCap, P/E, Yield, 52W range, and Beta before drilling into the
 * full Fundamentals tab. The full grid lives in the Fundamentals tab.
 *
 * WHY 22px rows: §0.1 data row height for the Terminal UI v3 design system.
 * All data rows across the entire app use h-[22px] for consistent density.
 *
 * WHO USES IT: OverviewLayout (within the 3-column lower grid)
 * DATA SOURCE: Props from FundamentalsTab / CompanyOverview (no independent fetch)
 * DESIGN REFERENCE: PRD-0031 §9 OverviewLayout zone 1, Wave 5
 */

// WHY no "use client": pure display component — no hooks, no browser APIs.
// Props flow in from the parent (OverviewLayout which is already "use client").

import { formatMarketCap, formatRatio, formatPercent, formatPrice } from "@/lib/utils";
import type { Fundamentals } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface InstrumentKeyMetricsProps {
  fundamentals: Fundamentals | null;
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
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1">
        {label}
      </span>
      {/* Value — monospace tabular-nums per §0.1 data value typography */}
      <span className={`font-mono text-[11px] tabular-nums ${valueClass}`}>
        {value}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InstrumentKeyMetrics({ fundamentals }: InstrumentKeyMetricsProps) {
  // ── Section header — terminal label strip ─────────────────────────────────
  // WHY h-6 (24px) for section header (not h-[22px]): Section headers are slightly
  // taller than data rows to provide visual grouping without extra margin/padding.
  return (
    <div>
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          KEY METRICS
        </span>
      </div>

      {/* Market Cap — no directional color, scale metric only */}
      <MetricRow
        label="MARKET CAP"
        value={formatMarketCap(fundamentals?.market_cap ?? null)}
      />

      {/* P/E Ratio — amber 20-35, red >35 per Graham/Damodaran thresholds */}
      <MetricRow
        label="P/E RATIO"
        value={formatRatio(fundamentals?.pe_ratio ?? null)}
        valueClass={
          fundamentals?.pe_ratio == null
            ? "text-muted-foreground"
            : fundamentals.pe_ratio > 35
            ? "text-negative"
            : fundamentals.pe_ratio < 20
            ? "text-positive"
            : "text-warning"
        }
      />

      {/* Dividend Yield — green >3% (income threshold) */}
      <MetricRow
        label="DIV YIELD"
        value={formatPercent(fundamentals?.dividend_yield ?? null)}
        valueClass={
          (fundamentals?.dividend_yield ?? 0) > 0.03
            ? "text-positive"
            : "text-foreground"
        }
      />

      {/* 52W High — text-positive (Bloomberg convention: session high = bullish) */}
      <MetricRow
        label="52W HIGH"
        value={formatPrice(fundamentals?.week_52_high ?? null)}
        valueClass="text-positive"
      />

      {/* 52W Low — text-negative (Bloomberg convention: session low = bearish) */}
      <MetricRow
        label="52W LOW"
        value={formatPrice(fundamentals?.week_52_low ?? null)}
        valueClass="text-negative"
      />

      {/* Beta — not in Fundamentals type; show em dash placeholder */}
      {/* WHY show anyway: keeps the 6-metric structure consistent across all
          instruments. When beta data is added to the Fundamentals type in a
          future wave, we only need to update this one row. */}
      <MetricRow
        label="BETA"
        value="—"
        valueClass="text-muted-foreground"
      />
    </div>
  );
}
