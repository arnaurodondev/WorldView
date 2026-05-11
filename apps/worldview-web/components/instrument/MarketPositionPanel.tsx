/**
 * components/instrument/MarketPositionPanel.tsx — Market Position sidebar panel
 *
 * WHY THIS EXISTS: The Fundamentals right sidebar needs a quick-reference panel
 * showing the instrument's market classification context. Before analyzing ratios,
 * analysts need to know: sector, industry, exchange, and market cap tier. A $50B
 * company has different P/E benchmarks than a $500M company — this panel surfaces
 * that context immediately.
 *
 * WHY MARKET CAP TIERS (not just raw value): Quantitative analysts use tier labels
 * (Mega/Large/Mid/Small/Micro) for portfolio construction rules. Many funds have
 * mandates restricted to "large cap" or "mid cap" — the label matters as much as
 * the dollar amount. Thresholds follow Russell/S&P conventional definitions.
 *
 * WHY PROPS-ONLY (no fetch): All data is already available from CompanyOverview
 * which the parent page has loaded. Fetching again would be a redundant API call.
 *
 * WHO USES IT: FundamentalsTab right sidebar (Wave D-2)
 * DATA SOURCE: Props from FundamentalsTab — instrument + fundamentals from CompanyOverview
 * DESIGN REFERENCE: PLAN-0041 §T-D-2-02
 */

// WHY no "use client": pure display component — props only, no hooks or browser APIs.

import { formatMarketCap } from "@/lib/utils";
import type { Fundamentals, Instrument } from "@/types/api";

// ── Props ─────────────────────────────────────────────────────────────────────

interface MarketPositionPanelProps {
  instrument: Instrument | null;
  fundamentals: Fundamentals | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * getMarketCapTier — classify market cap into conventional tier label
 *
 * WHY these thresholds: Based on Russell/S&P market cap tier conventions:
 * - Mega Cap (>$200B): S&P 100 territory — Apple, Microsoft, etc.
 * - Large Cap (>$10B): S&P 500 territory — investment-grade blue chips
 * - Mid Cap (>$2B): S&P 400 territory — established growth companies
 * - Small Cap (>$300M): Russell 2000 territory — emerging growth companies
 * - Micro Cap (<$300M): OTC/pink sheets territory — speculative / illiquid
 *
 * WHY function (not lookup): thresholds are continuous; function avoids
 * maintaining a sorted array of pairs.
 */
function getMarketCapTier(marketCap: number | null): string {
  if (marketCap == null) return "—";
  if (marketCap >= 200e9) return "Mega Cap";
  if (marketCap >= 10e9) return "Large Cap";
  if (marketCap >= 2e9) return "Mid Cap";
  if (marketCap >= 300e6) return "Small Cap";
  return "Micro Cap";
}

// ── Sub-component ─────────────────────────────────────────────────────────────

/**
 * MetricRow — 22px label/value row matching OverviewSidebarMetrics density
 *
 * WHY copy (not import from InstrumentKeyMetrics): InstrumentKeyMetrics exports
 * OverviewSidebarMetrics (the component), not MetricRow (the internal sub-component).
 * Keeping MetricRow local avoids a leaky internal API.
 */
function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center h-[22px] px-2 border-b border-border/30 last:border-0">
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1 truncate">
        {label}
      </span>
      <span className="font-mono text-[11px] tabular-nums truncate max-w-[55%] text-right text-foreground">
        {value}
      </span>
    </div>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export function MarketPositionPanel({ instrument, fundamentals }: MarketPositionPanelProps) {
  // ── Guard: show minimal panel when both props are null ────────────────────
  // WHY always render: sidebar should maintain consistent height even with no data,
  // so subsequent panels (ownership, news) don't jump when data loads.
  if (!instrument && !fundamentals) {
    return (
      <div>
        <div className="flex items-center border-b border-border px-2 h-6">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            MARKET POSITION
          </span>
        </div>
        <MetricRow label="SECTOR" value="—" />
        <MetricRow label="INDUSTRY" value="—" />
        <MetricRow label="EXCHANGE" value="—" />
        <MetricRow label="MARKET CAP" value="—" />
        <MetricRow label="CAP TIER" value="—" />
      </div>
    );
  }

  const tier = getMarketCapTier(fundamentals?.market_cap ?? null);
  // WHY tier-specific class: Mega/Large cap = positive (institutional-grade),
  // Micro cap = muted (speculative), others neutral.
  const tierClass =
    tier === "Mega Cap" || tier === "Large Cap"
      ? "text-positive"
      : tier === "Micro Cap"
        ? "text-muted-foreground"
        : "text-foreground";

  return (
    <div>
      {/* ── Section header ──────────────────────────────────────────────── */}
      <div className="flex items-center border-b border-border px-2 h-6">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          MARKET POSITION
        </span>
      </div>

      {/* ── Row 1: Sector ──────────────────────────────────────────────── */}
      <MetricRow label="SECTOR" value={instrument?.gics_sector ?? "—"} />

      {/* ── Row 2: Industry ────────────────────────────────────────────── */}
      <MetricRow label="INDUSTRY" value={instrument?.gics_industry ?? "—"} />

      {/* ── Row 3: Exchange ────────────────────────────────────────────── */}
      <MetricRow label="EXCHANGE" value={instrument?.exchange ?? "—"} />

      {/* ── Row 4: Market Cap (formatted) ──────────────────────────────── */}
      <MetricRow label="MARKET CAP" value={formatMarketCap(fundamentals?.market_cap ?? null)} />

      {/* ── Row 5: Cap Tier (with color) ───────────────────────────────── */}
      {/* WHY custom row (not MetricRow): need color class on the value */}
      <div className="flex items-center h-[22px] px-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground flex-1 truncate">
          CAP TIER
        </span>
        <span className={`font-mono text-[11px] tabular-nums text-right ${tierClass}`}>
          {tier}
        </span>
      </div>
    </div>
  );
}
