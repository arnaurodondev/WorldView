/**
 * components/portfolio/HoldingRealizedRow.tsx — per-instrument realized P&L strip
 * (PRD-0089 SA-B)
 *
 * WHY THIS EXISTS: The HoldingDetailPanel needs a compact 2-value row showing
 * short-term and long-term realized P&L for a specific instrument within the
 * selected portfolio. The full RealizedPnLResponse contains a
 * `breakdown_by_instrument` array — we filter to `instrumentId` and render
 * ST / LT columns.
 *
 * WHY "YTD" as period (not all-time): matches the KPI strip default and the
 * 1099-B tax-year mental model. Both the KPI strip and this row must agree on
 * the period or they'll show confusingly different numbers. "YTD" is the
 * `defaultRealizedPnLRange()` window.
 *
 * DATA SOURCE: GET /v1/portfolios/{id}/realized-pnl?period=YTD
 *   (proxied through S9; computed FIFO by S1)
 * WHO USES IT: HoldingDetailPanel (section 2)
 * DESIGN REFERENCE: PRD-0089 SA-B §E
 */

"use client";
// WHY "use client": this component calls useQuery (TanStack Query) which is
// a browser-only hook — it cannot run during SSR/RSC rendering.

import { useQuery } from "@tanstack/react-query";
import { useApiClient } from "@/lib/api-client";
import { qk } from "@/lib/query/keys";
import { cn } from "@/lib/utils";

// ── Props ─────────────────────────────────────────────────────────────────────

interface HoldingRealizedRowProps {
  portfolioId: string;
  instrumentId: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Format a dollar value as "+$X,XXX.XX" or "-$X,XXX.XX" with a sign prefix.
 * Returns "—" for null/undefined/NaN.
 *
 * WHY inline (not imported from lib/utils): lib/utils has formatPrice() but
 * it doesn't prepend the sign. A compact inline formatter keeps the component
 * self-contained rather than adding a new exported function for a minor variant.
 */
function fmtSigned(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return "—";
  const sign = val >= 0 ? "+" : "";
  return `${sign}$${Math.abs(val).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function HoldingRealizedRow({
  portfolioId,
  instrumentId,
}: HoldingRealizedRowProps) {
  const apiClient = useApiClient();

  // WHY include endDate in the key (D13 remediation): the YTD date range is
  // built inside queryFn from new Date(). Without baking the end-date into
  // the cache key, a query made at 23:59 would be served from cache the next
  // morning even though "today" has rolled over — leaving the user looking at
  // a stale YTD window. Encoding today's ISO date in the key forces a fresh
  // fetch at midnight without any manual staleTime juggling.
  //
  // WHY toISOString (Wave G QA M-005): the previous getFullYear/getMonth/
  // getDate trio used the browser's local timezone; a user east of UTC could
  // tick over to "tomorrow" locally while the backend snapshot was still on
  // yesterday's UTC date — producing a fresh cache miss that returned the
  // same data. Using ISO UTC keeps the key boundary aligned with the
  // backend's UTC date rollover.
  const todayUtc = new Date().toISOString().slice(0, 10);
  const endDate = todayUtc;
  const startDate = `${todayUtc.slice(0, 4)}-01-01`;

  // WHY qk.portfolios.realizedPnL(portfolioId, period): the key factory
  // encodes the portfolio + period; we append endDate so midnight rollover
  // produces a new cache slot. Opening AAPL then MSFT still shares the
  // request (instrumentId is NOT in the key — filtering is client-side).
  const { data, isLoading, isError } = useQuery({
    queryKey: [...qk.portfolios.realizedPnL(portfolioId, "YTD"), endDate],
    queryFn: () => apiClient.getRealizedPnL(portfolioId, startDate, endDate),
    enabled: Boolean(portfolioId),
    staleTime: 60_000, // 1 min — same as useRealizedPnL hook
    retry: false,      // 404 → show "—" immediately, don't loop
  });

  // ── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      // WHY flex gap-3: mirrors the rendered layout so the skeleton matches the
      // final pixel dimensions — no layout shift when data lands.
      <div className="flex items-center gap-3 px-3 py-1">
        {/* Label */}
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Realized
        </span>
        {/* Two skeleton pills — one for ST, one for LT */}
        <div className="h-[16px] w-16 animate-pulse rounded bg-muted" />
        <div className="h-[16px] w-16 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────
  if (isError || !data) {
    return (
      <div className="flex items-center gap-3 px-3 py-1">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Realized
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">—</span>
      </div>
    );
  }

  // ── Extract per-instrument breakdown ─────────────────────────────────────
  // The RealizedPnLResponse has `breakdown_by_instrument: RealizedPnLBreakdownItem[]`.
  // Each item only has `realized` (total) — not a pre-split ST/LT.
  // For the ST/LT split we fall back to the portfolio-level realized_short_term /
  // realized_long_term prorated by the instrument's share of total realized.
  // WHY proration (not exact per-lot ST/LT per instrument): the API's
  // breakdown_by_instrument only provides a single `realized` figure per
  // instrument. Exact per-instrument ST/LT split would require a new
  // endpoint. Proration gives a directionally correct estimate that's
  // acceptable for a compact strip display (not a tax form).
  const breakdown = data.breakdown_by_instrument.find(
    (b) => b.instrument_id === instrumentId,
  );

  if (!breakdown) {
    // This instrument had no realized P&L this year — show zeros.
    return (
      <div className="flex items-center gap-3 px-3 py-1">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          Realized
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          ST: $0.00
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          LT: $0.00
        </span>
      </div>
    );
  }

  // Prorate ST/LT split: instrument's `realized` × (portfolio_lt / portfolio_total)
  const portfolioTotal = data.total_realized;
  const ltFraction =
    portfolioTotal !== 0 ? data.realized_long_term / portfolioTotal : 0;
  const stFraction =
    portfolioTotal !== 0 ? data.realized_short_term / portfolioTotal : 0;

  const instrumentLt = breakdown.realized * ltFraction;
  const instrumentSt = breakdown.realized * stFraction;

  return (
    <div className="flex items-center gap-3 px-3 py-1">
      {/* Section label — matches the density conventions of other strips */}
      <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        Realized
      </span>

      {/* Short-term realized P&L */}
      <span
        className={cn(
          "font-mono text-[11px] tabular-nums",
          // WHY positive/negative tokens (not hardcoded green/red): design
          // system tokens adapt to light/dark theme without manual override.
          instrumentSt >= 0 ? "text-positive" : "text-negative",
        )}
      >
        ST: {fmtSigned(instrumentSt)}
      </span>

      {/* Long-term realized P&L */}
      <span
        className={cn(
          "font-mono text-[11px] tabular-nums",
          instrumentLt >= 0 ? "text-positive" : "text-negative",
        )}
      >
        LT: {fmtSigned(instrumentLt)}
      </span>
    </div>
  );
}
