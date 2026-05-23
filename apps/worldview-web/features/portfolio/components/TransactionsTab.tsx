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
 *
 * PRD-0089 SA-C: added TransactionsBrokerageStatusBar, TransactionsFilterBar
 * (URL-synced via useTransactionsFilterState), TransactionsTotalsRow, and
 * wired the filter state into TransactionsTable.
 */

"use client";
// WHY "use client": this component owns the brokerage-section collapse
// state via useState and binds onClick handlers. Also uses nuqs hooks
// (useTransactionsFilterState) which require the browser's URL API.

import { useState, useMemo } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { TransactionsFilterBar } from "@/components/portfolio/TransactionsFilterBar";
import { TransactionsTotalsRow } from "@/components/portfolio/TransactionsTotalsRow";
import { TransactionsBrokerageStatusBar } from "@/components/portfolio/TransactionsBrokerageStatusBar";
import { ConnectedBrokeragesList } from "@/components/brokerage/ConnectedBrokeragesList";
import { useTransactionsFilterState } from "@/features/portfolio/hooks/useTransactionsFilterState";
import type { TransactionsResponse } from "@/types/api";
import type { HoldingOverviewMap } from "@/features/portfolio/lib/kpi";
import type { Transaction } from "@/types/api";

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

 // ── URL-synced filter state (PRD-0089 SA-C Task 7) ─────────────────────
 // WHY here (not inside TransactionsTable): the filter bar, the table, and
 // the totals row all need access to the same filter values. Lifting state
 // to this component lets all three stay in sync without prop-drilling into
 // deeply nested internals.
 const { filters, setFilters, resetFilters } = useTransactionsFilterState();

 // ── All transactions (unfiltered) ───────────────────────────────────────
 const allTransactions = transactionsResp?.transactions ?? [];

 // ── Ticker options for the filter bar datalist ──────────────────────────
 // WHY memoised: the ticker set is derived from all transactions. It changes
 // only when a new sync brings new instruments — not on every filter change.
 const tickerOptions = useMemo(() => {
  const seen = new Set<string>();
  for (const tx of allTransactions) {
   if (tx.ticker) seen.add(tx.ticker);
   // Fallback: enrich from holdingOverviews if tx.ticker is empty.
   const ov = holdingOverviews?.[tx.instrument_id];
   if (ov?.ticker) seen.add(ov.ticker);
  }
  return Array.from(seen).sort();
 }, [allTransactions, holdingOverviews]);

 // ── Compute filtered items for TransactionsTotalsRow + CSV export ────────
 // WHY replicate filter logic: TransactionsTotalsRow needs the filtered
 // Transaction[] so it can sum aggregates. We apply the same filter logic
 // here rather than pulling the array up through TransactionsTable's internals.
 //
 // This is intentional duplication — TransactionsTable owns the canonical
 // filtered render; this is a summary-only slice used by sibling components.
 const filteredForTotals = useMemo((): Transaction[] => {
  const sorted = [...allTransactions].sort((a, b) =>
   b.executed_at.localeCompare(a.executed_at),
  );

  // Map external filter type to Transaction.type
  const typeMatch = (txType: string): boolean => {
   if (filters.type === "All" || filters.type === "") return true;
   if (filters.type === "DIV") return txType === "DIVIDEND";
   return txType === filters.type;
  };

  return sorted.filter((tx) => {
   if (!typeMatch(tx.type)) return false;
   if (filters.dateFrom && tx.executed_at.slice(0, 10) < filters.dateFrom) return false;
   if (filters.dateTo && tx.executed_at.slice(0, 10) > filters.dateTo) return false;
   if (filters.ticker.trim()) {
    const t = tx.ticker.toLowerCase();
    if (!t.includes(filters.ticker.trim().toLowerCase())) return false;
   }
   if (filters.currency && filters.currency !== "") {
    if (tx.currency !== filters.currency) return false;
   }
   if (filters.search.trim()) {
    const q = filters.search.trim().toLowerCase();
    const matches =
     tx.ticker.toLowerCase().includes(q) ||
     tx.type.toLowerCase().includes(q) ||
     (tx.notes ?? "").toLowerCase().includes(q);
    if (!matches) return false;
   }
   return true;
  });
 }, [allTransactions, filters]);

 return (
  // WHY flex flex-col: the brokerage section sits above the transactions
  // table. Using flex-col makes the section stack vertically and lets the
  // table take the remaining height.
  <>
   {/* ── PRD-0089 SA-C: Brokerage status bar (always visible, compact) ─ */}
   {/* WHY at the very top: the status bar is a health indicator. Placing
       it above even the filter bar ensures it's always visible regardless
       of scroll position. Its 22px height is minimal enough to not crowd
       the primary content. */}
   <TransactionsBrokerageStatusBar portfolioId={activePortfolioId} />

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

   {/* ── PRD-0089 SA-C: URL-synced filter bar ──────────────────────── */}
   {/* WHY above the table: filters affect what is shown — showing the
       filter controls at the top follows the standard "filter → result"
       visual flow. */}
   {!txLoading && (
    <TransactionsFilterBar
     value={filters}
     onChange={setFilters}
     tickerOptions={tickerOptions}
     totalCount={allTransactions.length}
     filteredCount={filteredForTotals.length}
     filteredItems={filteredForTotals}
    />
   )}

   {/* ── Transaction list (always visible below brokerage section) ──── */}
   <div className="flex-1 min-h-0 flex flex-col">
    {txLoading ? (
     <div className="space-y-px p-3">
      {Array.from({ length: 6 }).map((_, i) => (
       <Skeleton key={i} className="h-[22px] w-full" />
      ))}
     </div>
    ) : (
     <>
      <TransactionsTable
       transactions={allTransactions}
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
       // Pass URL-synced filters so the table reflects the filter bar state.
       // WHY hideInternalFilterBar: TransactionsFilterBar above is now the
       // canonical filter UI. Hiding the table's built-in bar avoids showing
       // two filter bars (confusing and redundant).
       externalFilters={{
        type: filters.type,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        ticker: filters.ticker,
        currency: filters.currency,
        search: filters.search,
       }}
       hideInternalFilterBar
      />

      {/* ── PRD-0089 SA-C: Aggregates totals row ────────────────── */}
      {/* WHY below the table: the totals summarise what is visible above.
          Sticky bottom-0 keeps it anchored regardless of scroll depth. */}
      {filteredForTotals.length > 0 && (
       <TransactionsTotalsRow filtered={filteredForTotals} />
      )}
     </>
    )}
   </div>
   {/* WHY outside the flex-1 div: the Reset button in the filter bar is
       already integrated into TransactionsFilterBar. If needed in the
       future, a footer can be added here without restructuring the layout. */}
  </>
 );
}
