/**
 * components/portfolio/ClosePositionDialog.tsx — "Close Position" dialog for
 * the SemanticHoldingsTable AG Grid context menu (PRD-0114 W5-T05).
 *
 * WHY THIS EXISTS: closes a long position by recording a SELL transaction via
 * the S9 gateway. The dialog pre-fills the full holding quantity and today's
 * date, requiring the user only to confirm the sale price. This is the
 * minimum-friction path for exiting a position without navigating to the
 * Add Position form and manually choosing SELL.
 *
 * FIELDS (per PRD §7.2):
 *   - Ticker: read-only — so the user knows which position they're closing
 *   - Quantity: read-only — pre-filled from the holding (full close by default)
 *   - Sale Price: user-entered, required, > 0
 *   - Trade Date: date picker, defaults to today; user can change it for
 *     a backdated close (e.g. after a market holiday)
 *
 * WHY trade_side: "SELL" (not transaction_type: "SELL"):
 *   S1's RecordTransactionRequest uses `transaction_type: "TRADE"` for manual
 *   trades and `trade_side: "BUY" | "SELL"` for the direction. This matches
 *   the addPosition() and addTransaction() patterns in lib/api/portfolios.ts.
 *
 * WHY lazy loading:
 *   The Close Position dialog is only opened from the AG Grid context menu —
 *   it is never visible on initial page load. React.lazy + Suspense keeps it
 *   out of the initial bundle so the cold-start time for the portfolio page
 *   is not penalised. The parent (SemanticHoldingsTable) uses a dynamic import.
 *
 * WHO USES IT: components/portfolio/SemanticHoldingsTable.tsx
 */

"use client";
// WHY "use client": useState for form state, fetch for API calls, event handlers.

import { useState } from "react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import type { Holding } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ClosePositionDialogProps {
  /** The holding being closed — provides ticker, quantity, instrument_id. */
  holding: Holding;
  /** The portfolio that owns this holding — needed for the POST body. */
  portfolioId: string;
  /**
   * Called after a successful close so the parent can refetch holdings/transactions
   * and show the updated (empty or reduced) position list.
   */
  onSuccess: () => void;
  /**
   * Called when the user dismisses the dialog (Cancel button or Esc key).
   * The parent controls open/close state via this callback.
   */
  onClose: () => void;
  /** Auth token for the S9 gateway POST /v1/transactions. */
  accessToken?: string | null;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ClosePositionDialog({
  holding,
  portfolioId,
  onSuccess,
  onClose,
  accessToken,
}: ClosePositionDialogProps) {
  // ── Form state ────────────────────────────────────────────────────────────

  // Sale price — user must enter this; default to current average cost as a
  // starting suggestion (user will override with the actual market price).
  // WHY string (not number): controlled inputs need strings; we parse on submit.
  const [salePriceStr, setSalePriceStr] = useState(
    holding.average_cost > 0 ? holding.average_cost.toFixed(2) : "",
  );

  // Trade date — defaults to today in YYYY-MM-DD format (ISO 8601 local date).
  // WHY toLocaleDateString with ISO components: new Date().toISOString() gives
  // UTC midnight which may display as yesterday in UTC-5 timezones. We build
  // YYYY-MM-DD from local date parts instead.
  const todayStr = (() => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  })();
  const [tradeDateStr, setTradeDateStr] = useState(todayStr);

  // Loading + error state for the submit action.
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);

  // ── Validation ────────────────────────────────────────────────────────────

  function validatePrice(raw: string): number | null {
    const n = parseFloat(raw);
    if (!isFinite(n) || n <= 0) return null;
    return n;
  }

  // ── Submit ────────────────────────────────────────────────────────────────

  async function handleConfirm() {
    if (isSubmitting) return;

    // Validate the sale price before hitting the API.
    const salePrice = validatePrice(salePriceStr);
    if (salePrice === null) {
      setPriceError("Please enter a valid sale price greater than 0.");
      return;
    }
    setPriceError(null);
    setIsSubmitting(true);

    try {
      // Build the S1 RecordTransactionRequest body.
      //
      // WHY transaction_type: "TRADE" + trade_side: "SELL":
      //   S1 uses a two-field model: `transaction_type` describes the economic
      //   event category ("TRADE" = manual equity trade) and `trade_side`
      //   describes directionality ("BUY" increases the position, "SELL"
      //   decreases it). This is the same convention used by addPosition() and
      //   the AddPositionDialog in this codebase.
      //
      // WHY executed_at as ISO 8601 with T00:00:00Z suffix:
      //   S1 expects a datetime string (not a bare date). We append midnight UTC
      //   to the user-selected date because the transaction_date in the filter
      //   bar maps `CAST(executed_at AS DATE)` — the time component is not
      //   meaningful for manual entries.
      const body = {
        portfolio_id: portfolioId,
        instrument_id: holding.instrument_id,
        transaction_type: "TRADE",
        trade_side: "SELL",
        quantity: holding.quantity,
        price: salePrice,
        fees: 0,                     // manual close has no brokerage fee
        // WHY "USD" default: the Holding type does not carry a currency field
        // (holdings are portfolio-currency-denominated; the per-transaction
        // currency is stored on the Transaction record). Manual close entries
        // default to "USD" — the same default used by addPosition() and
        // addTransaction() in lib/api/portfolios.ts.
        currency: "USD",
        executed_at: `${tradeDateStr}T00:00:00Z`,
        external_ref: null,
      };

      const response = await fetch("/v1/transactions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const errJson = (await response.json()) as { detail?: string };
          if (errJson.detail) detail = errJson.detail;
        } catch { /* use status code */ }
        throw new Error(detail);
      }

      // Success path:
      //   1. Show a toast explaining the async holdings update (FR-8).
      //   2. Call onSuccess so the parent can invalidate + refetch.
      //   3. Close the dialog.
      toast.success("Position closed", {
        description:
          "Holdings will update within seconds once the recompute event is processed.",
        duration: 5000,
      });

      onSuccess();
      onClose();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to close position. Please try again.";
      toast.error("Close position failed", {
        description: message,
        duration: 8000,
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    // WHY open={true}: the parent controls whether ClosePositionDialog is
    // rendered at all — when it renders, the dialog is always open. The parent
    // unmounts the component via conditional rendering on dialog close rather
    // than toggling the `open` prop, so we keep the prop fixed at true here.
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-[400px]">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm tracking-wide">
            Close Position — {holding.ticker || holding.name || "Unknown"}
          </DialogTitle>
        </DialogHeader>

        {/* ── Form fields ──────────────────────────────────────────────────── */}
        <div className="grid gap-4 py-2">

          {/* Ticker — read-only: confirms which position the user is closing */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="close-ticker"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Ticker
            </Label>
            <Input
              id="close-ticker"
              // WHY readOnly (not disabled): read-only inputs are still
              // selectable/copyable, which is useful if the ticker is long.
              // Disabled inputs are grayed-out AND non-interactive — read-only
              // gives the right visual weight (still shows as a field, just
              // not editable).
              readOnly
              value={holding.ticker || holding.name || "—"}
              className="col-span-2 h-7 font-mono text-[12px] bg-muted/30 cursor-default"
              tabIndex={-1}
            />
          </div>

          {/* Quantity — read-only: pre-filled with the full holding quantity */}
          {/* WHY not editable: "Close Position" means closing the FULL position.
              Partial closes can be achieved by recording a SELL transaction
              through the normal Add Position dialog. Locking quantity here
              prevents accidental partial closes when the intent is a full exit. */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="close-qty"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Quantity
            </Label>
            <Input
              id="close-qty"
              readOnly
              value={holding.quantity.toLocaleString()}
              className="col-span-2 h-7 font-mono text-[12px] bg-muted/30 cursor-default"
              tabIndex={-1}
            />
          </div>

          {/* Sale Price — user-entered; required; must be > 0 */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="close-price"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Sale Price
            </Label>
            <div className="col-span-2 flex flex-col gap-1">
              <Input
                id="close-price"
                type="number"
                min="0.000001"
                step="0.01"
                placeholder="0.00"
                value={salePriceStr}
                onChange={(e) => {
                  setSalePriceStr(e.target.value);
                  // Clear validation error as soon as the user starts typing again.
                  if (priceError) setPriceError(null);
                }}
                className="h-7 font-mono text-[12px]"
                autoFocus
              />
              {/* Inline validation error — shown only after a failed submit attempt */}
              {priceError && (
                <p className="text-[10px] text-destructive">{priceError}</p>
              )}
            </div>
          </div>

          {/* Trade Date — date picker; defaults to today; backdating is allowed */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="close-date"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Trade Date
            </Label>
            <Input
              id="close-date"
              type="date"
              value={tradeDateStr}
              onChange={(e) => setTradeDateStr(e.target.value)}
              className="col-span-2 h-7 font-mono text-[12px]"
            />
          </div>
        </div>

        {/* ── Action buttons ────────────────────────────────────────────────── */}
        <DialogFooter className="gap-2">
          {/* Cancel — dismisses without any API call */}
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Cancel
          </Button>

          {/* Confirm — records the SELL transaction */}
          <Button
            variant="destructive"
            size="sm"
            onClick={() => void handleConfirm()}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Closing…" : "Close Position"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
