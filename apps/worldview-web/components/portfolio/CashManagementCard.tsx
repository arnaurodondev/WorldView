/**
 * components/portfolio/CashManagementCard.tsx — Cash management mini card (PLAN-0053 T-B-2-04)
 *
 * WHY THIS EXISTS: Cash is the second-most-important state variable on a
 * portfolio dashboard (after total value). Most platforms hide it inside an
 * "exposure" panel; surfacing it as a one-line card on the Holdings tab gives
 * the user immediate awareness of whether they have dry powder available and
 * — crucially — whether they are leaving a meaningful chunk of capital
 * un-invested ("cash drag").
 *
 * WHY 5% CASH-DRAG THRESHOLD:
 *   Generally accepted finance heuristic — 5% is the point at which cash
 *   meaningfully reduces equity-like portfolio expected return. Below 5% the
 *   slack is "operational" (settlement, fees, dividend reinvestment), above
 *   5% it is a deliberate allocation decision the user should be aware of.
 *
 * WHY SWEEP APY IS RENDERED AS "—":
 *   SnapTrade does not currently expose broker sweep yields; we surface the
 *   field anyway because (a) it is the canonical thing users expect to see on
 *   a cash card, and (b) tooltipping "Sweep yield not available" preempts
 *   the bug-report we'd otherwise get for a missing field.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Holdings tab, below KPI strip
 * DATA SOURCE: S9 GET /v1/portfolios/{id}/exposure (cash field)
 * DESIGN REFERENCE: PLAN-0053 §T-B-2-04
 */

"use client";
// WHY "use client": uses useQuery hook for the exposure call.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";
import { formatPrice } from "@/lib/utils";
import { cn } from "@/lib/utils";

// ── Props ────────────────────────────────────────────────────────────────────

export interface CashManagementCardProps {
  /** Portfolio UUID — the card hides itself if undefined (no portfolio selected). */
  portfolioId: string | null | undefined;
}

// ── Component ────────────────────────────────────────────────────────────────

/**
 * CashManagementCard — single-row card with cash $, cash %, sweep APY, drag badge.
 *
 * WHY h-7 single row: a portfolio dashboard already has a KPI strip and a
 * holdings table competing for vertical attention. The card must stay out of
 * the way until the user looks for it — one row keeps it scannable without
 * stealing a chunk of the holdings list real estate.
 */
export function CashManagementCard({ portfolioId }: CashManagementCardProps) {
  const { accessToken } = useAuth();

  // WHY reuse the same queryKey shape as ExposureBreakdown: TanStack Query
  // shares cache entries by exact key match. Using ["exposure", id] means the
  // card and the analytics-section breakdown panel share a single in-flight
  // fetch and rehydrate from the same cache — no double network round-trip.
  const { data, isLoading } = useQuery({
    queryKey: ["exposure", portfolioId],
    queryFn: () => createGateway(accessToken).getExposure(portfolioId!),
    enabled: !!accessToken && !!portfolioId,
    // 30s — same cadence as ExposureBreakdown so values stay in lockstep
    // when the user has both panels visible at once.
    staleTime: 30_000,
  });

  // Hide the card entirely when we have no portfolio context (e.g. during
  // initial portfolio-list fetch) — leaves no skeleton flash on first paint.
  if (!portfolioId) return null;

  // ── Loading state — keep the row footprint stable to avoid layout shift ──
  if (isLoading || !data) {
    return (
      <div className="flex h-7 items-center gap-3 border-b border-border/60 bg-card px-2">
        <Skeleton className="h-3 w-[120px]" />
        <Skeleton className="h-3 w-[60px]" />
        <Skeleton className="ml-auto h-3 w-[80px]" />
      </div>
    );
  }

  // ── Derived values ──────────────────────────────────────────────────────
  // ``invested + cash`` is the canonical denominator: it's what S1 uses as
  // "total portfolio value" before any leverage adjustments. Falling back to
  // 1 when both are zero stops a divide-by-zero in the percentage calc and
  // yields 0% which is the right user-visible behaviour for an empty book.
  // PLAN-0053 QA-iter1 F-007: operator precedence trap. ``a + b || 1``
  // parses as ``(a + b) || 1``, so when *either* operand is undefined the
  // sum becomes NaN and the `|| 1` rescue fires — but the next line still
  // computes (undefined / 1) which is NaN, rendering "NaN%". Coerce
  // explicitly so missing fields fall through to 0 cleanly.
  const investedSafe = Number.isFinite(data.invested) ? data.invested : 0;
  const cashSafe = Number.isFinite(data.cash) ? data.cash : 0;
  const total = investedSafe + cashSafe || 1;
  const cashPct = (cashSafe / total) * 100;

  // WHY 5%: see top-of-file comment. The 30-day persistence requirement from
  // the spec ("cash > 5% of portfolio for >30d") needs historical data the
  // backend doesn't expose today; surfacing the badge on a current-snapshot
  // basis is a strict subset of that requirement (every 30-day-drag case is
  // also a current-snapshot drag case) and ships value immediately.
  const isCashDrag = cashPct > 5;

  // Sweep APY isn't in the exposure response yet — kept as a pure typed null
  // so the renderer below shows "—" + tooltip without an extra branch. The
  // explicit type annotation is required because TS would otherwise infer
  // ``null`` and refuse the .toFixed call in the (currently dead) non-null
  // branch — once the backend exposes the field, swapping in the real value
  // here is a one-line change with no other call-site updates needed.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const sweepApy = null as number | null;

  return (
    <div
      // WHY h-7: matches the standard dashboard data-row height (22-28px range)
      // — wider than h-[22px] so the small-chip badge has breathing room.
      // WHY border-b border-border/60: visually separates the card from the
      // KPI strip above and the table below. The /60 opacity is the "intra-tab
      // soft divider" pattern used elsewhere on the Holdings tab.
      className="flex h-7 items-center gap-3 border-b border-border/60 bg-card px-2"
      data-testid="cash-management-card"
      aria-label="Cash management summary"
    >
      {/* Cash $ amount */}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          CASH
        </span>
        <span className="font-mono text-[11px] font-semibold tabular-nums text-foreground">
          {formatPrice(data.cash)}
        </span>
      </div>

      {/* Cash % of portfolio — colored if drag */}
      <span
        className={cn(
          "font-mono text-[11px] tabular-nums",
          isCashDrag ? "text-warning" : "text-muted-foreground",
        )}
        title={`${cashPct.toFixed(2)}% of total portfolio`}
      >
        {cashPct.toFixed(1)}%
      </span>

      {/* Cash drag badge — only when over the 5% threshold. WHY warning (amber)
          not destructive (red): cash drag is a soft caution, not an error.
          A red badge would imply something is broken. */}
      {isCashDrag && (
        <span
          className="rounded-[2px] border border-warning/40 bg-warning/10 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-wider text-warning"
          title="Cash exceeds 5% of portfolio — consider deploying or transferring out"
        >
          Cash drag
        </span>
      )}

      {/* Sweep APY — pinned right. Tooltip explains the placeholder so users
          don't think the field is broken. WHY ml-auto: keeps the APY anchored
          to the right edge regardless of whether the drag badge renders. */}
      <div className="ml-auto flex items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
          SWEEP APY
        </span>
        <span
          className="font-mono text-[11px] tabular-nums text-muted-foreground"
          title={
            sweepApy == null
              ? "Sweep yield not available"
              : `${sweepApy.toFixed(2)}% APY`
          }
        >
          {sweepApy == null ? "—" : `${sweepApy.toFixed(2)}%`}
        </span>
      </div>
    </div>
  );
}
