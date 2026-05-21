/**
 * BrokerageStatusBanner — sync status banner above the KPI strip.
 *
 * WHY THIS EXISTS: C-34 moves sync events from RecentActivityStrip to a dedicated
 * banner. When a portfolio has a connected brokerage, the PM needs to know if the
 * last sync succeeded or failed without navigating to the transactions page.
 * Collapses to nothing (renders null) when no brokerage is connected.
 * WHO USES IT: portfolio overview page, between PortfolioPageHeader and PortfolioKPIStrip.
 * DATA SOURCE: getBrokerageConnections(portfolioId) — last sync time + status.
 * DESIGN REFERENCE: PRD-0089 W2 §4.22, V23
 */
"use client";
// WHY "use client": useQuery (TanStack) requires React context; cn() utility.

import { useQuery } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface BrokerageStatusBannerProps {
  portfolioId: string | null;
}

function formatSyncAge(isoUtc: string | null | undefined): string {
  if (!isoUtc) return "unknown";
  const diffMs = Date.now() - new Date(isoUtc).getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function BrokerageStatusBanner({ portfolioId }: BrokerageStatusBannerProps) {
  const { accessToken } = useAuth();

  const { data: connections } = useQuery({
    // WHY flat key (not qk.brokerage.*): this query is scoped to a portfolioId;
    // the existing brokerage keys in qk.brokerage are portfolio-agnostic.
    // Matches the key used in HoldingsTab.tsx for TanStack dedup.
    queryKey: portfolioId ? (["brokerage-connections", portfolioId] as const) : (["disabled"] as const),
    queryFn: () => createGateway(accessToken).getBrokerageConnections(portfolioId!),
    enabled: !!portfolioId && !!accessToken,
    staleTime: 60_000,
  });

  // No brokerage = no banner (collapses to nothing as specified in C-34)
  if (!connections?.length) return null;

  // WHY connections[0]: most portfolios have one brokerage. Multi-brokerage
  // (future) would show the most-recent-error or the first active.
  const conn = connections[0];
  // S9 returns "active" | "error" | "pending" | "disconnected"
  const hasError = conn.status === "error";

  return (
    <div className={cn(
      "flex h-[22px] shrink-0 items-center border-b border-border px-3 gap-3",
      hasError ? "bg-negative/10" : "bg-positive/5",
    )}>
      {/* WHY text-[9px] dot (not Lucide icon): smallest legible indicator;
          importing an icon for a single px dot wastes parse budget. */}
      <span className={cn("text-[9px]", hasError ? "text-negative" : "text-positive")}>●</span>
      <span className="font-mono text-[10px] text-muted-foreground">
        {conn.brokerage_name ?? "Brokerage"}
      </span>
      <span className="font-mono text-[10px] text-foreground">
        {hasError ? "Sync failed" : `Last sync ${formatSyncAge(conn.last_synced_at)}`}
      </span>
      {hasError && (
        <span className="font-mono text-[10px] text-negative">— retry on /portfolio/transactions</span>
      )}
    </div>
  );
}
