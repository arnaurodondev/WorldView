/**
 * RecentActivityStrip — compact last-8-transactions feed (transactions only, no sync events).
 *
 * WHY THIS EXISTS: The old RecentActivityFeed mixed transactions + broker sync events.
 * C-34 locks that sync events move to BrokerageStatusBanner — the activity strip
 * stays focused on actual trade events (BUY/SELL/DIVIDEND). 8 rows at 18px each
 * = 144px, similar to the old feed but lighter.
 * WHO USES IT: portfolio overview page, below ContributorsStrip.
 * DATA SOURCE: GET /v1/portfolios/{id}/transactions?limit=8 (via TanStack Query).
 * DESIGN REFERENCE: PRD-0089 W2 §4.14, C-34, C-35
 */
"use client";
// WHY "use client": useQuery (TanStack) requires React context; date formatting uses Date.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { formatPrice } from "@/lib/utils";
// WHY qk.portfolios.transactions: centralised key factory keeps cache entries
// consistent across all call sites (PLAN-0059-C C-2 migration).
import { QK_VERSION } from "@/lib/query/keys";

interface RecentActivityStripProps {
  portfolioId: string | null | undefined;
}

// C-35 date format: "12:18" today / "Yest" yesterday / "Xd ago" ≤7d / "Jan 12" older
function formatActivityDate(isoUtc: string): string {
  const txDate = new Date(isoUtc);
  const now = new Date();
  const diffMs = now.getTime() - txDate.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) {
    // Same calendar day — show time
    return txDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  if (diffDays === 1) return "Yest";
  if (diffDays <= 7) return `${diffDays}d`;
  return txDate.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function RecentActivityStrip({ portfolioId }: RecentActivityStripProps) {
  const { accessToken } = useAuth();

  const { data, isLoading } = useQuery({
    // WHY separate key from full transactions: this strip fetches limit=8 only;
    // sharing the full transactions key would overwrite the paginated cache entry.
    // Using the nested detail key here (not the flat legacy key) so it cascades
    // under portfolio detail invalidation but is scoped to "recent-8".
    queryKey: portfolioId
      ? ([QK_VERSION, "portfolios", "detail", portfolioId, "transactions", "recent-8"] as const)
      : (["disabled"] as const),
    queryFn: () => createGateway(accessToken).getTransactions(portfolioId!, { limit: 8 }),
    enabled: !!portfolioId && !!accessToken,
    staleTime: 60_000,
  });

  const rows = data?.transactions ?? [];

  if (!portfolioId) return null;

  return (
    <div className="shrink-0 bg-card border-b border-border">
      <div className="flex h-[22px] items-center px-3 border-b border-border">
        <span className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Recent Activity</span>
      </div>
      {isLoading ? (
        <div className="flex items-center px-3 h-[22px]">
          <span className="font-mono text-[11px] text-muted-foreground">loading…</span>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex items-center px-3 h-[22px]">
          <span className="font-mono text-[11px] text-muted-foreground">No transactions yet</span>
        </div>
      ) : (
        rows.map((tx) => (
          <div key={tx.transaction_id} className="flex items-center h-[18px] px-3 gap-3">
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground w-10 shrink-0">
              {formatActivityDate(tx.executed_at)}
            </span>
            <span className={`font-mono text-[10px] w-8 shrink-0 ${tx.type === "BUY" ? "text-positive" : tx.type === "SELL" ? "text-negative" : "text-muted-foreground"}`}>
              {tx.type}
            </span>
            <span className="font-mono text-[11px] text-primary">{tx.ticker}</span>
            <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{tx.quantity.toLocaleString()}</span>
            <span className="font-mono text-[10px] tabular-nums text-foreground">{formatPrice(tx.price)}</span>
          </div>
        ))
      )}
    </div>
  );
}
