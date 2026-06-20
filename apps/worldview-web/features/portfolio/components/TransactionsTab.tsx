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
// PRD-0114 W5-T02/03: server-side filter bar + export button.
import { TransactionsFilterBar } from "@/components/portfolio/TransactionsFilterBar";
import { ExportTransactionsButton } from "@/components/portfolio/ExportTransactionsButton";
import type { TransactionsResponse } from "@/types/api";
import type { HoldingOverviewMap } from "@/features/portfolio/lib/kpi";
import type { TransactionFilters, BackendTransactionParams } from "@/features/portfolio/hooks/useTransactionsFilterState";

interface TransactionsTabProps {
  activePortfolioId: string | null;
  txLoading: boolean;
  transactionsResp: TransactionsResponse | undefined;
  holdingOverviews: HoldingOverviewMap | undefined;
  /** Open the Connect Brokerage modal (lives at page level for OAuth survival). */
  onConnect: () => void;
  /**
   * R1 sprint: opens the AddPositionDialog so a user with zero transactions
   * can record their first trade from the empty state. Optional — pass
   * undefined for read-only contexts (e.g. the ROOT aggregate portfolio,
   * which rejects POST /v1/transactions) and the CTA button is hidden.
   */
  onAddPosition?: () => void;
  /**
   * R1 sprint: server-side pagination callback. When provided AND
   * `transactionsResp.total > transactionsResp.limit`, a Prev/Next pager
   * strip renders below the table. The new offset flows back into
   * usePortfolioData's transactions query (the offset is part of its
   * queryKey, so each page is its own cache entry).
   */
  onTxOffsetChange?: (offset: number) => void;

  // ── PRD-0114 W5-T02/03: backend-driven filter state ──────────────────────
  /**
   * filterState — current URL-synced filter values from useTransactionsFilterState().
   * When provided, the filter bar renders above the transaction table.
   * When undefined, the old layout (no filter bar) is preserved for callers
   * that haven't upgraded yet.
   */
  filterState?: TransactionFilters;
  /** onChange for the filter bar — updates URL params via nuqs. */
  onFilterChange?: (f: TransactionFilters) => void;
  /** Reset all filter slots to defaults. */
  onFilterReset?: () => void;
  /** Typed S9 query params derived from filterState via toBackendParams(). */
  backendFilterParams?: BackendTransactionParams;
  /** Auth token for the server-side CSV export button. */
  accessToken?: string | null;
  /** Ticker strings for the filter bar's suggest-as-you-type ticker input. */
  tickerSuggestions?: string[];
}

export function TransactionsTab({
  activePortfolioId,
  txLoading,
  transactionsResp,
  holdingOverviews,
  onConnect,
  onAddPosition,
  onTxOffsetChange,
  filterState,
  onFilterChange,
  onFilterReset,
  backendFilterParams,
  accessToken,
  tickerSuggestions,
}: TransactionsTabProps) {
  // WHY brokeragesSectionExpanded default false: the primary use of the
  // Transactions tab is reviewing transaction history — the brokerage
  // connection panel is secondary. Collapsed by default keeps the
  // transaction table immediately visible.
  const [brokeragesSectionExpanded, setBrokeragesSectionExpanded] =
    useState(false);

  // ── R1 sprint: pager derivation ──────────────────────────────────────────
  // All values come straight from the server response so the pager always
  // reflects what S1 actually applied (defensive against limit clamping).
  // WHY `limit > 0` guard: a malformed response with limit=0 would make the
  // pager divide by zero / loop — degrade to "no pager" instead.
  const total = transactionsResp?.total ?? 0;
  const offset = transactionsResp?.offset ?? 0;
  const limit = transactionsResp?.limit ?? 0;
  const showPager =
    onTxOffsetChange != null && limit > 0 && total > limit;
  // 1-based human-readable row range: "1–100 of 250".
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = Math.min(offset + limit, total);
  // R4 hardening (a11y): 1-based page position for the pager button labels.
  // "Previous transactions page" alone told a screen-reader user nothing
  // about WHERE they are — sighted users get that from the row-range counter
  // on the right, which is visually adjacent but not programmatically
  // associated with the buttons. Both derivations are guarded by showPager's
  // `limit > 0` check before render, so no division-by-zero can surface.
  const pageNum = limit > 0 ? Math.floor(offset / limit) + 1 : 1;
  const pageCount = limit > 0 ? Math.max(1, Math.ceil(total / limit)) : 1;

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
        <div className="flex h-9 items-center gap-1.5 px-3">
          <button
            onClick={() => setBrokeragesSectionExpanded((v) => !v)}
            aria-expanded={brokeragesSectionExpanded}
            className="flex flex-1 items-center gap-1.5 text-left"
          >
            <ChevronRight
              className={cn(
                "h-3 w-3 text-muted-foreground transition-transform duration-150",
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
              // R3 polish: focus-visible ring for keyboard parity with hover.
              className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 transition-colors shrink-0 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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

      {/* ── PRD-0114 W5-T02/03: Filter bar + export button ──────────────────
          Only renders when the caller passes filterState + handlers.
          Backwards compatible: if filterState is undefined, the old layout
          with no filter bar is preserved unchanged for existing callers. */}
      {filterState && onFilterChange && onFilterReset && activePortfolioId && (
        <div className="shrink-0 flex items-center gap-2 border-b border-border/60 px-2 py-1 bg-card/50">
          {/* TransactionsFilterBar renders the type pills + date/ticker inputs.
              filteredItems=[] disables the legacy client-side CSV export button
              inside the filter bar (it only exports the current page); the new
              ExportTransactionsButton below handles server-side export instead. */}
          <TransactionsFilterBar
            value={filterState}
            onChange={(f) => {
              onFilterChange(f);
              // Reset pagination to page 1 whenever filters change (PRD-0114 W5).
              onTxOffsetChange?.(0);
            }}
            // WHY tickerOptions (not tickerSuggestions): TransactionsFilterBar was
            // built before W5 and uses tickerOptions as the existing prop name.
            // We pass tickerSuggestions (or empty array) through here.
            tickerOptions={tickerSuggestions ?? []}
            // WHY 0 for total/filteredCount: the filter bar shows "X / Y" counts
            // but we don't have the unfiltered total from the server here (the
            // total in transactionsResp is for the FILTERED set). Passing 0
            // hides the count display or shows "0" — acceptable until W3 ships
            // a dedicated endpoint for unfiltered counts.
            totalCount={transactionsResp?.total ?? 0}
            filteredCount={transactionsResp?.total ?? 0}
            // WHY []: filteredItems drives the client-side CSV export button.
            // Setting it to [] disables that button — the server-side
            // ExportTransactionsButton to the right handles exports instead.
            filteredItems={[]}
          />
          <div className="ml-auto shrink-0">
            <ExportTransactionsButton
              portfolioId={activePortfolioId}
              filter={backendFilterParams ?? {}}
              accessToken={accessToken}
            />
          </div>
        </div>
      )}

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
            // R1 sprint: empty-state CTA — record the first trade without
            // hunting for the header button. Undefined hides the CTA (e.g.
            // for the read-only ROOT aggregate).
            onAddFirst={onAddPosition}
          />
        )}
      </div>

      {/* ── R1 sprint: server-side pagination strip ─────────────────────── */}
      {/* WHY below the table (not in the filter bar): the filter bar operates
          on the CURRENT page client-side; the pager swaps the page itself.
          Mixing them would suggest filters span all pages — they don't (the
          per-page scope is reported by the "X / Y" counter in the bar). */}
      {showPager && (
        <div
          data-testid="transactions-pager"
          className="flex h-7 shrink-0 items-center gap-2 border-t border-border bg-card px-2"
        >
          <button
            type="button"
            // R4 hardening: page context in the accessible name (see the
            // pageNum/pageCount derivation above). The label keeps the
            // original "Previous transactions page" prefix — tests and any
            // AT user scripts matching on it keep working.
            aria-label={`Previous transactions page (currently page ${pageNum} of ${pageCount})`}
            disabled={offset === 0}
            onClick={() => onTxOffsetChange(Math.max(0, offset - limit))}
            // R3 polish: focus-visible ring — pager buttons are prime
            // keyboard targets (page through history without the mouse).
            className="h-5 px-2 font-mono text-[10px] uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground transition-colors enabled:hover:text-foreground enabled:hover:border-foreground disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            ‹ Prev
          </button>
          <button
            type="button"
            // R4 hardening: page context (see Prev button above).
            aria-label={`Next transactions page (currently page ${pageNum} of ${pageCount})`}
            disabled={rangeEnd >= total}
            onClick={() => onTxOffsetChange(offset + limit)}
            // R3 polish: focus-visible ring (see Prev button above).
            className="h-5 px-2 font-mono text-[10px] uppercase tracking-[0.06em] border border-border rounded-[2px] text-muted-foreground transition-colors enabled:hover:text-foreground enabled:hover:border-foreground disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            Next ›
          </button>
          {/* Row-range counter — tabular-nums keeps digits aligned as the
              range changes (1–100 → 101–200). */}
          <span className="ml-auto font-mono text-[10px] tabular-nums text-muted-foreground">
            {rangeStart}–{rangeEnd} of {total}
          </span>
        </div>
      )}
    </>
  );
}
