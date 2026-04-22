/**
 * app/(app)/portfolio/page.tsx — Full portfolio page
 *
 * WHY THIS EXISTS: The dashboard PortfolioSummary widget shows only 4 holdings.
 * This page is the "zoom in" view that traders use for deep position management:
 * reviewing all holdings with live P&L, scrolling full transaction history,
 * monitoring watchlists, and managing brokerage connections — all in one page.
 *
 * WHY FOUR TABS: Holdings / Transactions / Watchlist / Brokerages maps to the four
 * primary trader workflows:
 *   Holdings    — "Where is my money? How is each position performing?"
 *   Transactions — "What did I do recently? Am I holding too long?"
 *   Watchlist   — "What am I watching that I don't own yet?"
 *   Brokerages  — "Which brokerages feed this portfolio? Is sync healthy?"
 * Keeping them in tabs avoids a 4-panel vertical scroll marathon.
 *
 * DATA LOADING PATTERN (waterfall chain):
 *   1. getPortfolios() → pick portfolio (or let user select from dropdown)
 *   2. getHoldings(portfolioId) → positions + server-side P&L snapshot
 *   3. getBatchQuotes(instrumentIds) → live prices, refetchInterval 15s
 *   4. getTransactions(portfolioId) → history (lazy, only fetches when tab active)
 *   5. getWatchlists() → watchlist members
 *   6. getBatchQuotes(watchlistIds) → watchlist live prices, refetchInterval 30s
 *   7. getBrokerageConnections(portfolioId) → SnapTrade connections (Brokerages tab)
 *
 * WHO USES IT: Authenticated users navigating to /portfolio
 * DATA SOURCE: S9 portfolio + watchlist + brokerage routes
 * DESIGN REFERENCE: PRD-0028 §6.5 Portfolio, PRD-0022 §6.6, docs/ui/DESIGN_SYSTEM.md
 */

"use client";
// WHY "use client": All data fetching uses TanStack Query (client-side hooks),
// portfolio selector uses useState, and tab switching uses Radix UI state.
// No meaningful static content to server-render here.

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Plus, TrendingUp, TrendingDown, Link2 } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import {
  formatPrice,
  formatPercent,
  formatDateTime,
  priceChangeClass,
  cn,
} from "@/lib/utils";
import type { Portfolio, Holding, Transaction, WatchlistMember } from "@/types/api";

// ── Brokerage components ──────────────────────────────────────────────────────
// WHY import here: the Brokerages tab renders these two components.
// ConnectBrokerageModal is controlled by local state; ConnectedBrokeragesList
// owns its own query (useBrokerageConnections) keyed to the active portfolio.
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";
import { ConnectedBrokeragesList } from "@/components/brokerage/ConnectedBrokeragesList";

// ── shadcn/ui components ──────────────────────────────────────────────────────
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// ── P&L Summary Row ───────────────────────────────────────────────────────────

/**
 * PnlSummaryRow — 4 KPI tiles: Total Value | Today P&L | Unrealised P&L | Unrealised P&L%
 *
 * WHY a separate component: the same row is used in Holdings tab header.
 * Extracting it avoids duplicating the skeleton layout logic.
 */
interface PnlSummaryRowProps {
  totalValue: number;
  todayPnl: number | null;          // computed from quote.change * quantity sum
  unrealisedPnl: number;
  unrealisedPnlPct: number;
}

function PnlSummaryRow({
  totalValue,
  todayPnl,
  unrealisedPnl,
  unrealisedPnlPct,
}: PnlSummaryRowProps) {
  return (
    // WHY grid grid-cols-4: even spacing for exactly 4 KPI tiles.
    // sm:grid-cols-2 collapses on mobile so numbers don't get clipped.
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {/* ── Total Value ──────────────────────────────────────────────────── */}
      {/* WHY hover:bg-muted/50 + transition-colors on all PnL tiles: subtle hover
          feedback tells the user these tiles are interactive-looking data regions.
          transition-colors smooths the background change (no jarring flash). */}
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2 hover:bg-muted/50 transition-colors">
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Total Value
        </p>
        <p className="font-mono text-base font-semibold tabular-nums text-foreground">
          {formatPrice(totalValue)}
        </p>
      </div>

      {/* ── Today P&L ──────────────────────────────────────────────────── */}
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2 hover:bg-muted/50 transition-colors">
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Today P&amp;L
        </p>
        <p
          className={cn(
            "font-mono text-base font-semibold tabular-nums",
            priceChangeClass(todayPnl),
          )}
        >
          {todayPnl == null ? "—" : formatPrice(todayPnl)}
        </p>
      </div>

      {/* ── Unrealised P&L ──────────────────────────────────────────────── */}
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2 hover:bg-muted/50 transition-colors">
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Unrealised P&amp;L
        </p>
        <p
          className={cn(
            "font-mono text-base font-semibold tabular-nums",
            priceChangeClass(unrealisedPnl),
          )}
        >
          {formatPrice(unrealisedPnl)}
        </p>
      </div>

      {/* ── Unrealised P&L% ─────────────────────────────────────────────── */}
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2 hover:bg-muted/50 transition-colors">
        <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Unrealised P&amp;L%
        </p>
        <div
          className={cn(
            "flex items-center gap-1 font-mono text-base font-semibold tabular-nums",
            priceChangeClass(unrealisedPnlPct),
          )}
        >
          {/* WHY icon: instant visual positive/negative cue without reading the number */}
          {unrealisedPnlPct >= 0 ? (
            <TrendingUp className="h-4 w-4" />
          ) : (
            <TrendingDown className="h-4 w-4" />
          )}
          {formatPercent(unrealisedPnlPct / 100)}
        </div>
      </div>
    </div>
  );
}

// ── Holdings Table ────────────────────────────────────────────────────────────

/**
 * HoldingsTable — full holdings with live prices
 *
 * WHY not a <table>: <table> elements are hard to make responsive and scroll
 * horizontally on mobile. A CSS-grid approach (grid-cols with auto) handles
 * overflow naturally and is easier to style for the dark theme.
 *
 * WHY compute live P&L here (not trust server values):
 * getBatchQuotes() gives fresher data than holdingsResp.holdings[].current_price.
 * The server-side current_price is a snapshot from the ingestion pipeline;
 * the batch quote is cached for 5s on S9 (Valkey) and reflects the latest trade.
 */
interface HoldingsTableProps {
  holdings: Holding[];
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  onRowClick: (entityId: string) => void;
}

function HoldingsTable({ holdings, quotes, onRowClick }: HoldingsTableProps) {
  if (holdings.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center">
        <p className="text-sm text-muted-foreground">No holdings yet.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      {/* Column header row */}
      <div className="mb-1 grid min-w-[700px] grid-cols-[100px_1fr_90px_100px_110px_110px_100px_90px] gap-2 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <span>Ticker</span>
        <span>Name</span>
        <span className="text-right">Qty</span>
        <span className="text-right">Avg Cost</span>
        <span className="text-right">Current</span>
        <span className="text-right">Value</span>
        <span className="text-right">P&amp;L</span>
        <span className="text-right">P&amp;L%</span>
      </div>

      {/* Data rows */}
      <div className="space-y-0.5">
        {holdings.map((h) => {
          const quote = quotes[h.instrument_id];

          // WHY fallback chain: quote.price → h.current_price → h.average_cost
          // If market data isn't available, we at least show cost basis (break even = 0% P&L).
          const livePrice = quote?.price ?? h.current_price ?? h.average_cost;
          const holdingValue = livePrice * h.quantity;
          const pnl = (livePrice - h.average_cost) * h.quantity;
          const pnlPct = h.average_cost > 0
            ? ((livePrice - h.average_cost) / h.average_cost) * 100
            : 0;

          return (
            <div
              key={h.holding_id}
              // WHY cursor-pointer + hover:bg-muted/50: visual affordance that
              // clicking navigates to the instrument detail page
              className="grid min-w-[700px] cursor-pointer grid-cols-[100px_1fr_90px_100px_110px_110px_100px_90px] gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted/50"
              onClick={() => onRowClick(h.entity_id)}
              role="row"
              tabIndex={0}
              onKeyDown={(e) => {
                // WHY keyboard handler: accessibility — keyboard users should
                // also be able to navigate to instrument detail
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onRowClick(h.entity_id);
                }
              }}
            >
              {/* Ticker — monospace so letters align across rows */}
              <span className="font-mono text-xs font-semibold tabular-nums text-foreground">
                {h.ticker}
              </span>

              {/* Name — truncates to avoid overflow */}
              <span className="truncate text-xs text-muted-foreground">
                {h.name}
              </span>

              {/* Quantity */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {h.quantity.toLocaleString("en-US")}
              </span>

              {/* Average Cost */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {formatPrice(h.average_cost)}
              </span>

              {/* Current Price */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {formatPrice(livePrice)}
              </span>

              {/* Total Value */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {formatPrice(holdingValue)}
              </span>

              {/* P&L — colored positive/negative */}
              <span
                className={cn(
                  "text-right font-mono text-xs tabular-nums",
                  priceChangeClass(pnl),
                )}
              >
                {formatPrice(pnl)}
              </span>

              {/* P&L% — colored positive/negative */}
              <span
                className={cn(
                  "text-right font-mono text-xs tabular-nums",
                  priceChangeClass(pnlPct),
                )}
              >
                {formatPercent(pnlPct / 100)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Transactions Table ────────────────────────────────────────────────────────

/**
 * TransactionsTable — sorted newest-first, BUY green / SELL red
 *
 * WHY newest-first: traders review recent activity, not archaeological history.
 * The API returns transactions in insertion order; we sort client-side
 * because changing the API order param would affect other consumers.
 */
interface TransactionsTableProps {
  transactions: Transaction[];
}

function TransactionsTable({ transactions }: TransactionsTableProps) {
  if (transactions.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center">
        <p className="text-sm text-muted-foreground">No transactions yet.</p>
      </div>
    );
  }

  // Sort newest first (ISO timestamps compare lexicographically)
  const sorted = [...transactions].sort(
    (a, b) => b.executed_at.localeCompare(a.executed_at),
  );

  return (
    <div className="overflow-x-auto">
      {/* Column header */}
      <div className="mb-1 grid min-w-[600px] grid-cols-[130px_70px_90px_90px_100px_100px_80px] gap-2 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <span>Date</span>
        <span>Type</span>
        <span>Ticker</span>
        <span className="text-right">Qty</span>
        <span className="text-right">Price</span>
        <span className="text-right">Total</span>
        <span className="text-right">Fee</span>
      </div>

      <div className="space-y-0.5">
        {sorted.map((tx) => {
          const total = tx.quantity * tx.price;
          const isBuy = tx.type === "BUY";

          return (
            <div
              key={tx.transaction_id}
              className="grid min-w-[600px] grid-cols-[130px_70px_90px_90px_100px_100px_80px] gap-2 rounded px-2 py-1.5 text-sm"
            >
              {/* Date — font-mono tabular-nums ensures column-aligned date/time digits */}
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {formatDateTime(tx.executed_at)}
              </span>

              {/* Transaction type — BUY=green, SELL=red */}
              <span
                className={cn(
                  "font-mono text-xs font-semibold tabular-nums",
                  // WHY semantic tokens: bg-positive/text-positive and
                  // bg-negative/text-negative are defined in tailwind.config.ts
                  // via CSS variables, so they survive Tailwind purge.
                  isBuy ? "text-positive" : "text-negative",
                )}
                data-testid={`tx-type-${tx.transaction_id}`}
              >
                {tx.type}
              </span>

              {/* Ticker */}
              <span className="font-mono text-xs font-medium tabular-nums text-foreground">
                {tx.ticker}
              </span>

              {/* Qty */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {tx.quantity.toLocaleString("en-US")}
              </span>

              {/* Price per share */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {formatPrice(tx.price)}
              </span>

              {/* Total consideration */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {formatPrice(total)}
              </span>

              {/* Fee */}
              <span className="text-right font-mono text-xs tabular-nums text-muted-foreground">
                {tx.fee > 0 ? formatPrice(tx.fee) : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Watchlist Table ───────────────────────────────────────────────────────────

/**
 * WatchlistTable — members with live prices, refetchInterval 30s
 *
 * WHY 30s (not 15s like holdings): watchlist is "monitoring" mode, not
 * active position management. 30s is fresh enough without hammering S9.
 */
interface WatchlistTableProps {
  members: WatchlistMember[];
  quotes: Record<string, { price: number; change: number; change_pct: number }>;
  onRowClick: (entityId: string) => void;
}

function WatchlistTable({ members, quotes, onRowClick }: WatchlistTableProps) {
  if (members.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center">
        <p className="text-sm text-muted-foreground">Watchlist is empty.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      {/* Column header */}
      <div className="mb-1 grid min-w-[400px] grid-cols-[100px_1fr_120px_100px] gap-2 px-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <span>Ticker</span>
        <span>Name</span>
        <span className="text-right">Price</span>
        <span className="text-right">Change%</span>
      </div>

      <div className="space-y-0.5">
        {members.map((m) => {
          // WHY instrument_id for quote lookup: WatchlistMember may have null
          // instrument_id for non-equity entities (topics, companies without
          // a listed instrument). We gracefully handle null with "—".
          const quote = m.instrument_id ? quotes[m.instrument_id] : undefined;

          return (
            <div
              key={m.entity_id}
              className="grid min-w-[400px] cursor-pointer grid-cols-[100px_1fr_120px_100px] gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted/50"
              onClick={() => onRowClick(m.entity_id)}
              role="row"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onRowClick(m.entity_id);
                }
              }}
            >
              {/* Ticker */}
              <span className="font-mono text-xs font-semibold tabular-nums text-foreground">
                {m.ticker ?? "—"}
              </span>

              {/* Name */}
              <span className="truncate text-xs text-muted-foreground">
                {m.name}
              </span>

              {/* Current price */}
              <span className="text-right font-mono text-xs tabular-nums text-foreground">
                {quote ? formatPrice(quote.price) : "—"}
              </span>

              {/* Change % — colored */}
              <span
                className={cn(
                  "text-right font-mono text-xs tabular-nums",
                  quote ? priceChangeClass(quote.change_pct) : "text-muted-foreground",
                )}
              >
                {quote ? formatPercent(quote.change_pct / 100) : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const { accessToken } = useAuth();
  const router = useRouter();

  // WHY track selectedPortfolioId in state (not URL param):
  // Switching portfolios is ephemeral — we don't want the URL to change
  // and trigger a Next.js navigation for each portfolio switch.
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string | null>(null);

  // WHY local state for modal: ConnectBrokerageModal is a controlled dialog.
  // The portfolio page owns the open/close state so it can place the trigger
  // button wherever it wants (Brokerages tab header) while keeping the modal
  // definition in its own file. Only one connection attempt at a time.
  const [connectModalOpen, setConnectModalOpen] = useState(false);

  // ── Query 1: portfolio list ──────────────────────────────────────────────
  const {
    data: portfolios,
    isLoading: portfoliosLoading,
    isError: portfoliosError,
  } = useQuery({
    queryKey: ["portfolios"],
    queryFn: () => createGateway(accessToken).getPortfolios(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  // WHY derived (not directly state): we want the first portfolio as default
  // without explicitly setting state on every render or in a useEffect
  const activePortfolioId =
    selectedPortfolioId ?? portfolios?.[0]?.portfolio_id ?? null;
  const activePortfolio = portfolios?.find(
    (p) => p.portfolio_id === activePortfolioId,
  );

  // ── Query 2: holdings for selected portfolio ─────────────────────────────
  const {
    data: holdingsResp,
    isLoading: holdingsLoading,
    isError: holdingsError,
  } = useQuery({
    queryKey: ["holdings", activePortfolioId],
    queryFn: () =>
      createGateway(accessToken).getHoldings(activePortfolioId!),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 3: live quotes for holdings ───────────────────────────────────
  const holdingInstrumentIds = useMemo(
    () => holdingsResp?.holdings.map((h) => h.instrument_id) ?? [],
    [holdingsResp],
  );
  const { data: holdingsQuotesData } = useQuery({
    queryKey: ["holdings-quotes", holdingInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(holdingInstrumentIds),
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    // WHY 15s: active portfolio holdings need fresher prices than watchlist
    refetchInterval: 15_000,
    staleTime: 0,
  });

  // ── Query 4: transactions ────────────────────────────────────────────────
  const { data: transactionsResp, isLoading: txLoading } = useQuery({
    queryKey: ["transactions", activePortfolioId],
    queryFn: () =>
      createGateway(accessToken).getTransactions(activePortfolioId!, {
        limit: 100,
      }),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 5: watchlists ──────────────────────────────────────────────────
  const { data: watchlists, isLoading: watchlistsLoading } = useQuery({
    queryKey: ["watchlists"],
    queryFn: () => createGateway(accessToken).getWatchlists(),
    enabled: !!accessToken,
    staleTime: 60_000,
  });

  const firstWatchlist = watchlists?.[0];

  // ── Query 6: live quotes for watchlist members ───────────────────────────
  const watchlistInstrumentIds = useMemo(
    () =>
      (firstWatchlist?.members ?? [])
        .map((m) => m.instrument_id)
        .filter((id): id is string => id !== null),
    [firstWatchlist],
  );
  const { data: watchlistQuotesData } = useQuery({
    queryKey: ["watchlist-quotes", watchlistInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(watchlistInstrumentIds),
    enabled: watchlistInstrumentIds.length > 0 && !!accessToken,
    // WHY 30s: watchlist is monitoring mode, less critical than live holdings
    refetchInterval: 30_000,
    staleTime: 0,
  });

  // ── Computed P&L values ──────────────────────────────────────────────────
  // WHY memoize these derivations separately: the react-hooks/exhaustive-deps
  // rule flags inline `?? {}` / `?? []` as new object references every render,
  // causing the downstream useMemo to re-run unnecessarily. Wrapping each
  // derivation in its own useMemo gives stable references.
  const holdingsQuotes = useMemo(
    () => holdingsQuotesData?.quotes ?? {},
    [holdingsQuotesData],
  );
  const watchlistQuotes = useMemo(
    () => watchlistQuotesData?.quotes ?? {},
    [watchlistQuotesData],
  );
  const holdings = useMemo(
    () => holdingsResp?.holdings ?? [],
    [holdingsResp],
  );

  const { totalValue, totalCost, todayPnl } = useMemo(() => {
    let value = 0;
    let cost = 0;
    let today = 0;

    for (const h of holdings) {
      const q = holdingsQuotes[h.instrument_id];
      const livePrice = q?.price ?? h.current_price ?? h.average_cost;
      value += livePrice * h.quantity;
      cost += h.average_cost * h.quantity;
      // WHY q.change * quantity: q.change is the absolute price change today.
      // Multiplying by quantity gives today's P&L for this holding.
      if (q?.change != null) {
        today += q.change * h.quantity;
      }
    }

    return {
      totalValue: value,
      totalCost: cost,
      // WHY null when no quotes: if batch quotes haven't resolved yet,
      // we don't have today's P&L — show "—" instead of $0.
      todayPnl: Object.keys(holdingsQuotes).length > 0 ? today : null,
    };
  }, [holdings, holdingsQuotes]);

  const unrealisedPnl = totalValue - totalCost;
  const unrealisedPnlPct = totalCost > 0 ? (unrealisedPnl / totalCost) * 100 : 0;

  // ── Navigation handler ───────────────────────────────────────────────────
  function handleInstrumentClick(entityId: string) {
    // WHY entity_id in URL (not instrument_id):
    // Instrument detail pages are keyed by entity_id (ADR-F-12).
    // entity_id is the stable cross-service identifier; instrument_id is
    // market-data-specific and changes if an instrument is delisted/relisted.
    router.push(`/instruments/${encodeURIComponent(entityId)}`);
  }

  // ── Error state ──────────────────────────────────────────────────────────
  if (portfoliosError || holdingsError) {
    return (
      <div className="flex h-64 items-center justify-center p-6">
        <div className="text-center">
          <p className="text-sm font-medium text-destructive">
            Failed to load portfolio data
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Check your connection and try refreshing.
          </p>
        </div>
      </div>
    );
  }

  // ── Loading state ────────────────────────────────────────────────────────
  if (portfoliosLoading || (holdingsLoading && !holdingsResp)) {
    return (
      <div className="space-y-4 p-6">
        {/* Page header skeleton */}
        <div className="flex items-center justify-between">
          <Skeleton className="h-7 w-32" />
          <Skeleton className="h-8 w-40" />
        </div>
        {/* P&L tiles skeleton */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
        {/* Tab skeleton */}
        <Skeleton className="h-9 w-64" />
        {/* Table rows skeleton */}
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4 p-6">

      {/* ── Page header: title + portfolio selector ────────────────────── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">Portfolio</h1>

        <div className="flex items-center gap-3">
          {/* Portfolio selector — only shown if user has multiple portfolios */}
          {portfolios && portfolios.length > 1 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="gap-1">
                  <span className="font-mono text-xs tabular-nums">
                    {activePortfolio?.name ?? "Select portfolio"}
                  </span>
                  <ChevronDown className="h-3 w-3 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {portfolios.map((p: Portfolio) => (
                  <DropdownMenuItem
                    key={p.portfolio_id}
                    onClick={() => setSelectedPortfolioId(p.portfolio_id)}
                    className={cn(
                      "text-xs",
                      p.portfolio_id === activePortfolioId &&
                        "text-primary font-medium",
                    )}
                  >
                    {p.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {/*
           * "Add Position" button — placeholder for Wave F-10 transaction modal.
           * WHY disabled+tooltip: the spec says to show the button as a stub
           * in Wave F-9 without the modal implementation. Disabled state
           * + title tooltip communicates "coming soon" without custom UI.
           */}
          <Button
            size="sm"
            disabled
            title="Coming soon — add a position to your portfolio"
            className="gap-1 opacity-60"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Position
          </Button>
        </div>
      </div>

      {/* ── P&L Summary row (always visible above tabs) ────────────────── */}
      {holdingsResp && (
        <PnlSummaryRow
          totalValue={totalValue}
          todayPnl={todayPnl}
          unrealisedPnl={unrealisedPnl}
          unrealisedPnlPct={unrealisedPnlPct}
        />
      )}

      {/* ── Tabs ────────────────────────────────────────────────────────── */}
      <Tabs defaultValue="holdings">
        <TabsList>
          <TabsTrigger value="holdings">Holdings</TabsTrigger>
          <TabsTrigger value="transactions">Transactions</TabsTrigger>
          <TabsTrigger value="watchlist">Watchlist</TabsTrigger>
          {/* WHY Brokerages tab: PLAN-0022 Wave E-1 — SnapTrade brokerage integration.
              The tab is always visible regardless of connection count so users can
              always find the Connect Brokerage button without hunting for it. */}
          <TabsTrigger value="brokerages">Brokerages</TabsTrigger>
        </TabsList>

        {/* ── Holdings Tab ─────────────────────────────────────────────── */}
        <TabsContent value="holdings">
          <Card>
            <CardHeader className="pb-1 pt-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Holdings
                  {holdings.length > 0 && (
                    // WHY count badge: traders want instant "how many positions" answer
                    <Badge variant="secondary" className="ml-2">
                      {holdings.length}
                    </Badge>
                  )}
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              {holdingsLoading && !holdingsResp ? (
                // Inline skeleton for holdings list
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : (
                <HoldingsTable
                  holdings={holdings}
                  quotes={holdingsQuotes}
                  onRowClick={handleInstrumentClick}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Transactions Tab ─────────────────────────────────────────── */}
        <TabsContent value="transactions">
          <Card>
            <CardHeader className="pb-1 pt-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Transactions
                  {transactionsResp && transactionsResp.total > 0 && (
                    <Badge variant="secondary" className="ml-2">
                      {transactionsResp.total}
                    </Badge>
                  )}
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              {txLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : (
                <TransactionsTable
                  transactions={transactionsResp?.transactions ?? []}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Watchlist Tab ─────────────────────────────────────────────── */}
        <TabsContent value="watchlist">
          <Card>
            <CardHeader className="pb-1 pt-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Watchlist
                  {firstWatchlist && (
                    <span className="ml-2 text-foreground">
                      {firstWatchlist.name}
                    </span>
                  )}
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              {watchlistsLoading ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : (
                <WatchlistTable
                  members={firstWatchlist?.members ?? []}
                  quotes={watchlistQuotes}
                  onRowClick={handleInstrumentClick}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── Brokerages Tab ────────────────────────────────────────────── */}
        {/*
         * WHY a dedicated tab (not a settings panel):
         * Brokerage sync status is operationally important — traders need to know
         * if their data is fresh. Putting it in the portfolio context (not settings)
         * keeps it visible alongside the data it affects.
         *
         * DATA: ConnectedBrokeragesList owns its own query keyed to activePortfolioId.
         * The query is not triggered until this tab mounts, keeping page load fast.
         */}
        <TabsContent value="brokerages">
          <Card>
            <CardHeader className="pb-2 pt-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  Connected Brokerages
                </CardTitle>

                {/* Connect Brokerage button — opens the consent modal */}
                {activePortfolioId && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 gap-1.5 px-2.5 text-xs"
                    onClick={() => setConnectModalOpen(true)}
                  >
                    <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
                    Connect Brokerage
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {/*
               * WHY render ConnectedBrokeragesList unconditionally (not inside activePortfolioId guard):
               * The tab content renders after portfolios load (loading state above handles the
               * null case). activePortfolioId will be set by the time this tab is visible.
               * If somehow it's null, ConnectedBrokeragesList defaults to empty state gracefully
               * because its query is disabled when portfolioId is empty.
               */}
              <ConnectedBrokeragesList portfolioId={activePortfolioId ?? ""} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ── Connect Brokerage Modal ──────────────────────────────────────── */}
      {/*
       * WHY render outside Tabs: the modal should be accessible regardless of
       * which tab is active (in case we add a trigger elsewhere in the future).
       * Rendering outside the tab content also avoids the modal unmounting when
       * the user switches tabs mid-connection-attempt.
       *
       * WHY conditional render on activePortfolioId: the modal requires a portfolio
       * to associate the new connection with. Without an ID the POST would fail.
       */}
      {activePortfolioId && (
        <ConnectBrokerageModal
          portfolioId={activePortfolioId}
          portfolioName={activePortfolio?.name}
          open={connectModalOpen}
          onOpenChange={setConnectModalOpen}
        />
      )}
    </div>
  );
}
