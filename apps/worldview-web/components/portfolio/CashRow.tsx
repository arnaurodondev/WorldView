/**
 * components/portfolio/CashRow.tsx — single-row cash strip (PLAN-0088 Wave E E-1)
 *
 * REPLACES the previous 3-column CashManagementCard (~28-44 px tall card with
 * coloured chips + heavy border) with a single 28 px row that shows:
 *
 *     CASH 0.0% · BUYING POWER -- · SWEEP --
 *
 * WHY single-row replacement: the audit (`docs/audits/2026-05-09-qa-holdings-
 * redesign.md` §1) called out the original card as "F" rated — it always
 * showed cash=$0 because S1's `compute_portfolio_value`/`get_exposure` use
 * cases hard-code cash=0 in v1. A 28 px card communicating "$0" is wasted
 * vertical real estate. Compressing to one row keeps the field present (so
 * users notice the moment broker sweep yields land) without dominating the
 * page.
 *
 * COMPETITOR REFERENCE: Schwab StreetSmart cash row — single horizontal line,
 * 4 metrics, em-dash placeholders for unknowns.
 *
 * WHY no broker-connected vs paper-trader split: the row stays useful in
 * both modes — for paper traders all values are em-dashes, for broker-
 * connected users the cash field becomes the live value. The strip itself
 * never decides "show / hide".
 *
 * DATA: GET /v1/portfolios/{id}/exposure — `cash` field (always 0 in v1).
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx → HoldingsTab top-of-tab strip.
 * DESIGN REFERENCE: PLAN-0088 §Wave E task E-1, audit §2 wireframe row R-7.
 */

"use client";
// WHY "use client": uses TanStack Query — needs a browser fetch context.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface CashRowProps {
  /** Portfolio UUID. Null/undefined skips the fetch (loading skeleton). */
  portfolioId: string | null | undefined;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * h-7 strip: matches OverviewSidebarMetrics density. Three columns separated
 * by a vertical divider so the eye scans them like spreadsheet cells. WHY
 * `divide-x` (not borders): aligned with the existing density tokens —
 * `divide-border` resolves to the same #1f1f23 hairline used by the KPI
 * strip and the AG Grid column borders.
 */
export function CashRow({ portfolioId }: CashRowProps) {
  const { accessToken } = useAuth();

  // We reuse the existing /exposure endpoint here (it already returns `cash`)
  // — adding a new dedicated endpoint just for this row would be over-
  // engineering. The exposure endpoint is cached by TanStack Query elsewhere
  // on the page so this fetch is usually a cache hit.
  const { data, isLoading } = useQuery({
    enabled: Boolean(portfolioId && accessToken),
    queryKey: ["portfolio-exposure-cash-row", portfolioId],
    queryFn: () => createGateway(accessToken!).getExposure(portfolioId!),
    staleTime: 30_000,
  });

  // Loading skeleton — keep h-7 so the row never causes layout shift.
  if (!portfolioId || isLoading) {
    return (
      <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex-1 px-3 flex items-center gap-2">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="h-3 w-12" />
          </div>
        ))}
      </div>
    );
  }

  // PLAN-0088 P0-11 (truthful Cash / Buying Power surface).
  //
  // BEFORE: this component blindly rendered ``formatPrice(data?.cash ?? 0)``
  // which always painted "$0.00" because the v1 ``GetExposureUseCase``
  // hard-codes ``cash=0`` (no SnapTrade balance integration shipped). A
  // hard "$0.00" implies "we checked your broker, you have zero dollars",
  // which is a lie — we never asked the broker.
  //
  // AFTER: when the backend reports ``cash === 0`` we treat it as
  // "unknown / not yet wired" and render an em-dash with a hover tooltip
  // explaining what's missing. The moment SnapTrade balance sync is wired
  // (see ``docs/audits/2026-05-10-demo-stabilization-cash-balance-state.md``)
  // and the API returns a non-zero figure, the live value lights up
  // automatically without a frontend change.
  //
  // WHY no separate "balance_status" envelope: avoids a backend contract
  // change for a UI fix; the v1 cash value of 0 is the unambiguous
  // "no broker sync yet" signal because no real portfolio with holdings
  // has literal $0 cash. When v2 backend wiring lands, the upgrade path
  // is to keep the UI as-is and let the real value flow through.
  const rawCash = data?.cash;
  const cashKnown = typeof rawCash === "number" && rawCash > 0;

  return (
    <div className="flex h-7 items-stretch divide-x divide-border border-b border-border bg-card font-mono text-[11px]">
      {/* CASH cell — em-dash + tooltip when value is unknown / pending
          broker sync. The title attribute is the lightweight tooltip
          surface that matches the rest of the dense grid (no shadcn
          Tooltip wrapper here — it would add a portal per row and the
          whole row is 28px tall). */}
      <div
        className="flex-1 px-3 flex items-center gap-2"
        title={
          cashKnown
            ? undefined
            : "Cash and buying power are not synced yet. Connect a brokerage in Settings to enable live balances."
        }
      >
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          CASH
        </span>
        {cashKnown ? (
          <span className="tabular-nums text-foreground">{formatPrice(rawCash)}</span>
        ) : (
          <span className="tabular-nums text-muted-foreground" aria-label="Cash unavailable — broker sync pending">
            —
          </span>
        )}
      </div>

      {/* BUYING POWER — placeholder until SnapTrade cash + margin endpoints
          land. Em-dash with a label is the explicit "we know about this
          field, no data yet" signal — better than hiding the field. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          BUYING POWER
        </span>
        <span className="tabular-nums text-muted-foreground">—</span>
      </div>

      {/* SWEEP RATE — broker sweep APY. SnapTrade does not currently expose
          this (audit §1 row 1). Field stays so it lights up the moment the
          adapter publishes the value, without a frontend deploy. */}
      <div className="flex-1 px-3 flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          SWEEP RATE
        </span>
        <span className="tabular-nums text-muted-foreground">—</span>
      </div>
    </div>
  );
}
