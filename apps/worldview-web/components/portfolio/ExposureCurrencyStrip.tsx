/**
 * ExposureCurrencyStrip — single h-[22px] density row combining exposure + leverage + currency.
 *
 * WHY THIS EXISTS: Bloomberg PORT header shows exposure summary and leverage in
 * one compact row. Previous layout used a 120px ExposureStrip + separate card.
 * This 22px strip delivers the same information at 5× less vertical cost.
 *
 * CURRENCY EXPOSURE: accepts an optional `currencies` prop (array of
 * { code, pct } pairs sorted by weight desc) so the parent can surface the
 * book's currency mix inline. When not provided, the CCY section is omitted.
 * WHY optional (not self-fetching): currency breakdown is not available from
 * the /exposure endpoint today — it is computed by the parent from holdings.
 * Keeping it optional lets the strip render correctly for portfolios where the
 * parent cannot yet derive this breakdown.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx directly above ConcentrationSectorTeaseStrip.
 * DATA SOURCE:
 *   - Exposure: GET /v1/portfolios/{id}/exposure → ExposureResponse (via useExposure hook)
 *   - Currencies: optional prop from parent (derived from holdings if available)
 * DESIGN REFERENCE: PRD-0089 W2 §4.3, §6.1
 */
"use client";
// WHY "use client": uses TanStack Query hook (useExposure) which requires React context.

import { useExposure } from "@/hooks/useExposure";
import { formatPrice, formatPercent } from "@/lib/utils";

/** A single currency chip: code (e.g. "USD") and weight as 0-1 fraction. */
export interface CurrencyChip {
  code: string;
  /** Portfolio weight fraction (0-1). e.g. 0.92 = 92% */
  pct: number;
}

interface ExposureCurrencyStripProps {
  portfolioId: string | null;
  /**
   * Optional currency exposure breakdown, sorted by weight desc.
   * When provided, top 2 currencies are shown inline with a "+N more" chip
   * if there are more than 2. When absent, the CCY section is not rendered.
   * WHY optional: currency cannot always be derived from available data.
   */
  currencies?: CurrencyChip[];
}

export function ExposureCurrencyStrip({
  portfolioId,
  currencies,
}: ExposureCurrencyStripProps) {
  // useExposure calls useAuth() internally — no need to pass the token here.
  const { data: exposure, isLoading } = useExposure(portfolioId);

  if (!portfolioId) return null;

  // ── Currency chips (top 2 inline, overflow chip for the rest) ─────────
  // WHY top 2: beyond 2 the strip overflows at 1280px viewport. A "+N more"
  // chip communicates there are more without cluttering the primary scan.
  const topCurrencies = currencies?.slice(0, 2) ?? [];
  const overflowCount = Math.max(0, (currencies?.length ?? 0) - 2);

  return (
    <div className="flex h-[22px] shrink-0 items-center border-b border-border bg-card px-3 gap-3">
      <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Exposure</span>
      {isLoading ? (
        <span className="text-[11px] font-mono text-muted-foreground">—</span>
      ) : exposure ? (
        <>
          {/* INV = invested amount; WHY show absolute + pct: traders need both the
              $ amount to size new trades and the % for allocation math. net_exposure_pct
              is a 0-1 fraction from the API — formatPercent multiplies by 100 internally. */}
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            INV {formatPrice(exposure.invested)}
            <span className="ml-1 text-muted-foreground">({formatPercent(exposure.net_exposure_pct)})</span>
          </span>
          <span className="text-[10px] text-muted-foreground">·</span>
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            CASH {formatPrice(exposure.cash)}
          </span>
          <span className="text-[10px] text-muted-foreground">·</span>
          {/* LEV = leverage ratio; >1.0x indicates margin use (rare for cash accounts) */}
          <span className="font-mono text-[11px] tabular-nums text-foreground">
            LEV {exposure.leverage.toFixed(2)}×
          </span>

          {/* ── Currency chips — only rendered when parent supplies data ──── */}
          {/* WHY gated on topCurrencies.length > 0: avoids an orphaned "CCY"
              label when the parent hasn't computed the breakdown yet. */}
          {topCurrencies.length > 0 && (
            <>
              <span className="text-[10px] text-muted-foreground">·</span>
              <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">CCY</span>
              {topCurrencies.map((c) => (
                // WHY rounded: small radius keeps the chip compact without
                // looking like a card. Matches the "4px rounded" spec in §6.1.
                <span
                  key={c.code}
                  className="inline-flex items-center gap-0.5 rounded bg-muted/40 px-1 font-mono text-[10px] text-muted-foreground"
                >
                  {c.code}
                  {/* WHY formatPercent(c.pct): c.pct is 0-1 fraction, formatPercent × 100. */}
                  <span className="tabular-nums">{formatPercent(c.pct)}</span>
                </span>
              ))}
              {overflowCount > 0 && (
                <span className="inline-flex items-center rounded bg-muted/30 px-1 font-mono text-[10px] text-muted-foreground">
                  +{overflowCount}
                </span>
              )}
            </>
          )}

          {exposure.prices_stale && (
            <span className="ml-auto text-[10px] text-muted-foreground">(stale prices)</span>
          )}
        </>
      ) : (
        <span className="text-[11px] font-mono text-muted-foreground">—</span>
      )}
    </div>
  );
}
