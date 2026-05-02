"use client";

/**
 * features/portfolio/components/AddPositionDialog.tsx
 *
 * Modal for manually adding a new position to a portfolio.
 *
 * WHY a BUY transaction (not a direct "add holding" call): S1 has no
 * dedicated endpoint for creating holdings. Holdings are derived from
 * transaction history — a BUY transaction increases (or creates) a holding.
 * This mirrors how a real broker records a purchase. See gateway.addPosition
 * for the S1 mapping.
 *
 * TICKER RESOLUTION FLOW:
 *   1. User types a ticker (e.g. "AAPL")
 *   2. On submit → searchInstruments("AAPL") → gets instrument_id
 *   3. addPosition(portfolioId, instrument_id, qty, price) → POST /v1/transactions
 *   4. On success → invalidate ["holdings", portfolioId] so the table refreshes
 *
 * WHY resolve ticker server-side (not via user-supplied instrument_id):
 * Instrument IDs are internal UUIDs — they're not meaningful to a user.
 * Letting users type tickers and resolving them to instrument_ids at submit
 * time is the standard UX for all finance terminals (Bloomberg, Schwab, etc.).
 *
 * WHY no autocomplete on the ticker field: adding a dependency on a live
 * search query inside a modal is complex. The simpler approach is to resolve
 * on submit and show an error if the ticker doesn't exist (same flow as
 * Bloomberg CMD line entry). Autocomplete can be added later as a UX
 * enhancement.
 */

import { useState, useCallback } from "react";
import { createGateway } from "@/lib/gateway";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface AddPositionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
  portfolioId: string;
  accessToken: string | null | undefined;
}

export function AddPositionDialog({
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
    // WHY avgPrice optional: some traders enter positions at cost=0 (e.g.,
    // gifted shares, or when exact cost basis is unknown). We allow
    // empty/zero but not negative.
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
      // WHY search with limit=1: we only need the best match (exact ticker
      // match is ranked first by S3's instrument search).
      const searchResult = await gw.searchInstruments(trimmedTicker, 1);
      const instrument = searchResult.results[0];

      if (!instrument) {
        // WHY user-facing error (not throw): the user may have mistyped the
        // ticker. Show an inline error with guidance rather than crashing
        // the dialog.
        setError(
          `Ticker "${trimmedTicker}" not found. Check the symbol and try again.`,
        );
        setIsSubmitting(false);
        return;
      }

      // ── Step 2: add the position via a BUY transaction ─────────────────
      // gateway.addPosition() maps to POST /v1/transactions with
      // direction=BUY. The response is the created transaction (we don't
      // need to use it here — we just care that the request succeeded so we
      // can refetch holdings).
      await gw.addPosition(
        portfolioId,
        instrument.instrument_id,
        parsedQty,
        costBasis,
      );

      // Reset form on success.
      setTicker("");
      setQuantity("");
      setAvgPrice("");
      setError(null);

      // Notify parent to invalidate ["holdings", portfolioId] so the table
      // updates.
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
        // Clear form on close so the dialog is fresh on next open.
        setTicker("");
        setQuantity("");
        setAvgPrice("");
        setError(null);
      }
      onOpenChange(nextOpen);
    },
    [isSubmitting, onOpenChange],
  );

  // WHY disable submit when ticker is empty: quantity and price have
  // sensible defaults (empty = 0), but a ticker-less submission would
  // always fail at the search step. Disable early to prevent a wasted
  // network round-trip.
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
              // WHY toUpperCase(): tickers are always uppercase in financial
              // systems. Converting as-you-type prevents "aapl" from failing
              // the S3 search lookup.
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
              // WHY step="any": S1 stores quantity as Decimal(18,8). Users
              // may have fractional shares (e.g., crypto or fractional
              // equity programs like Robinhood).
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
              // WHY optional: some users add positions without knowing exact
              // cost basis (gifted shares, inherited positions). Defaults to 0.
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
