/**
 * MarketExposurePanel — compact market-exposure panel for the Holdings overview.
 * (2026-06-10 sprint, Wave 2 portfolio surface.)
 *
 * WHY THIS EXISTS: the exposure data (invested / cash / buying power / gross /
 * net / leverage / β-adjusted) was previously crammed into a single 22px
 * "EXPOSURE INV … · CASH … · LEV …" text line (ExposureCurrencyStrip). The
 * user verdict was that the overview "seems a bit empty" while this line was
 * unreadable at a glance — this panel gives every figure its own labelled
 * cell in a two-column terminal grid, at the same information density per
 * pixel but with scannable alignment.
 *
 * LAYOUT (h-[128px], two columns of 4 × 26px label/value rows):
 *   INVESTED   $        │  GROSS    %
 *   CASH       $        │  NET      %
 *   BUYING PWR $        │  LEVERAGE ×
 *   (stale caption)     │  β-ADJ    %
 *
 * DATA SOURCE: GET /v1/portfolios/{id}/exposure via the shared useExposure
 * hook (same ["exposure", id] cache entry the KPI strip reads — zero extra
 * round-trips). `buying_power` is the explicit server field (sprint gap #5,
 * v1 semantics: equals cash); when an older S9 build omits it we fall back
 * to `cash` — same value by definition, so the fallback is honest.
 * β-ADJ comes from the parent (Σ position_value × beta / total_value, beta
 * default 1.0 — see HoldingsTab's betaAdjExposure memo); null renders "—".
 *
 * WHO USES IT: features/portfolio/components/HoldingsTab.tsx (overview band).
 * DESIGN REFERENCE: DS §6.1 loading pattern, §6.2 skeletons, ADR-F-15 mono numbers.
 */
"use client";
// WHY "use client": TanStack Query hook (useExposure) requires React context.

import { RotateCw } from "lucide-react";
import { useExposure } from "@/hooks/useExposure";
// formatPercentUnsigned for GROSS (a magnitude — "+100%" would be a category
// error); signed formatPercent for NET and β-ADJ (directional: short books
// go negative).
import { formatPrice, formatPercent, formatPercentUnsigned } from "@/lib/utils";

interface MarketExposurePanelProps {
  portfolioId: string | null;
  /**
   * Beta-adjusted exposure fraction (Σ pos_value × β / total_value), computed
   * by the parent from holdings × instrument betas (default β = 1.0). null →
   * "—" (never silently substitute net exposure — different metric).
   */
  betaAdjExposure?: number | null;
}

/** One label/value row — 26px, label left (muted caps), value right (mono).
 *
 * WAVE-3 LAYOUT FIX (2026-06-11, screenshot 7 "huge black spaces"): the row
 * previously used bare `justify-between` with no width cap. Whenever the
 * panel renders wider than its xl 3-col slot (below the xl breakpoint, or
 * when the band stacks), the elastic gap stretched to the full panel width —
 * label hard-left, value hard-right, ~1400px of dead space between them.
 * The fix caps the row at `max-w-[240px]`: the value column is always within
 * one eye-saccade of its label, regardless of panel width. 240px fits the
 * widest real content ("BUYING PWR" label + "$1,234,567.89" value) with the
 * 8px gap, and is narrower than the ~260px column the xl 3-col slot provides,
 * so the cap never causes truncation at the design breakpoint. */
function StatRow({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <div
      className="flex h-[26px] w-full max-w-[240px] items-center justify-between gap-2"
      title={title}
    >
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground shrink-0">
        {label}
      </span>
      <span className="font-mono text-[11px] tabular-nums text-foreground truncate">
        {value}
      </span>
    </div>
  );
}

export function MarketExposurePanel({
  portfolioId,
  betaAdjExposure,
}: MarketExposurePanelProps) {
  // Shared hook — TanStack deduplicates with the KPI strip's subscription.
  const { data: exposure, isLoading, isError, refetch } = useExposure(portfolioId);

  if (!portfolioId) return null;

  return (
    <div
      data-testid="market-exposure-panel"
      className="flex h-[128px] flex-col bg-card overflow-hidden"
    >
      {/* ── Accent header (22px, matches every overview panel) ── */}
      <div className="flex h-[22px] shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">
          Market Exposure
        </span>
        {/* Stale-price caveat lives in the header so it never collides with
            the value grid. Only rendered when the backend flagged it. */}
        {exposure?.prices_stale && (
          <span className="text-[9px] uppercase tracking-[0.04em] text-warning">
            stale prices
          </span>
        )}
      </div>

      {/* ── Body ── */}
      {isLoading ? (
        // DS §6.2: shape-matched static skeleton — same 2-col × 4-row grid
        // the populated panel renders, so data arrival causes zero shift.
        <div
          data-testid="market-exposure-skeleton"
          className="grid flex-1 grid-cols-2 gap-x-4 px-3 py-1"
          aria-hidden="true"
        >
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex h-[26px] items-center">
              <div className="h-2.5 w-full rounded-[2px] bg-muted/30" />
            </div>
          ))}
        </div>
      ) : isError || !exposure ? (
        // Named error state with in-place retry (house convention — a dead
        // "—" grid would read as missing data rather than a failed fetch).
        <div
          data-testid="market-exposure-error"
          className="flex flex-1 flex-col items-center justify-center gap-1.5"
        >
          <span className="font-mono text-[11px] text-negative">
            Couldn&apos;t load exposure.
          </span>
          <button
            type="button"
            aria-label="Retry loading exposure"
            onClick={() => void refetch()}
            className="flex h-6 items-center gap-1 rounded-[2px] border border-primary/60 px-2 font-mono text-[10px] uppercase tracking-[0.06em] text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <RotateCw className="h-2.5 w-2.5" strokeWidth={1.5} />
            Retry
          </button>
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-2 gap-x-4 px-3 py-1">
          {/* Left column — dollar figures */}
          <div className="flex flex-col">
            <StatRow label="Invested" value={formatPrice(exposure.invested)} />
            <StatRow label="Cash" value={formatPrice(exposure.cash)} />
            {/* buying_power: explicit server field (sprint gap #5). Older S9
                builds omit it → fall back to cash (identical by v1 definition,
                margin not modelled — see ExposureResponse docs). */}
            <StatRow
              label="Buying pwr"
              value={formatPrice(exposure.buying_power ?? exposure.cash)}
              title="v1 cash account — buying power equals cash (margin not modelled)"
            />
            <StatRow
              label="Total eq"
              value={formatPrice(exposure.invested + exposure.cash)}
              title="Invested + cash"
            />
          </div>

          {/* Right column — ratios. *_pct fields are 0-1 fractions;
              formatPercent multiplies by 100 (codebase convention). */}
          <div className="flex flex-col">
            <StatRow
              label="Gross"
              value={formatPercentUnsigned(exposure.gross_exposure_pct)}
              title="Gross exposure: |long| + |short| as a fraction of equity"
            />
            <StatRow
              label="Net"
              value={formatPercent(exposure.net_exposure_pct)}
              title="Net exposure: long − short as a fraction of equity"
            />
            <StatRow
              label="Leverage"
              value={`${exposure.leverage.toFixed(2)}×`}
              title="Market value of positions ÷ account equity"
            />
            {/* β-ADJ — "—" when the parent hasn't derived it (no beta data).
                Silently substituting net exposure would mislabel the metric. */}
            <StatRow
              label="β-adj"
              value={betaAdjExposure != null ? formatPercent(betaAdjExposure) : "—"}
              title="Beta-adjusted exposure: Σ(position value × β) ÷ total value (β defaults to 1.0 when unavailable)"
            />
          </div>
        </div>
      )}
    </div>
  );
}
