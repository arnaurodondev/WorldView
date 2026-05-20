/**
 * features/portfolio/components/TransactionsTab.tsx — Transactions tab body.
 *
 * WHY THIS EXISTS (PLAN-0059 E-2 follow-up): the Transactions tab carried
 * a collapsible Connected Brokerages panel above the transactions table
 * (~80 LOC inline). Lifting it into its own component keeps the page
 * focused on tab routing and lets the brokerage-section expansion state
 * live next to the markup that uses it.
 *
 * BEHAVIOR PARITY: identical collapse/expand UX, identical "+ Connect"
 * affordance, identical 6-row skeleton dimensions, and identical
 * tickerByInstrumentId projection (the gateway returns tx.ticker = ""
 * because S1's TransactionListItem omits it; we reuse the holdings'
 * company-overview map to enrich without an extra round-trip).
 */

"use client";
// WHY "use client": this component owns the brokerage-section collapse
// state via useState and binds onClick handlers.

import { useState } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { ConnectedBrokeragesList } from "@/components/brokerage/ConnectedBrokeragesList";
import type { TransactionsResponse } from "@/types/api";
import type { HoldingOverviewMap } from "@/features/portfolio/lib/kpi";

interface TransactionsTabProps {
 activePortfolioId: string | null;
 txLoading: boolean;
 transactionsResp: TransactionsResponse | undefined;
 holdingOverviews: HoldingOverviewMap | undefined;
 /** Open the Connect Brokerage modal (lives at page level for OAuth survival). */
 onConnect: () => void;
}

export function TransactionsTab({
 activePortfolioId,
 txLoading,
 transactionsResp,
 holdingOverviews,
 onConnect,
}: TransactionsTabProps) {
 // WHY brokeragesSectionExpanded default false: the primary use of the
 // Transactions tab is reviewing transaction history — the brokerage
 // connection panel is secondary. Collapsed by default keeps the
 // transaction table immediately visible.
 const [brokeragesSectionExpanded, setBrokeragesSectionExpanded] =
 useState(false);

 return (
 // WHY flex flex-col: the brokerage section sits above the transactions
 // table. Using flex-col makes the section stack vertically and lets the
 // table take the remaining height.
 <>
 {/* ── Brokerage connections collapsible ─────────────────────────── */}
 {/* WHY merged here: brokerage connection status is context for
 understanding which transactions came from which source. Moving
 it here eliminates the separate Brokerages tab and surfaces the
 information next to the data it explains. */}
 <div className="shrink-0 border-b border-border">
 {/* Header row — always visible, click to expand/collapse */}
 <div className="flex h-[36px] items-center gap-1.5 px-3">
 <button
 onClick={() => setBrokeragesSectionExpanded((v) => !v)}
 aria-expanded={brokeragesSectionExpanded}
 className="flex flex-1 items-center gap-1.5 text-left"
 >
 <ChevronRight
 className={cn(
 "h-3 w-3 text-muted-foreground transition-[transform] duration-150",
 brokeragesSectionExpanded && "rotate-90",
 )}
 />
 <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
 Connected Brokerages
 </span>
 </button>

 {/* Connect CTA — always reachable without expanding the section. */}
 {activePortfolioId && (
 <button
 aria-label="Connect a new brokerage"
 onClick={onConnect}
 className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 transition-colors shrink-0"
 >
 + Connect
 </button>
 )}
 </div>

 {/* Expanded brokerage list. */}
 {brokeragesSectionExpanded && (
 <div className="px-2 pb-2">
 <ConnectedBrokeragesList portfolioId={activePortfolioId ?? ""} />
 </div>
 )}
 </div>

 {/* ── Transaction list (always visible below brokerage section) ──── */}
 <div className="flex-1 min-h-0">
 {txLoading ? (
 <div className="space-y-px p-3">
 {Array.from({ length: 6 }).map((_, i) => (
 <Skeleton key={i} className="h-[22px] w-full" />
 ))}
 </div>
 ) : (
 <TransactionsTable
 transactions={transactionsResp?.transactions ?? []}
 // WHY pass holdingOverviews as ticker lookup (A-2): the gateway
 // returns tx.ticker = "" because S1's TransactionListItem omits
 // ticker. The portfolio page already fetches getCompanyOverview
 // per holding (holdingOverviews keyed by instrument_id); reusing
 // it avoids a second round-trip and guarantees the TICKER column
 // matches the holdings table for the same instrument.
 tickerByInstrumentId={Object.fromEntries(
 Object.entries(holdingOverviews ?? {}).map(([id, ov]) => [
 id,
 ov?.ticker,
 ]),
 )}
 />
 )}
 </div>
 </>
 );
}
