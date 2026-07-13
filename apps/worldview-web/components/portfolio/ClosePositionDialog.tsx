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
 * FIELDS (per PRD §7.2, quantity un-locked in PLAN-0122 W-D §6.5):
 *   - Ticker: read-only — so the user knows which position they're closing
 *   - Quantity: EDITABLE — pre-filled with the FULL holding quantity so a full
 *     close stays one click, but the user may enter a smaller quantity for a
 *     PARTIAL close (0 < qty ≤ holding.quantity). A "Sell all" link resets it to
 *     the full holding. The backend already accepts any positive SELL quantity
 *     (PRD-0122 §1.2.3), so partial close is a pure frontend un-lock.
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

import { useRef, useState } from "react";
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

  // PLAN-0122 W-D (§6.5): quantity is now EDITABLE for partial closes. Default to
  // the FULL holding quantity so the historical "full close in one click"
  // behaviour is preserved — the user only changes it when they want to sell part.
  // WHY string (not number): controlled inputs need strings; parsed on submit.
  const [quantityStr, setQuantityStr] = useState(String(holding.quantity));

  // Loading + error state for the submit action.
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [priceError, setPriceError] = useState<string | null>(null);
  const [quantityError, setQuantityError] = useState<string | null>(null);
  // Future-date guard error (QA item 5): the date input now also carries a
  // `max={today}` attribute, but a typed/pasted future value is rejected here.
  const [dateError, setDateError] = useState<string | null>(null);

  // WHY useRef for idempotency key (not useState): we need a stable value for
  // the entire lifecycle of this dialog instance. If the user double-clicks
  // "Confirm" (or the network is slow and they click again), both requests will
  // carry the same key and S1 will deduplicate them, preventing duplicate SELL
  // transactions from corrupting FIFO cost-basis and holdings. useRef is correct
  // because changing the key should NOT cause a re-render.
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());

  // attemptedRef + bumpIdempotencyOnEdit (QA item 6): a fixed key protects
  // against double-clicks, but if the user changes a submittable input (quantity,
  // sale price, trade date) after a failed/completed attempt and resubmits, that
  // corrected request must be a DISTINCT idempotency key — otherwise S1 dedupes
  // it against the stale first attempt and silently drops the correction. We mint
  // a fresh key the first time an input changes after an attempt, then clear the
  // flag so further keystrokes reuse the same new key (double-click still safe).
  const attemptedRef = useRef(false);
  function bumpIdempotencyOnEdit() {
    if (attemptedRef.current) {
      idempotencyKeyRef.current = crypto.randomUUID();
      attemptedRef.current = false;
    }
  }

  // ── Validation ────────────────────────────────────────────────────────────

  function validatePrice(raw: string): number | null {
    const n = parseFloat(raw);
    if (!isFinite(n) || n <= 0) return null;
    return n;
  }

  // PLAN-0122 W-D (§6.5): validate the (now editable) quantity. Returns the
  // parsed quantity, or null with a specific error message set. Rules:
  //   - must be > 0 ("Quantity must be greater than 0.")
  //   - must be ≤ the holding quantity ("You only hold {n} shares.") — a
  //     client-side over-sell guard (S1 would still record it, but we prevent the
  //     confusing derived-recompute an over-sell would produce).
  function validateQuantity(raw: string): number | null {
    const n = parseFloat(raw);
    if (!isFinite(n) || n <= 0) {
      setQuantityError("Quantity must be greater than 0.");
      return null;
    }
    if (n > holding.quantity) {
      setQuantityError(`You only hold ${holding.quantity.toLocaleString()} shares.`);
      return null;
    }
    setQuantityError(null);
    return n;
  }

  // Derived full/partial state for the labels + "Sell all" affordance. A parse
  // failure is treated as "not partial" so an in-progress edit doesn't flicker
  // the title; the real validation happens on submit.
  const parsedQty = parseFloat(quantityStr);
  const isPartial =
    Number.isFinite(parsedQty) && parsedQty > 0 && parsedQty < holding.quantity;

  // ── Submit ────────────────────────────────────────────────────────────────

  async function handleConfirm() {
    if (isSubmitting) return;

    // Validate the (editable) quantity first — a partial close must be a
    // positive quantity no larger than the holding (PLAN-0122 W-D §6.5).
    const sellQuantity = validateQuantity(quantityStr);
    if (sellQuantity === null) {
      // validateQuantity already set the specific error message.
      return;
    }

    // Validate the sale price before hitting the API.
    const salePrice = validatePrice(salePriceStr);
    if (salePrice === null) {
      setPriceError("Please enter a valid sale price greater than 0.");
      return;
    }
    setPriceError(null);

    // Reject a future trade date (QA item 5). Backdating a close is allowed (e.g.
    // after a market holiday) but a FUTURE close is nonsensical — you cannot have
    // sold shares tomorrow. String compare is valid for zero-padded ISO dates.
    if (tradeDateStr > todayStr) {
      setDateError("Trade date can't be in the future.");
      return;
    }
    setDateError(null);

    setIsSubmitting(true);
    // POSTing with the current key; a later input edit regenerates it (item 6).
    attemptedRef.current = true;

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
        // PLAN-0122 W-D: the entered quantity (full holding by default, or a
        // smaller partial-close amount). Validated 0 < qty ≤ holding.quantity.
        quantity: sellQuantity,
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

      const response = await fetch("/api/v1/transactions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // WHY Idempotency-Key: the backend (S1) deduplicates POST /transactions
          // requests that carry the same key, preventing duplicate SELL entries
          // from double-clicks or retries. The key is stable for the dialog
          // instance (useRef above) so rapid re-clicks all carry the same key.
          "Idempotency-Key": idempotencyKeyRef.current,
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
        // WHY no duration override: centralized Toaster in app/providers.tsx
        // sets duration=4000 for all toasts (DESIGN_SYSTEM.md §6.16 + toast-config.test.ts).
        description:
          "Holdings will update within seconds once the recompute event is processed.",
      });

      onSuccess();
      onClose();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Failed to close position. Please try again.";
      toast.error("Close position failed", {
        // WHY no duration override: centralized Toaster in app/providers.tsx
        // sets duration=4000 for all toasts (DESIGN_SYSTEM.md §6.16 + toast-config.test.ts).
        description: message,
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

          {/* Quantity — EDITABLE (PLAN-0122 W-D §6.5): defaults to the full
              holding quantity (full close in one click) but the user may enter a
              smaller amount for a partial close. A "Sell all" link resets it to
              the full holding. The backend already accepts any positive SELL
              quantity, so this is a pure frontend un-lock (no backend change). */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="close-qty"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Quantity
            </Label>
            <div className="col-span-2 flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <Input
                  id="close-qty"
                  type="number"
                  min="0"
                  step="any"
                  value={quantityStr}
                  onChange={(e) => {
                    setQuantityStr(e.target.value);
                    // Clear the validation error as soon as the user edits.
                    if (quantityError) setQuantityError(null);
                    // Corrected qty after a prior attempt → fresh idempotency key.
                    bumpIdempotencyOnEdit();
                  }}
                  className="h-7 flex-1 font-mono text-[12px]"
                />
                {/* "Sell all" resets to the full holding — the Full/Partial
                    affordance (R-21). Shown only when the field is not already
                    at the full amount so it doesn't read as a redundant control. */}
                {isPartial && (
                  <button
                    type="button"
                    onClick={() => {
                      setQuantityStr(String(holding.quantity));
                      setQuantityError(null);
                    }}
                    className="shrink-0 text-[10px] uppercase tracking-wide text-primary hover:underline"
                  >
                    Sell all
                  </button>
                )}
              </div>
              {/* Full/Partial intent label (R-21): the header stays "Close
                  Position — {ticker}"; this line makes the effect explicit. */}
              <p
                data-testid="close-mode-label"
                className="text-[10px] text-muted-foreground"
              >
                {isPartial
                  ? `Sell ${parsedQty.toLocaleString()} of ${holding.quantity.toLocaleString()}`
                  : "Close Position"}
              </p>
              {quantityError && (
                <p className="text-[10px] text-destructive">{quantityError}</p>
              )}
            </div>
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
                  bumpIdempotencyOnEdit();
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

          {/* Trade Date — date picker; defaults to today; backdating is allowed
              but future dates are blocked (max attr + submit-side guard, item 5). */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="close-date"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Trade Date
            </Label>
            <div className="col-span-2 flex flex-col gap-1">
              <Input
                id="close-date"
                type="date"
                max={todayStr}
                value={tradeDateStr}
                onChange={(e) => {
                  setTradeDateStr(e.target.value);
                  if (dateError) setDateError(null);
                  bumpIdempotencyOnEdit();
                }}
                className="h-7 font-mono text-[12px]"
              />
              {dateError && (
                <p className="text-[10px] text-destructive">{dateError}</p>
              )}
            </div>
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
            {/* Label reflects full vs partial intent (R-21). Full close keeps the
                "Close Position" label existing tests + muscle-memory rely on. */}
            {isSubmitting
              ? "Closing…"
              : isPartial
                ? `Sell ${parsedQty.toLocaleString()} of ${holding.quantity.toLocaleString()}`
                : "Close Position"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
