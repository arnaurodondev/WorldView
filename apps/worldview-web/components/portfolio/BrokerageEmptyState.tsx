/**
 * BrokerageEmptyState — full-page CTA for portfolios with no data and no brokerage.
 *
 * WHY THIS EXISTS: When a user has no portfolios AND no brokerage connection,
 * the holdings table shows nothing and the KPI strip shows "$0" everywhere.
 * This empty state replaces the confusing blank page with a clear call-to-action.
 * WHO USES IT: portfolio overview page, rendered instead of all other content when
 * enrichedHoldings.length === 0 AND no brokerage connection exists.
 * DATA SOURCE: none — static CTA.
 * DESIGN REFERENCE: PRD-0089 W2 §4.15, V18
 */
import Link from "next/link";

export function BrokerageEmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 bg-background">
      <div className="text-center">
        <p className="font-mono text-[13px] text-foreground">No positions tracked yet</p>
        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
          Connect a brokerage to sync your holdings automatically,
        </p>
        <p className="font-mono text-[11px] text-muted-foreground">
          or add a portfolio manually.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Link
          href="/portfolio/brokerage"
          className="h-8 px-4 font-mono text-[11px] uppercase tracking-[0.06em] border border-primary text-primary hover:bg-primary/10 flex items-center"
        >
          Connect Brokerage
        </Link>
      </div>
    </div>
  );
}
