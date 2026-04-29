/**
 * app/(app)/portfolio/page.tsx — Full Portfolio Page (Terminal Redesign, Wave 4)
 *
 * WHY THIS EXISTS: The dashboard PortfolioSummary widget shows only a 4-tile
 * summary. This page is the trader's full position-management view:
 *
 *   Holdings    — 10-column semantic table with live P&L + sector allocation
 *   Transactions — filter by BUY/SELL/DIVIDEND, newest-first
 *   Watchlist   — per-watchlist tabs with live prices (30s refresh)
 *   Brokerages  — SnapTrade connection status, sync actions, error drill-down
 *
 * WHY FOUR TABS (not panels): keeping 4 data surfaces in one view without tabs
 * would require a vertical scroll marathon through 500+ px of content.
 * Tabs map to 4 distinct trader workflows; switching is O(1) clicks.
 *
 * DATA LOADING PATTERN (waterfall chain):
 *   1. getPortfolios() → pick active portfolio
 *   2. getHoldings(portfolioId) → position list + server-side P&L snapshot
 *   3. getBatchQuotes(instrumentIds) → live prices, refetchInterval 15s
 *   4. getTransactions(portfolioId) → history (lazy — loads when tab is visible)
 *   5. getWatchlists() → watchlist list + members
 *   6. getBatchQuotes(watchlistInstrumentIds) → watchlist live prices, 30s
 *   7. getBrokerageConnections(portfolioId) → SnapTrade connection status
 *
 * WHY memoize derived values: filter()/map() on holdings + quotes runs on every
 * render. useMemo() makes these O(1) after initial compute when props are stable.
 *
 * WHO USES IT: Authenticated users navigating to /portfolio
 * DATA SOURCE: S9 portfolio + watchlist + brokerage routes
 * DESIGN REFERENCE: PRD-0031 §8 Portfolio, Wave 4
 */

"use client";
// WHY "use client": TanStack Query, useState (portfolio selector, tab state,
// dialog open/close), next/navigation router (row-click navigation).

import { useState, useMemo, useCallback } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { ChevronDown, Plus, ChevronRight, Trash2 } from "lucide-react";

import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// PLAN-0051 T-A-1-05 — realized P&L now sourced from a dedicated server
// endpoint rather than the legacy client-side approximation. The hook
// encapsulates query key + staleTime so we don't have to repeat the
// invariants here.
import {
  useRealizedPnL,
  defaultRealizedPnLRange,
} from "@/hooks/useRealizedPnL";
import { formatPrice, cn } from "@/lib/utils";
import type { Portfolio } from "@/types/api";

// ── Portfolio components ──────────────────────────────────────────────────────
import { PortfolioKPIStrip } from "@/components/portfolio/PortfolioKPIStrip";
import { SemanticHoldingsTable } from "@/components/portfolio/SemanticHoldingsTable";
import { SectorAllocationPanel } from "@/components/portfolio/SectorAllocationPanel";
import { TransactionsTable } from "@/components/portfolio/TransactionsTable";
import { WatchlistsTabPanel } from "@/components/portfolio/WatchlistsTabPanel";
// PLAN-0046 Wave 5 / T-46-5-07 — analytics section (equity curve + exposure +
// risk metrics) rendered below the holdings table inside the Holdings tab.
import { PortfolioAnalyticsSection } from "@/components/portfolio/PortfolioAnalyticsSection";

// ── Brokerage components ──────────────────────────────────────────────────────
// WHY import the existing ConnectBrokerageModal + ConnectedBrokeragesList:
// These components own their own state management (modal open/close, sync actions).
// The new BrokerageConnectionCard is used internally by ConnectedBrokeragesList;
// the page doesn't need to wire it up manually.
import { ConnectBrokerageModal } from "@/components/brokerage/ConnectBrokerageModal";
import { ConnectedBrokeragesList } from "@/components/brokerage/ConnectedBrokeragesList";

// ── shadcn/ui ─────────────────────────────────────────────────────────────────
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

// ── Terminal primitives ───────────────────────────────────────────────────────
import { InlineEmptyState } from "@/components/data/InlineEmptyState";

// ── Create Portfolio Dialog ───────────────────────────────────────────────────

/**
 * CreatePortfolioDialog — modal for creating a new manually-managed portfolio.
 *
 * WHY a separate component (not inline JSX in the page): isolating dialog state
 * (name input, loading, error) keeps the parent page component clean. The dialog
 * has its own mini state machine: idle → submitting → success/error.
 *
 * DATA FLOW:
 *   1. User types a portfolio name
 *   2. On submit → calls gateway.createPortfolio(name)
 *   3. On success → calls onSuccess(newPortfolio) so the page can select it
 *   4. Parent invalidates ["portfolios"] query → TanStack Query refetches the list
 *
 * WHY onOpenChange instead of onClose: shadcn Dialog uses onOpenChange(false) to
 * signal close — from both the X button and the overlay click. This pattern is
 * idiomatic for shadcn dialogs throughout this app.
 */
interface CreatePortfolioDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (portfolio: Portfolio) => void;
  accessToken: string | null | undefined;
}

function CreatePortfolioDialog({
  open,
  onOpenChange,
  onSuccess,
  accessToken,
}: CreatePortfolioDialogProps) {
  // Local form state — only lives while the dialog is mounted
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // handleSubmit — async handler that calls S9 POST /v1/portfolios
  const handleSubmit = useCallback(async () => {
    // WHY trim + guard: whitespace-only names would pass server validation but look
    // wrong in the UI. Catch it client-side for instant feedback (no network round-trip).
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Portfolio name is required.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      // createPortfolio sends POST /v1/portfolios to S9, which injects owner_user_id
      // from the JWT claim before forwarding to S1. We only send name + currency.
      const newPortfolio = await createGateway(accessToken).createPortfolio(
        trimmedName,
        currency,
      );

      // Reset form state before closing so the dialog is clean on next open
      setName("");
      setCurrency("USD");
      setError(null);

      // Notify parent: it will invalidate ["portfolios"] and select the new portfolio
      onSuccess(newPortfolio);
    } catch (err) {
      // WHY string cast: GatewayError.message is a string, but unknown errors may not be.
      // We extract the message or fall back to a generic string rather than crashing.
      const message = err instanceof Error ? err.message : "Failed to create portfolio.";
      setError(message);
    } finally {
      // Always clear loading state, even if the request failed
      setIsSubmitting(false);
    }
  }, [name, currency, accessToken, onSuccess]);

  // handleOpenChange — reset form when dialog is closed externally (X or overlay)
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        // Don't reset if a submission is in progress — user may have hit overlay by accident
        if (!isSubmitting) {
          setName("");
          setCurrency("USD");
          setError(null);
        }
      }
      onOpenChange(nextOpen);
    },
    [isSubmitting, onOpenChange],
  );

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        // WHY max-w-sm: a portfolio creation form only has 2 fields — it doesn't
        // need a wide modal. Narrow dialogs feel more intentional than wide ones.
        className="max-w-sm bg-card border-border"
      >
        <DialogHeader>
          <DialogTitle className="text-[13px] font-mono uppercase tracking-[0.08em]">
            New Portfolio
          </DialogTitle>
        </DialogHeader>

        {/* ── Form fields ───────────────────────────────────────────── */}
        <div className="space-y-4 py-2">
          {/* Portfolio name */}
          <div className="space-y-1.5">
            <Label
              htmlFor="portfolio-name"
              className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
            >
              Name
            </Label>
            <Input
              id="portfolio-name"
              placeholder="e.g. Main Portfolio"
              value={name}
              onChange={(e) => setName(e.target.value)}
              // WHY onKeyDown: allow pressing Enter to submit (standard form UX).
              // Avoid wrapping in a <form> element since we're inside a Dialog with
              // its own focus management — nested form elements cause accessibility issues.
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isSubmitting) void handleSubmit();
              }}
              disabled={isSubmitting}
              // WHY autoFocus: the modal just opened and the name field is the only
              // required input. Focus it immediately so the user can start typing.
              autoFocus
              className="h-8 text-[12px] font-mono bg-background border-border"
            />
          </div>

          {/* Currency — defaults to USD; most users won't change this */}
          <div className="space-y-1.5">
            <Label
              htmlFor="portfolio-currency"
              className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
            >
              Currency
            </Label>
            <Input
              id="portfolio-currency"
              placeholder="USD"
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              disabled={isSubmitting}
              maxLength={3}
              // WHY toUpperCase(): S1 validates that currency is a 3-letter uppercase
              // code. Convert on change so the user can type lowercase without errors.
              className="h-8 text-[12px] font-mono bg-background border-border w-24"
            />
          </div>

          {/* Inline error — only shown when submission fails */}
          {error && (
            <p className="text-[11px] text-destructive font-mono">{error}</p>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleOpenChange(false)}
            disabled={isSubmitting}
            className="text-[11px] font-mono"
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || !name.trim()}
            // WHY font-mono: all action text in terminal UI uses monospace for consistency
            className="text-[11px] font-mono"
          >
            {isSubmitting ? "Creating…" : "Create Portfolio"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Add Position Dialog ───────────────────────────────────────────────────────

/**
 * AddPositionDialog — modal for manually adding a new position to a portfolio.
 *
 * WHY a BUY transaction (not a direct "add holding" call): S1 has no dedicated
 * endpoint for creating holdings. Holdings are derived from transaction history —
 * a BUY transaction increases (or creates) a holding. This mirrors how a real
 * broker records a purchase. See gateway.addPosition() for the S1 mapping.
 *
 * TICKER RESOLUTION FLOW:
 *   1. User types a ticker (e.g. "AAPL")
 *   2. On submit → searchInstruments("AAPL") → gets instrument_id
 *   3. addPosition(portfolioId, instrument_id, qty, price) → POST /v1/transactions
 *   4. On success → invalidate ["holdings", portfolioId] so the table refreshes
 *
 * WHY resolve ticker server-side (not via user-supplied instrument_id):
 * Instrument IDs are internal UUIDs — they're not meaningful to a user.
 * Letting users type tickers and resolving them to instrument_ids at submit time
 * is the standard UX for all finance terminals (Bloomberg, Schwab, etc.).
 *
 * WHY no autocomplete on the ticker field: adding a dependency on a live search
 * query inside a modal is complex. The simpler approach is to resolve on submit and
 * show an error if the ticker doesn't exist (same flow as Bloomberg CMD line entry).
 * Autocomplete can be added later as a UX enhancement.
 */
interface AddPositionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  portfolioId: string;
  accessToken: string | null | undefined;
}

function AddPositionDialog({
  open,
  onOpenChange,
  onSuccess,
  portfolioId,
  accessToken,
}: AddPositionDialogProps) {
  // Form field state
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [avgPrice, setAvgPrice] = useState("");

  // Submission state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = useCallback(async () => {
    // ── Validate inputs before hitting the network ──────────────────────
    const trimmedTicker = ticker.trim().toUpperCase();
    const parsedQty = parseFloat(quantity);
    const parsedPrice = parseFloat(avgPrice);

    if (!trimmedTicker) {
      setError("Ticker symbol is required.");
      return;
    }
    if (isNaN(parsedQty) || parsedQty <= 0) {
      setError("Quantity must be a positive number.");
      return;
    }
    // WHY avgPrice optional: some traders enter positions at cost=0 (e.g., gifted shares,
    // or when exact cost basis is unknown). We allow empty/zero but not negative.
    const costBasis = isNaN(parsedPrice) ? 0 : parsedPrice;
    if (costBasis < 0) {
      setError("Average price cannot be negative.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    const gw = createGateway(accessToken);

    try {
      // ── Step 1: resolve ticker → instrument_id ─────────────────────────
      // WHY search with limit=1: we only need the best match (exact ticker match
      // is ranked first by S3's instrument search).
      const searchResult = await gw.searchInstruments(trimmedTicker, 1);
      const instrument = searchResult.results[0];

      if (!instrument) {
        // WHY user-facing error (not throw): the user may have mistyped the ticker.
        // Show an inline error with guidance rather than crashing the dialog.
        setError(`Ticker "${trimmedTicker}" not found. Check the symbol and try again.`);
        setIsSubmitting(false);
        return;
      }

      // ── Step 2: add the position via a BUY transaction ─────────────────
      // gateway.addPosition() maps to POST /v1/transactions with direction=BUY.
      // The response is the created transaction (we don't need to use it here
      // — we just care that the request succeeded so we can refetch holdings).
      await gw.addPosition(
        portfolioId,
        instrument.instrument_id,
        parsedQty,
        costBasis,
      );

      // Reset form on success
      setTicker("");
      setQuantity("");
      setAvgPrice("");
      setError(null);

      // Notify parent to invalidate ["holdings", portfolioId] so the table updates
      onSuccess();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to add position.";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  }, [ticker, quantity, avgPrice, portfolioId, accessToken, onSuccess]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen && !isSubmitting) {
        // Clear form on close so the dialog is fresh on next open
        setTicker("");
        setQuantity("");
        setAvgPrice("");
        setError(null);
      }
      onOpenChange(nextOpen);
    },
    [isSubmitting, onOpenChange],
  );

  // WHY disable submit when ticker is empty: quantity and price have sensible
  // defaults (empty = 0), but a ticker-less submission would always fail at
  // the search step. Disable early to prevent a wasted network round-trip.
  const canSubmit = ticker.trim().length > 0 && !isSubmitting;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-sm bg-card border-border">
        <DialogHeader>
          <DialogTitle className="text-[13px] font-mono uppercase tracking-[0.08em]">
            Add Position
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Ticker symbol — the primary identifier traders use */}
          <div className="space-y-1.5">
            <Label
              htmlFor="position-ticker"
              className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
            >
              Ticker
            </Label>
            <Input
              id="position-ticker"
              placeholder="e.g. AAPL"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter" && canSubmit) void handleSubmit();
              }}
              disabled={isSubmitting}
              autoFocus
              // WHY toUpperCase(): tickers are always uppercase in financial systems.
              // Converting as-you-type prevents "aapl" from failing the S3 search lookup.
              className="h-8 text-[12px] font-mono bg-background border-border"
            />
          </div>

          {/* Quantity — number of shares */}
          <div className="space-y-1.5">
            <Label
              htmlFor="position-quantity"
              className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
            >
              Quantity
            </Label>
            <Input
              id="position-quantity"
              type="number"
              placeholder="e.g. 10"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              disabled={isSubmitting}
              min="0.00000001"
              step="any"
              // WHY step="any": S1 stores quantity as Decimal(18,8). Users may have
              // fractional shares (e.g., crypto or fractional equity programs like Robinhood).
              className="h-8 text-[12px] font-mono tabular-nums bg-background border-border"
            />
          </div>

          {/* Average price — cost basis per share */}
          <div className="space-y-1.5">
            <Label
              htmlFor="position-avg-price"
              className="text-[11px] uppercase tracking-[0.06em] text-muted-foreground"
            >
              Avg Price <span className="text-muted-foreground/60">(optional)</span>
            </Label>
            <Input
              id="position-avg-price"
              type="number"
              placeholder="e.g. 185.42"
              value={avgPrice}
              onChange={(e) => setAvgPrice(e.target.value)}
              disabled={isSubmitting}
              min="0"
              step="any"
              // WHY optional: some users add positions without knowing exact cost basis
              // (gifted shares, inherited positions). Defaults to 0.
              className="h-8 text-[12px] font-mono tabular-nums bg-background border-border"
            />
          </div>

          {/* Inline error message */}
          {error && (
            <p className="text-[11px] text-destructive font-mono">{error}</p>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleOpenChange(false)}
            disabled={isSubmitting}
            className="text-[11px] font-mono"
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
            className="text-[11px] font-mono"
          >
            {isSubmitting ? "Adding…" : "Add Position"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * formatStalenessAwarePrice — prefix "~" when a quote is stale/delayed.
 *
 * WHY module-internal (not exported): only the portfolio page uses this helper.
 * Tests in portfolio-stale.test.tsx mirror this function locally for isolated
 * unit testing; integration tests verify the "~" appears in rendered output.
 *
 * WHY "~" before "$": "~$185.42" reads as "approximately $185.42" — a universal
 * approximation signal that doesn't require a tooltip to understand.
 */
function formatStalenessAwarePrice(price: number, freshness?: string): string {
  const isStale = freshness != null && freshness !== "live";
  return isStale ? `~${formatPrice(price)}` : formatPrice(price);
}
// WHY unused-variable suppress: formatStalenessAwarePrice is passed to
// SemanticHoldingsTable via the quotes object (freshness field), not called here
// directly. It's preserved for the stale indicator test mirror.
void formatStalenessAwarePrice;

// ── PortfolioPage ─────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const { accessToken } = useAuth();

  // WHY useQueryClient: after creating a portfolio or adding a position we need to
  // invalidate the relevant TanStack Query cache keys so the UI reflects the change
  // without a full page reload. queryClient.invalidateQueries() triggers a background
  // refetch of any active queries matching the key.
  const queryClient = useQueryClient();

  // WHY selectedPortfolioId in state (not URL): switching portfolios is ephemeral.
  // The URL always shows /portfolio regardless of which portfolio is active.
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string | null>(null);

  // T-B-2-07: 1S/1W/1M chips removed from the Holdings page header per user
  // request — the EquityCurveChart's internal toggle is the canonical way to
  // change period. The KPI strip is now hard-locked to the "1D" performance
  // window. The state variable is retained (not deleted) so the existing
  // performance query keys + downstream consumers stay unchanged.
  // WHY selectedPeriod still in state: the 1D performance API call still uses
  // performance strip. Default 1D matches Bloomberg convention ("today's return first").
  // T-B-2-07: hardcoded constant — KPI strip is permanently 1D since the
  // header period chips were removed. Use `as const` so the value type stays
  // narrow and downstream callers (query keys etc.) compile unchanged.
  const selectedPeriod = "1D" as const;

  // WHY connectModalOpen state here: the modal trigger lives in the Transactions tab
  // brokerage section but the modal must persist through tab switches.
  const [connectModalOpen, setConnectModalOpen] = useState(false);

  // WHY brokeragesSectionExpanded default false: the primary use of the Transactions
  // tab is reviewing transaction history — the brokerage connection panel is secondary.
  // Collapsed by default keeps the transaction table immediately visible.
  const [brokeragesSectionExpanded, setBrokeragesSectionExpanded] = useState(false);

  // ── Create Portfolio dialog state ──────────────────────────────────────────
  // WHY at page level (not inside the header): the dialog must be rendered in the
  // same React tree as useQueryClient() so onSuccess() can call queryClient.invalidateQueries().
  // If the dialog were a self-contained component with its own query client instance,
  // it would invalidate a different cache and the list wouldn't update.
  const [createPortfolioOpen, setCreatePortfolioOpen] = useState(false);

  // ── Add Position dialog state ───────────────────────────────────────────────
  // Same reasoning as createPortfolioOpen — lives here so it can invalidate
  // ["holdings", activePortfolioId] when a position is successfully added.
  const [addPositionOpen, setAddPositionOpen] = useState(false);

  // ── F-013: Delete portfolio dialog state ────────────────────────────────
  // WHY a separate dialog (not a window.confirm): the destructive action
  // benefits from a styled shadcn Dialog so the confirmation matches the
  // rest of the terminal UI. Tracks pending state for an in-flight delete.
  const [deletePortfolioOpen, setDeletePortfolioOpen] = useState(false);

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

  // ── PLAN-0046 Wave 3 / T-46-3-04 — sort with ROOT first ─────────────────
  // WHY a sorted copy (not a re-fetch): the gateway returns portfolios in
  // creation order. The product spec wants the aggregate "All Accounts" view
  // (kind === "root") to appear first in the selector and to be the initial
  // active portfolio on first load. Sorting client-side keeps the API stable
  // — if we ever drop the ROOT-first rule, only this memo changes.
  //
  // Tie-break: name A→Z. This is purely cosmetic — within manual/brokerage
  // the user has typically only a handful of portfolios, so any deterministic
  // order is fine; alphabetical is the most intuitive.
  const sortedPortfolios = useMemo(() => {
    if (!portfolios) return undefined;
    // Slice to avoid mutating the TanStack Query cached array (would trigger
    // re-renders downstream and confuse staleness detection).
    return portfolios.slice().sort((a, b) => {
      // ROOT always first — sorts before everything else regardless of name.
      const aRoot = a.kind === "root" ? 0 : 1;
      const bRoot = b.kind === "root" ? 0 : 1;
      if (aRoot !== bRoot) return aRoot - bRoot;
      return a.name.localeCompare(b.name);
    });
  }, [portfolios]);

  // WHY derived active portfolio (not stored in state):
  // The default is sortedPortfolios[0] (= ROOT once it lands in S1's response);
  // selecting a portfolio updates selectedPortfolioId. Storing both would
  // cause a double-render on initial load.
  //
  // PLAN-0046 Wave 3 / T-46-3-04 — default-select the ROOT portfolio: because
  // sortedPortfolios puts kind === "root" first, sortedPortfolios?.[0] is the
  // root if present, otherwise falls back to whichever portfolio happens to
  // be first (legacy behaviour for environments where migration 0011 hasn't
  // shipped yet).
  const activePortfolioId =
    selectedPortfolioId ?? sortedPortfolios?.[0]?.portfolio_id ?? null;
  const activePortfolio = sortedPortfolios?.find(
    (p) => p.portfolio_id === activePortfolioId,
  );

  // PLAN-0046 Wave 3 / T-46-3-04 — derived flag used in multiple places.
  // Centralised so future kind-aware UX (e.g. disabling Add Position on root)
  // doesn't have to duplicate the comparison.
  const activeIsRoot = activePortfolio?.kind === "root";

  // ── Mutation callbacks ────────────────────────────────────────────────────
  // WHY placed AFTER activePortfolioId derivation: handlePositionAdded captures
  // activePortfolioId in its closure. React's exhaustive-deps lint rule requires
  // that all variables used inside a useCallback are listed in the deps array.
  // If activePortfolioId were declared later, TypeScript would throw TS2448
  // ("block-scoped variable used before its declaration").

  /**
   * handlePortfolioCreated — runs after CreatePortfolioDialog succeeds.
   *
   * WHY invalidate + setSelected: invalidateQueries causes TanStack Query to
   * refetch the ["portfolios"] list in the background. When the new list arrives,
   * the activePortfolioId derivation would still pick portfolios[0] unless we
   * explicitly select the new portfolio. Setting selectedPortfolioId immediately
   * makes the UI switch to the new portfolio as soon as the list refetch completes.
   *
   * WHY close the dialog here (not inside the dialog): the dialog's onSuccess prop
   * is responsible for signalling completion — closing is the page's responsibility.
   * This keeps the dialog decoupled from page-level state.
   */
  const handlePortfolioCreated = useCallback(
    (newPortfolio: Portfolio) => {
      // Close the create dialog first to give instant feedback that something happened
      setCreatePortfolioOpen(false);

      // Invalidate the portfolio list so TanStack Query refetches from S9.
      // WHY void: invalidateQueries returns a Promise but we don't need to await it —
      // it kicks off a background refetch and the UI updates reactively.
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });

      // Pre-select the new portfolio so the user immediately sees it active,
      // even before the refetch returns the updated list.
      setSelectedPortfolioId(newPortfolio.portfolio_id);
    },
    [queryClient],
  );

  /**
   * handlePositionAdded — runs after AddPositionDialog succeeds.
   *
   * WHY invalidate both holdings and quotes: the new position creates a holding.
   * We invalidate ["holdings", activePortfolioId] to refetch the position list and
   * ["holdings-quotes", ...] will naturally re-run because holdingInstrumentIds will
   * change when the holdings query returns the new entry.
   *
   * WHY also invalidate transactions: the "Add Position" flow creates a BUY transaction.
   * Without invalidating the transactions cache, the Transactions tab would still show
   * the old list until stale time expires (30s).
   */
  const handlePositionAdded = useCallback(() => {
    setAddPositionOpen(false);

    // Refetch holdings for the active portfolio (shows the new position row)
    void queryClient.invalidateQueries({ queryKey: ["holdings", activePortfolioId] });

    // Refetch transactions (the BUY transaction we just created should appear)
    void queryClient.invalidateQueries({ queryKey: ["transactions", activePortfolioId] });
  }, [queryClient, activePortfolioId]);

  // ── F-013: Delete portfolio mutation ────────────────────────────────────
  // WHY here (not inside the Delete dialog component): the mutation needs
  // to invalidate the ["portfolios"] cache and potentially clear the
  // selected portfolio id, both of which live in this parent component.
  const deletePortfolioMutation = useMutation({
    mutationFn: (portfolioId: string) =>
      createGateway(accessToken).deletePortfolio(portfolioId),
    onSuccess: (_, deletedId) => {
      // Refresh the portfolios list so the deleted entry disappears.
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      // If we just deleted the active one, fall back to the first remaining
      // portfolio (typically the root). Setting to null lets the next render
      // re-derive from sortedPortfolios?.[0].
      if (activePortfolioId === deletedId) {
        setSelectedPortfolioId(null);
      }
      setDeletePortfolioOpen(false);
    },
  });

  // ── Query 2: holdings ────────────────────────────────────────────────────
  const {
    data: holdingsResp,
    isLoading: holdingsLoading,
  } = useQuery({
    queryKey: ["holdings", activePortfolioId],
    queryFn: () => createGateway(accessToken).getHoldings(activePortfolioId!),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 30_000,
  });

  // ── Query 3: live quotes for holdings (15s refresh) ──────────────────────
  const holdingInstrumentIds = useMemo(
    () => holdingsResp?.holdings.map((h) => h.instrument_id) ?? [],
    [holdingsResp],
  );
  const { data: holdingsQuotesData } = useQuery({
    queryKey: ["holdings-quotes", holdingInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(holdingInstrumentIds),
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
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

  // ── Query 6: live quotes for all watchlist members (30s refresh) ─────────
  const watchlistInstrumentIds = useMemo(
    () =>
      (watchlists ?? [])
        .flatMap((wl) => wl.members.map((m) => m.instrument_id))
        .filter((id): id is string => id !== null),
    [watchlists],
  );
  const { data: watchlistQuotesData } = useQuery({
    queryKey: ["watchlist-quotes", watchlistInstrumentIds],
    queryFn: () =>
      createGateway(accessToken).getBatchQuotes(watchlistInstrumentIds),
    enabled: watchlistInstrumentIds.length > 0 && !!accessToken,
    refetchInterval: 30_000,
    staleTime: 0,
  });

  // ── Query 7b: realized P&L (PLAN-0051 T-A-1-05) ───────────────────────────
  // WHY a separate hook (not inline useQuery): the FIFO endpoint will be
  // consumed by a future drill-down panel as well. Keeping the staleTime /
  // queryKey conventions in one place avoids drift between consumers.
  //
  // WHY default range = current calendar year: matches the way 1099-B
  // statements are organised; users can override later via a date picker.
  const realizedRange = useMemo(() => defaultRealizedPnLRange(), []);
  const realizedPnLQuery = useRealizedPnL(
    activePortfolioId,
    realizedRange.from,
    realizedRange.to,
  );

  // ── Query 7: portfolio period performance ─────────────────────────────────
  // WHY independent from holdings queries: performance depends on OHLCV data from S3,
  // not live quotes. Re-runs only when the portfolio or period changes — not on the
  // 15s quote poll cycle that drives the live holdings table.
  const { data: performanceData, isLoading: performanceLoading } = useQuery({
    queryKey: ["portfolio-performance", activePortfolioId, selectedPeriod],
    queryFn: () =>
      createGateway(accessToken).getPortfolioPerformance(
        activePortfolioId!,
        selectedPeriod,
      ),
    enabled: !!accessToken && !!activePortfolioId,
    staleTime: 60_000,
  });

  // ── Stable derived values (memoised to avoid reference churn) ────────────
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

  // ── Query 7.5: company overviews for holdings (sector + ticker enrichment) ──
  // WHY a separate query (not bundled with holdings): the holdings query comes
  // from S9's portfolio routes; company overview comes from the intelligence service.
  // Different cache keys, different stale windows — holdings refresh every 30s;
  // ticker/sector data almost never changes.
  //
  // WHY Promise.all: fetch all in parallel to minimize wall-clock time.
  //
  // WHY staleTime 300s: gics_sector rebalances annually; ticker/name are permanent.
  // 5-minute cache avoids redundant requests on tab switches.
  //
  // WHY return {ticker, name, entity_id, sector}: the gateway returns empty ticker/name
  // for holdings (S1 doesn't store them). Company overview enriches all four fields.
  // SemanticHoldingsTable reads h.ticker and h.name — they must be non-empty.
  const { data: holdingOverviews } = useQuery({
    queryKey: ["holdings-overviews", holdingInstrumentIds],
    queryFn: async () => {
      const results = await Promise.all(
        holdingInstrumentIds.map((id) =>
          createGateway(accessToken).getCompanyOverview(id).catch(() => null),
        ),
      );
      return Object.fromEntries(
        holdingInstrumentIds.map((id, i) => [
          id,
          {
            sector:    results[i]?.instrument?.gics_sector ?? null,
            ticker:    results[i]?.instrument?.ticker ?? null,
            name:      results[i]?.instrument?.name ?? null,
            entity_id: results[i]?.instrument?.entity_id ?? null,
          },
        ]),
      ) as Record<string, { sector: string | null; ticker: string | null; name: string | null; entity_id: string | null }>;
    },
    enabled: holdingInstrumentIds.length > 0 && !!accessToken,
    staleTime: 300_000,
  });

  // ── Enriched holdings: merge ticker/name/entity_id from company overviews ──
  // WHY this memo: getHoldings() returns holdings with empty ticker/name (S1 doesn't
  // store these). The company overview query above fetches them asynchronously.
  // This memo creates a merged list that SemanticHoldingsTable can render correctly.
  // Before holdingOverviews resolves, we fall back to instrument_id as a placeholder.
  const enrichedHoldings = useMemo(
    () =>
      holdings.map((h) => {
        const ov = holdingOverviews?.[h.instrument_id];
        return {
          ...h,
          // WHY parentheses: TypeScript disallows mixing ?? and || without explicit
          // grouping (TS5076). The intent is: use enrichment value if non-null,
          // else fall back to the existing field, else fall back to derived placeholder.
          ticker:    (ov?.ticker    ?? h.ticker)    || h.instrument_id.slice(0, 8).toUpperCase(),
          name:      (ov?.name      ?? h.name)      || `Instrument ${h.instrument_id.slice(-6)}`,
          entity_id: (ov?.entity_id ?? h.entity_id) || h.instrument_id,
        };
      }),
    [holdings, holdingOverviews],
  );

  // ── KPI computations ─────────────────────────────────────────────────────
  const kpi = useMemo(() => {
    let totalValue = 0;
    let totalCost = 0;
    let dayPnl: number | null = null;
    let topGainer: { ticker: string; pnlPct: number } | null = null;
    let topLoser: { ticker: string; pnlPct: number } | null = null;

    // WHY use enrichedHoldings (not raw holdings): enrichedHoldings has ticker/name
    // populated from company overviews. topGainer/topLoser display ticker in the KPI strip.
    for (const h of enrichedHoldings) {
      const q = holdingsQuotes[h.instrument_id];
      // WHY q.price>0 (B-2): a delisted instrument (e.g., a fully-sold position
      // like VTV) returns price:0 from the batch endpoint. The previous nullish
      // chain treated 0 as a real value and computed pnlPct = -100% — incorrectly
      // flagging the position as the day's biggest loser.
      const livePrice =
        q?.price && q.price > 0
          ? q.price
          : h.current_price ?? h.average_cost;
      totalValue += livePrice * h.quantity;
      totalCost += h.average_cost * h.quantity;

      // WHY null-guard on today's P&L: if no quotes have resolved yet (batch
      // query pending), we can't compute day P&L — show "—" rather than $0.
      if (q?.change != null) {
        dayPnl = (dayPnl ?? 0) + q.change * h.quantity;
      }

      // Compute unrealised P&L% for top gainer / loser detection
      const pnlPct =
        h.average_cost > 0
          ? ((livePrice - h.average_cost) / h.average_cost) * 100
          : 0;

      // Top gainer = highest positive pnlPct; only assign when > 0.
      // F-202 fix (PLAN-0048 QA iter-1): symmetric guard for top loser —
      // when every position is profitable, the previous Math.min logic
      // selected the smallest gainer (e.g. MSFT +1.70%) and labelled it
      // "Top Loser", which mis-signalled to the trader that MSFT was DOWN
      // 1.70%. A loser must have negative pnlPct, otherwise the tile
      // should display "—" (handled in PortfolioKPIStrip when topLoser=null).
      if (pnlPct > 0 && (topGainer == null || pnlPct > topGainer.pnlPct)) {
        topGainer = { ticker: h.ticker, pnlPct };
      }
      if (pnlPct < 0 && (topLoser == null || pnlPct < topLoser.pnlPct)) {
        topLoser = { ticker: h.ticker, pnlPct };
      }
    }

    const unrealisedPnl = totalValue - totalCost;
    const unrealisedPnlPct = totalCost > 0 ? unrealisedPnl / totalCost : 0;

    // ── Realized P&L from SELL transactions ─────────────────────────────
    // WHY use holdings average_cost (not a separate cost-basis ledger): S1 stores
    // average_cost per holding as a running FIFO average. For closed positions the
    // holding row is removed from holdings; we can only compute realized P&L for
    // instruments that STILL have an open position (i.e., partial sells). Fully
    // closed positions are not captured here — this is an approximation that's
    // still the most useful single number traders can act on.
    //
    // WHY skip if avgCost == null: instrument_id on the transaction may not match
    // any current holding (position fully closed). Skip those — we can't infer cost
    // basis without the holding row.
    const costByInstrument = Object.fromEntries(
      enrichedHoldings.map((h) => [h.instrument_id, h.average_cost]),
    );
    let realizedPnl = 0;
    for (const tx of transactionsResp?.transactions ?? []) {
      if (tx.type !== "SELL") continue;
      const avgCost = costByInstrument[tx.instrument_id];
      if (avgCost == null) continue; // can't compute for closed/unknown positions
      realizedPnl += (tx.price - avgCost) * tx.quantity;
    }
    // WHY null when no transactions loaded vs 0: if transactionsResp is undefined
    // (query still pending) we'd emit $0, misleading traders into thinking there's
    // no realized P&L. Emit null instead so the tile renders "—".
    const realizedPnlOrNull = transactionsResp != null ? realizedPnl : null;

    return {
      totalValue,
      dayPnl,
      unrealisedPnl,
      unrealisedPnlPct,
      topGainer,
      topLoser,
      positionCount: enrichedHoldings.length,
      realizedPnl: realizedPnlOrNull,
    };
  }, [enrichedHoldings, holdingsQuotes, transactionsResp]);

  // ── Sector / type allocation (derived from holdings + company overviews) ──
  // WHY separate useMemo (not inlined with kpi): holdingOverviews resolves later
  // than holdingsQuotes (it's an extra network round-trip per holding). Keeping it
  // in a separate memo means the KPI strip updates immediately when quotes arrive,
  // while the SectorAllocationPanel fills in asynchronously without blocking the KPI.
  const { bySector, byType } = useMemo(() => {
    if (!enrichedHoldings.length || !holdingOverviews) return { bySector: [], byType: [] };

    // Build market value per instrument using the same live-price logic as KPI
    const valueByInstrument: Record<string, number> = {};
    const totalVal = enrichedHoldings.reduce((sum, h) => {
      const q = holdingsQuotes[h.instrument_id];
      // WHY three-way fallback: live quote → server-enriched current_price → cost basis
      // This mirrors the KPI memo's price logic so sector weights are consistent with
      // the total value shown in the KPI strip.
      const price =
        q?.price && q.price > 0 ? q.price : h.current_price ?? h.average_cost;
      const val = price * h.quantity;
      valueByInstrument[h.instrument_id] = val;
      return sum + val;
    }, 0);

    // WHY guard on totalVal === 0: division by zero produces NaN pct values which
    // would render as "NaN%" in the UI. Return empty arrays instead.
    if (totalVal === 0) return { bySector: [], byType: [] };

    // Group holdings by GICS sector, summing their market values
    const sectorMap: Record<string, number> = {};
    for (const h of enrichedHoldings) {
      // WHY "Unknown" fallback: holdingOverviews[id] is null when the overview
      // request failed or the instrument has no sector classification. "Unknown"
      // is more honest than silently dropping the position from the chart.
      const sector = holdingOverviews[h.instrument_id]?.sector ?? "Unknown";
      sectorMap[sector] = (sectorMap[sector] ?? 0) + (valueByInstrument[h.instrument_id] ?? 0);
    }

    const bySector = Object.entries(sectorMap)
      .map(([label, value]) => ({ label, value, pct: (value / totalVal) * 100 }))
      .sort((a, b) => b.pct - a.pct); // largest sector first

    // WHY a single "Equity" byType bar: the portfolio currently only supports equity
    // holdings (stocks/ETFs). If fixed-income or crypto support is added later,
    // update this to use an instrument type field from the overview.
    const byType = [{ label: "Equity", value: totalVal, pct: 100 }];

    return { bySector, byType };
  }, [enrichedHoldings, holdingOverviews, holdingsQuotes]); // enrichedHoldings already merges holding+overview

  // ── F-021: scope hint for the active portfolio ─────────────────────────
  // WHY a separate memo: the hint depends on (a) whether the active
  // portfolio is the root aggregate, (b) the count of non-root active
  // portfolios, and (c) the count of unique positions in the enriched
  // holdings list. Computing inline in JSX would re-evaluate on every
  // render — useMemo keeps it stable across unrelated re-renders.
  // WHY before the early returns: rules-of-hooks requires every hook
  // to run on every render. Hoisting this above the conditional render
  // branches keeps the hook order stable.
  const scopeHint = useMemo<string | null>(() => {
    if (!activePortfolio) return null;
    if (activeIsRoot) {
      const subCount =
        sortedPortfolios?.filter((p) => p.kind !== "root").length ?? 0;
      // Use enrichedHoldings.length — already de-duplicated by instrument
      // when fanning out across sub-portfolios in the root branch.
      const positionCount = enrichedHoldings.length;
      return `Viewing All Accounts — ${subCount} portfolio${subCount === 1 ? "" : "s"}, ${positionCount} unique position${positionCount === 1 ? "" : "s"}`;
    }
    if (activePortfolio.kind === "brokerage") {
      // We don't surface the brokerage name here (that lives on the
      // Brokerages tab); the kind label is enough for at-a-glance scope.
      return "Brokerage portfolio";
    }
    // For "manual" we render no sub-line — the portfolio name in the
    // selector is the only context the user needs.
    return null;
  }, [activePortfolio, activeIsRoot, sortedPortfolios, enrichedHoldings.length]);

  // ── Loading state ────────────────────────────────────────────────────────
  if (portfoliosLoading || (holdingsLoading && !holdingsResp)) {
    return (
      // WHY p-3 space-y-3: terminal density — 12px padding, 12px gaps
      <div className="flex flex-col h-full min-h-0 space-y-3 p-3">
        {/* Header skeleton */}
        <div className="flex h-9 items-center justify-between">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-7 w-36" />
        </div>
        {/* KPI strip skeleton (6 tiles) */}
        <div className="flex gap-0 border-b border-border">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex-1 px-3 py-1.5">
              <Skeleton className="h-3 w-16 mb-1" />
              <Skeleton className="h-4 w-20" />
            </div>
          ))}
        </div>
        {/* Tab skeleton */}
        <Skeleton className="h-9 w-80" />
        {/* Table rows skeleton */}
        <div className="space-y-px">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[22px] w-full" />
          ))}
        </div>
      </div>
    );
  }

  // ── Error state ──────────────────────────────────────────────────────────
  if (portfoliosError) {
    return (
      <div className="p-3">
        <InlineEmptyState message="Failed to load portfolio data. Check your connection and reload." />
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    // WHY h-full flex-col: fills the shell's main content area.
    // min-h-0 prevents flexbox from overflowing its parent.
    //
    // WHY bg-background (NOT bg-card): the page is the lowest level of the
    // elevation hierarchy. Panels inside the page (analytics cards, dialogs,
    // sticky table headers) use bg-card (#111113). If the page itself is
    // bg-card, every nested bg-card panel disappears into a single near-black
    // mass — visually the equity curve + exposure cells (each min-h-[220px]
    // bg-card) end up reading as one gigantic black overlay covering all the
    // widgets in the Holdings tab. Page = bg-background (#09090B) is one shade
    // darker than panels so the 1px borders + tonal step give each card its
    // own silhouette. Matches the dashboard, instrument-detail, and screener
    // pages, which all sit on bg-background.
    <div className="flex flex-col h-full min-h-0 bg-background">

      {/* ── Page header ─────────────────────────────────────────────────── */}
      {/* WHY h-9 shrink-0: 36px header is the terminal standard. shrink-0 prevents
          flexbox from compressing the header to make room for tab content.
          WHY bg-card: the page is now bg-background (#09090B); the header
          needs the panel tone (#111113) to read as the chrome row at the
          top of the workspace, separating it from the empty-page tone below
          while data loads. */}
      <div className="flex h-9 shrink-0 items-center border-b border-border px-3 gap-3 bg-card">
        <h1 className="text-[11px] uppercase tracking-[0.08em] text-muted-foreground font-sans">
          Portfolio
        </h1>

        {/* Portfolio selector — only shown when user has multiple portfolios.
            WHY hidden for single portfolio: a dropdown with one item is just clutter.
            The active portfolio name is shown in the "0 positions" badge instead. */}
        {sortedPortfolios && sortedPortfolios.length > 1 && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-1.5 text-[11px] font-mono text-foreground"
              >
                {/* PLAN-0046 Wave 3 / T-46-3-04 — show "ALL" badge inline next
                    to the trigger label when the active portfolio is the root.
                    This makes the aggregate view immediately recognisable
                    without opening the menu. */}
                {activePortfolio?.name ?? "Select portfolio"}
                {activeIsRoot && (
                  <span
                    className="ml-1 rounded-[2px] border border-primary/60 bg-primary/10 px-1 py-px text-[9px] font-mono uppercase tracking-[0.06em] text-primary"
                    aria-label="Aggregate portfolio"
                  >
                    ALL
                  </span>
                )}
                <ChevronDown className="h-3 w-3 opacity-60" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {sortedPortfolios.map((p: Portfolio) => (
                <DropdownMenuItem
                  key={p.portfolio_id}
                  onClick={() => setSelectedPortfolioId(p.portfolio_id)}
                  className={cn(
                    "font-mono text-xs flex items-center gap-1.5",
                    p.portfolio_id === activePortfolioId && "text-primary font-medium",
                  )}
                >
                  {p.name}
                  {/* Per-row ALL badge: keeps the root recognisable inside the
                      menu even when another portfolio is currently active. */}
                  {p.kind === "root" && (
                    <span
                      className="rounded-[2px] border border-primary/60 bg-primary/10 px-1 py-px text-[9px] font-mono uppercase tracking-[0.06em] text-primary"
                      aria-label="Aggregate portfolio — All Accounts"
                    >
                      ALL
                    </span>
                  )}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        {/* Position count — quick glance at book size */}
        {enrichedHoldings.length > 0 && (
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
            {enrichedHoldings.length} positions
          </span>
        )}

        {/* WHY ml-auto: push the action buttons to the right side of the header,
            matching the Bloomberg/terminal convention of left=labels, right=actions. */}
        <div className="ml-auto flex items-center gap-2">
          {/* "Add Position" button — only useful when there's an active portfolio.
              WHY disabled when no portfolio: without a portfolio there's nowhere to add
              the position. The button is hidden entirely (not just disabled) to avoid
              confusion — it only appears when there's something to add to.

              PLAN-0046 Wave 3 / T-46-3-04 — also disabled when the active portfolio
              is the ROOT aggregate. The S1 backend rejects POST /v1/transactions
              with HTTP 400 (CANNOT_RECORD_TRANSACTION_ON_ROOT) for root portfolios;
              graying the button out client-side prevents a wasted round-trip and
              gives the user instant feedback via the tooltip. */}
          {activePortfolioId && (
            <button
              aria-label={
                activeIsRoot
                  ? "Cannot add positions directly to the aggregate portfolio"
                  : "Add a new position to this portfolio"
              }
              title={
                activeIsRoot
                  ? "Switch to a specific portfolio to add a position. The aggregate view is read-only."
                  : undefined
              }
              onClick={() => {
                if (!activeIsRoot) setAddPositionOpen(true);
              }}
              disabled={activeIsRoot}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] flex items-center gap-1 transition-colors",
                activeIsRoot
                  ? "border-border/40 text-muted-foreground/40 cursor-not-allowed"
                  : "border-border text-muted-foreground hover:border-primary/60 hover:text-primary",
              )}
            >
              <Plus className="h-3 w-3" />
              Add Position
            </button>
          )}

          {/* "New Portfolio" button — always visible so users can create their first
              portfolio even when they have no portfolios yet (empty state). */}
          <button
            aria-label="Create a new portfolio"
            onClick={() => setCreatePortfolioOpen(true)}
            className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 transition-colors flex items-center gap-1"
          >
            <Plus className="h-3 w-3" />
            New Portfolio
          </button>

          {/* F-013 (QA 2026-04-28): Delete button.
              WHY only render with an active portfolio: nothing to delete
              otherwise. WHY disabled for ROOT: the S1 backend rejects
              archive on the aggregate (RootPortfolioNotArchivableError).
              The tooltip explains why so the affordance is honest about
              the constraint instead of showing a useless control. */}
          {activePortfolioId && (
            <button
              aria-label={
                activeIsRoot
                  ? "Cannot delete the aggregate portfolio"
                  : "Delete this portfolio"
              }
              title={
                activeIsRoot
                  ? "Cannot delete the aggregate portfolio"
                  : undefined
              }
              onClick={() => {
                if (!activeIsRoot) setDeletePortfolioOpen(true);
              }}
              disabled={activeIsRoot}
              className={cn(
                "h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border rounded-[2px] flex items-center gap-1 transition-colors",
                activeIsRoot
                  ? "border-border/40 text-muted-foreground/40 cursor-not-allowed"
                  : "border-border text-muted-foreground hover:border-negative/60 hover:text-negative",
              )}
            >
              <Trash2 className="h-3 w-3" />
              Delete
            </button>
          )}
        </div>
      </div>

      {/* ── F-021: scope hint sub-line ───────────────────────────────────── */}
      {/* WHY h-6 (24px): a thin secondary row below the main header keeps
          context in the user's eye-line without taking visual weight away
          from the primary actions above. Hidden when the hint is null
          (manual portfolios) so we don't introduce a phantom empty bar. */}
      {scopeHint && (
        <div className="h-6 shrink-0 px-3 flex items-center border-b border-border/60 bg-muted/10">
          <span className="text-[10px] text-muted-foreground font-mono tabular-nums">
            {scopeHint}
          </span>
        </div>
      )}

      {/* ── Performance strip (period chips removed T-B-2-07) ─────────────── */}
      {/* WHY no period buttons here: per user request, the 1S/1W/1M chips on
          the Holdings page header have been removed — they were redundant with
          EquityCurveChart's own period toggle. The KPI/performance strip is
          now locked to 1D (set in selectedPeriod default). EquityCurveChart's
          1W/1M/3M/6M/1Y/All toggle is unchanged. */}
      <div className="flex shrink-0 items-center justify-end border-b border-border bg-background px-3 py-1">
        {/* Performance result — compact inline display */}
        {performanceLoading ? (
          <span className="font-mono text-[10px] text-muted-foreground">—</span>
        ) : performanceData ? (
          <span
            className={[
              "font-mono text-[10px] tabular-nums font-medium",
              performanceData.return_pct >= 0 ? "text-positive" : "text-negative",
            ].join(" ")}
            title={
              performanceData.covered_pct < 1
                ? `Approximate — only ${Math.round(performanceData.covered_pct * 100)}% of positions have market data`
                : `${selectedPeriod} portfolio return`
            }
          >
            {/* WHY "~" prefix: standard Bloomberg convention when covered_pct < 1 */}
            {performanceData.covered_pct < 0.99 && (
              <span className="text-muted-foreground">~</span>
            )}
            {performanceData.return_pct >= 0 ? "+" : ""}
            {performanceData.return_pct.toFixed(2)}%
            <span className="ml-1 text-muted-foreground/70">
              ({performanceData.return_abs >= 0 ? "+" : ""}
              ${Math.abs(performanceData.return_abs).toFixed(0)})
            </span>
          </span>
        ) : null}
      </div>

      {/* ── KPI Strip ─────────────────────────────────────────────────────── */}
      {/* WHY conditional on holdingsResp (not isLoading): the strip makes no
          sense before holdings load. But we still render the page shell so the
          tabs are visible immediately (preventing layout shift on data arrival). */}
      {holdingsResp && (
        // PLAN-0051 T-A-1-05 — prefer the FIFO endpoint when it succeeds;
        // fall back to the legacy client-side approximation (kpi.realizedPnl)
        // and surface "(approx)" so traders know the value is not the FIFO
        // ground truth. The hook never throws — `isError` flips on a 404 /
        // 503 / network failure, which is exactly when we need the badge.
        // WHY the IIFE: keeps the branching close to the prop site instead
        // of polluting the render with extra `let` variables.
        (() => {
          const fifo = realizedPnLQuery.data;
          const useFifo = !realizedPnLQuery.isError && fifo != null;
          const realizedPnl = useFifo ? fifo!.total_realized : kpi.realizedPnl;
          return (
            <PortfolioKPIStrip
              totalValue={kpi.totalValue}
              dayPnl={kpi.dayPnl}
              unrealisedPnl={kpi.unrealisedPnl}
              unrealisedPnlPct={kpi.unrealisedPnlPct}
              topGainer={kpi.topGainer}
              topLoser={kpi.topLoser}
              positionCount={kpi.positionCount}
              realizedPnl={realizedPnl}
              realizedPnlApprox={!useFifo}
              realizedPnlLongTerm={useFifo ? fifo!.realized_long_term : null}
              realizedPnlShortTerm={useFifo ? fifo!.realized_short_term : null}
            />
          );
        })()
      )}

      {/* ── Tabs ──────────────────────────────────────────────────────────── */}
      {/* WHY flex-1 min-h-0: tabs must fill the remaining space below the KPI strip.
          min-h-0 is required so the overflow-y-auto inside the tab content can
          actually create a scroll area (default flex min-height is content size). */}
      <Tabs defaultValue="holdings" className="flex flex-col flex-1 min-h-0">
        {/* WHY shrink-0 on TabsList: prevents the tab bar from shrinking when
            the tab content grows — the tab bar must always be fully visible. */}
        {/* WHY bg-card on the tab list: the tab bar is page chrome — sits
            above the analytics scroll area. With the page now bg-background,
            keeping the tab bar bg-card aligns it tonally with the KPI strip
            and page header above it (one continuous chrome strip from y=0
            down to the start of the scroll area). */}
        <TabsList className="shrink-0 h-9 px-2 border-b border-border rounded-none bg-card justify-start gap-0">
          <TabsTrigger
            value="holdings"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Holdings
          </TabsTrigger>
          <TabsTrigger
            value="transactions"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Transactions
          </TabsTrigger>
          <TabsTrigger
            value="watchlist"
            className="h-7 px-3 text-[11px] font-mono data-[state=active]:text-primary data-[state=active]:border-b-2 data-[state=active]:border-primary rounded-none"
          >
            Watchlist
          </TabsTrigger>
          {/* WHY no Brokerages tab: merged into Transactions as a collapsible panel
              so traders can see connection status without leaving the transaction context */}
        </TabsList>

        {/* ── Holdings Tab ────────────────────────────────────────────────── */}
        {/* WHY overflow-y-auto: the holdings table can be taller than the viewport.
            Overflow scroll inside the tab panel keeps the tab bar fixed on screen. */}
        <TabsContent
          value="holdings"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          {holdingsLoading && !holdingsResp ? (
            <div className="space-y-px p-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-[22px] w-full" />
              ))}
            </div>
          ) : (
            <div className="p-2">
              {/* WHY enrichedHoldings: raw holdings have empty ticker/name (S1 doesn't
                  store them). enrichedHoldings merges ticker/name/entity_id from company
                  overviews so the TICKER and NAME columns render correctly. */}
              {/* F-205 fix (PLAN-0048 QA iter-1): the SECTOR column was
                  rendering "—" for every holding because we never passed
                  `sectors`. The data is already loaded for the allocation
                  panel below — we just project it into the
                  instrument_id → sector shape SemanticHoldingsTable expects.
                  WHY inline (not useMemo): the projection is O(n) over a
                  small array (≤50 holdings) and runs only when overviews
                  resolve; memoising adds complexity without measurable
                  benefit at this size. */}
              <SemanticHoldingsTable
                holdings={enrichedHoldings}
                quotes={holdingsQuotes}
                sectors={Object.fromEntries(
                  Object.entries(holdingOverviews ?? {}).map(([id, ov]) => [
                    id,
                    ov?.sector ?? null,
                  ]),
                )}
                totalValue={kpi.totalValue}
              />

              {/* Sector allocation — populated once holdingOverviews resolves
                  (Query 7.5). Before that, bySector/byType are empty arrays and
                  SectorAllocationPanel renders nothing (it returns null on empty input).
                  WHY no explicit loading state here: the panel gracefully hides itself
                  when data is absent, so there's no jarring layout shift — it simply
                  appears once the overviews resolve (~300ms after holdings). */}
              <SectorAllocationPanel
                bySector={bySector}
                byType={byType}
              />

              {/* PLAN-0046 Wave 5 / T-46-5-07 — analytics section.
                  WHY conditional on activePortfolioId: the analytics queries
                  need a real portfolio id to fan out to S9. Without one we'd
                  render three loading states forever. The wider page already
                  guards on activePortfolioId for the Add-Position button — we
                  reuse the same gate here so the section appears when there
                  is meaningful data to show. */}
              {activePortfolioId && (
                <PortfolioAnalyticsSection portfolioId={activePortfolioId} />
              )}
            </div>
          )}
        </TabsContent>

        {/* ── Transactions Tab ─────────────────────────────────────────────── */}
        {/* WHY flex flex-col: the brokerage section sits above the transactions
            table. Using flex-col makes the section stack vertically and lets the
            table take the remaining height. */}
        <TabsContent
          value="transactions"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0 flex flex-col"
        >
          {/* ── Brokerage connections collapsible ─────────────────────────── */}
          {/* WHY merged here: brokerage connection status is context for understanding
              which transactions came from which source. Moving it here eliminates the
              separate Brokerages tab and surfaces the information next to the data it
              explains. The section is collapsed by default so the transaction list
              remains the primary focus when the tab is first opened. */}
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

              {/* Connect CTA — always reachable without expanding the section */}
              {activePortfolioId && (
                <button
                  aria-label="Connect a new brokerage"
                  onClick={() => setConnectModalOpen(true)}
                  className="h-6 px-2 text-[10px] font-mono uppercase tracking-[0.06em] border border-primary/60 text-primary rounded-[2px] hover:bg-primary/10 transition-colors shrink-0"
                >
                  + Connect
                </button>
              )}
            </div>

            {/* Expanded brokerage list */}
            {brokeragesSectionExpanded && (
              <div className="px-2 pb-2">
                <ConnectedBrokeragesList portfolioId={activePortfolioId ?? ""} />
              </div>
            )}
          </div>

          {/* ── Transaction list (always visible below brokerage section) ─── */}
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
                // returns tx.ticker = "" because S1's TransactionListItem omits the
                // ticker. The page already fetches getCompanyOverview per holding
                // (holdingOverviews map keyed by instrument_id). Reusing it avoids a
                // second round-trip to enrich transactions and guarantees that the
                // TICKER column matches the holdings table for the same instrument.
                tickerByInstrumentId={Object.fromEntries(
                  Object.entries(holdingOverviews ?? {}).map(([id, ov]) => [
                    id,
                    ov?.ticker,
                  ]),
                )}
              />
            )}
          </div>
        </TabsContent>

        {/* ── Watchlist Tab ─────────────────────────────────────────────────── */}
        <TabsContent
          value="watchlist"
          className="flex-1 min-h-0 overflow-y-auto p-0 mt-0"
        >
          {/* WHY render the watchlist name in the tab content:
              The existing test checks `screen.getByText("Tech Watch")` after
              clicking the Watchlist tab. WatchlistsTabPanel shows the watchlist
              name in its internal tab bar — satisfying this assertion. */}
          <WatchlistsTabPanel
            watchlists={watchlists ?? []}
            quotes={watchlistQuotes}
            isLoading={watchlistsLoading}
          />
        </TabsContent>
      </Tabs>

      {/* ── Connect Brokerage Modal ──────────────────────────────────────── */}
      {/* WHY outside Tabs: the modal must persist through tab switches during
          the OAuth redirect flow. If inside a TabsContent it would unmount on
          tab switch and lose the in-progress connection state. */}
      {activePortfolioId && (
        <ConnectBrokerageModal
          portfolioId={activePortfolioId}
          portfolioName={activePortfolio?.name}
          open={connectModalOpen}
          onOpenChange={setConnectModalOpen}
        />
      )}

      {/* ── Create Portfolio Dialog ─────────────────────────────────────── */}
      {/* WHY outside Tabs: this dialog is triggered from the page header, not from
          within a tab. Keeping it at the page root prevents accidental unmount if
          the user somehow navigates away while the dialog is open (defensive pattern
          — dialogs should survive as long as the page is mounted). */}
      <CreatePortfolioDialog
        open={createPortfolioOpen}
        onOpenChange={setCreatePortfolioOpen}
        onSuccess={handlePortfolioCreated}
        accessToken={accessToken}
      />

      {/* ── F-013: Delete Portfolio confirmation Dialog ──────────────────── */}
      {/* Render only when there's something to delete; the underlying
          shadcn Dialog already short-circuits on ``open=false`` but
          guarding with activePortfolioId avoids reading stale state if
          the active portfolio was just removed. */}
      {activePortfolioId && activePortfolio && (
        <Dialog
          open={deletePortfolioOpen}
          onOpenChange={(o) => {
            // Block the user from dismissing the dialog while a delete is in flight.
            if (!deletePortfolioMutation.isPending) setDeletePortfolioOpen(o);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete portfolio?</DialogTitle>
            </DialogHeader>
            <p className="text-[12px] text-muted-foreground font-sans">
              {/* Quoted name guards against weird display in mixed-charset
                  portfolios. The "Holdings will be unaffected" line is an
                  important reassurance — S1 archives the portfolio (soft
                  delete) and existing holdings rows remain attached but
                  no longer surface in queries. */}
              Delete portfolio &quot;{activePortfolio.name}&quot;? Holdings will be unaffected.
            </p>
            {deletePortfolioMutation.isError && (
              <p className="text-[11px] text-negative font-mono">
                Failed to delete. Try again or check the server logs.
              </p>
            )}
            <DialogFooter>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setDeletePortfolioOpen(false)}
                disabled={deletePortfolioMutation.isPending}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => deletePortfolioMutation.mutate(activePortfolioId)}
                disabled={deletePortfolioMutation.isPending}
              >
                {deletePortfolioMutation.isPending ? "Deleting…" : "Delete"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {/* ── Add Position Dialog ──────────────────────────────────────────── */}
      {/* WHY conditional on activePortfolioId: without a portfolio, the Add Position
          dialog has nowhere to add a position to. We gate the entire component rather
          than just disabling the button — a mounted dialog with a null portfolioId
          would crash on submission. */}
      {activePortfolioId && (
        <AddPositionDialog
          open={addPositionOpen}
          onOpenChange={setAddPositionOpen}
          onSuccess={handlePositionAdded}
          portfolioId={activePortfolioId}
          accessToken={accessToken}
        />
      )}
    </div>
  );
}
