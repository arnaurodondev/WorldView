/**
 * components/portfolio/EditPositionDialog.tsx — PLAN-0122 W-D (T-A-D-02):
 * the HONEST "Edit Position" dialog for a single holding.
 *
 * ⚠️ NAMING GUARD (PLAN-0122 W-D): this file edits a *holding* (a position) by
 * recording an adjusting trade. Do NOT confuse it with the already-shipped
 * `features/portfolio/components/EditPortfolioDialog.tsx` (PLAN-0114 W6), which
 * edits a *portfolio's* cost_basis_method via `PATCH /portfolios/{id}`. Different
 * file, different target, different endpoint — both coexist intentionally.
 *
 * WHY THIS EXISTS — the honest-ledger mechanism (PRD-0122 §6.4 / §1.2.4):
 *   Holdings are DERIVED from the transaction ledger; there is NO transaction
 *   PATCH/DELETE and NO in-place holding mutation on the backend. So "editing" a
 *   position can only mean posting a NEW adjusting trade that reconciles the
 *   ledger to the user's target quantity:
 *
 *       delta = targetQty − currentQty
 *       delta > 0  → BUY  of delta          (want more shares)
 *       delta < 0  → SELL of |delta|        (want fewer shares; 0 = full exit)
 *       delta == 0 → nothing to record      (Submit disabled)
 *
 *   The dialog shows the current position READ-ONLY and previews the exact trade
 *   it will record ("Record BUY of 30") so the effect is transparent BEFORE
 *   submit. It NEVER rewrites history and NEVER silently overwrites average cost —
 *   the backend recomputes avg cost from the full trade history. An unmissable
 *   note states this in plain language.
 *
 * WHY raw fetch (mirrors ClosePositionDialog, not gateway.addTransaction):
 *   the adjusting trade needs an Idempotency-Key header so a double-click cannot
 *   post two BUY/SELLs and corrupt the derived holding. gateway.addTransaction()
 *   does not send that header; ClosePositionDialog's proven raw-fetch pattern
 *   (stable useRef key) does. Same endpoint (`POST /api/v1/transactions`), same
 *   body shape as Close/Add — no new endpoint (PRD-0122 §8).
 *
 * WHO USES IT: components/portfolio/SemanticHoldingsTable.tsx (opened from the
 * row-kebab menu and the right-click context menu).
 */

"use client";
// WHY "use client": useState/useRef form state, fetch, and event handlers.

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
// WHY formatPrice (not a hand-built `$${n.toFixed(2)}`): the architecture guard
// (no-off-palette-colors.test.ts, HF-10 1A) forbids hand-built currency literals
// so every price goes through the one canonical USD formatter.
import { formatPrice } from "@/lib/utils";
import { computeAdjustment } from "@/lib/portfolio/adjusting-transaction";
import type { Holding } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface EditPositionDialogProps {
  /** The holding being edited — provides ticker, current quantity, avg cost. */
  holding: Holding;
  /** The portfolio that owns this holding — needed for the POST body. */
  portfolioId: string;
  /**
   * The row's current live price, if available (from the enriched holdings row).
   * Used only as the DEFAULT adjustment price; the user can override it. Falls
   * back to the holding's average cost when no live price is known (PRD §6.4).
   */
  currentPrice?: number | null;
  /** Called after a successful adjustment so the parent can refetch holdings. */
  onSuccess: () => void;
  /** Called when the user dismisses the dialog (Cancel / Esc / backdrop). */
  onClose: () => void;
  /** Auth token forwarded to the S9 gateway POST /v1/transactions. */
  accessToken?: string | null;
}

// ── Local date builder (shared convention with ClosePositionDialog) ────────────
// WHY build YYYY-MM-DD from LOCAL parts (not toISOString): toISOString() returns
// UTC midnight, which can render as "yesterday" in negative-offset timezones. We
// want the date the user perceives as "today", so we read local date components.
function todayLocalISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function EditPositionDialog({
  holding,
  portfolioId,
  currentPrice,
  onSuccess,
  onClose,
  accessToken,
}: EditPositionDialogProps) {
  // ── Form state ────────────────────────────────────────────────────────────

  // Target quantity — pre-filled with the CURRENT quantity so the dialog opens
  // in a no-op state (delta 0 → Submit disabled). The user changes it to the
  // quantity they want to end up holding. String because controlled inputs need
  // strings; parsed on every render for the live delta preview.
  const [targetQtyStr, setTargetQtyStr] = useState(String(holding.quantity));

  // Adjustment price — the price at which the delta trade is recorded. Default to
  // the live price when known (PRD §6.4), else the position's average cost as a
  // sensible starting suggestion. The user overrides with the real fill price.
  const defaultPrice =
    currentPrice != null && currentPrice > 0
      ? currentPrice
      : holding.average_cost;
  const [priceStr, setPriceStr] = useState(
    defaultPrice > 0 ? defaultPrice.toFixed(2) : "",
  );

  // Trade date — defaults to today; not allowed in the future (max=today).
  const todayStr = todayLocalISO();
  const [tradeDateStr, setTradeDateStr] = useState(todayStr);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [qtyError, setQtyError] = useState<string | null>(null);
  const [priceError, setPriceError] = useState<string | null>(null);

  // WHY useRef for the idempotency key (not useState): a stable value for the
  // whole dialog lifecycle. A double-click / retry carries the SAME key so S1
  // deduplicates and cannot post two adjusting trades. Changing it must NOT
  // trigger a re-render — useRef is correct. Mirrors ClosePositionDialog.
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());

  // ── Derived delta preview (the transparency guarantee, R-17) ────────────────
  // Parse the raw inputs and compute the adjusting trade so we can (a) label the
  // Submit button with the exact action and (b) disable it on a 0 / invalid delta.
  // computeAdjustment throws on an invalid target (negative/NaN); we treat that as
  // "no valid adjustment yet" and let the inline validation on submit explain it.
  const targetQty = parseFloat(targetQtyStr);
  let adjustment: ReturnType<typeof computeAdjustment> = null;
  let adjustmentValid = false;
  if (Number.isFinite(targetQty) && targetQty >= 0) {
    adjustment = computeAdjustment(holding.quantity, targetQty);
    adjustmentValid = true; // a finite non-negative target is a valid input
  }

  const price = parseFloat(priceStr);
  const priceValid = Number.isFinite(price) && price > 0;

  // Submit is enabled only when there is a real trade to record AND the price is
  // valid. delta === 0 (adjustment null) → nothing to record → disabled.
  const canSubmit = adjustmentValid && adjustment !== null && priceValid;

  // Human-readable submit label reflecting the derived action (R-18).
  const submitLabel = (() => {
    if (isSubmitting) return "Recording…";
    if (adjustment) {
      return `Record ${adjustment.side} of ${adjustment.quantity.toLocaleString()}`;
    }
    // delta 0 (or not-yet-valid) — a neutral label; the button is disabled.
    return "No change";
  })();

  // ── Submit ────────────────────────────────────────────────────────────────

  async function handleConfirm() {
    if (isSubmitting) return;

    // Validate the target quantity first.
    if (!Number.isFinite(targetQty) || targetQty < 0) {
      setQtyError("Enter a target quantity of 0 or more.");
      return;
    }
    setQtyError(null);

    // Validate the adjustment price.
    if (!priceValid) {
      setPriceError("Enter a valid price greater than 0.");
      return;
    }
    setPriceError(null);

    // Compute the honest adjusting trade. `null` = no change → nothing to do
    // (the button is disabled in this state, but we guard defensively).
    const adj = computeAdjustment(holding.quantity, targetQty);
    if (!adj) return;

    setIsSubmitting(true);
    try {
      // Same body shape as Close/Add (PRD §6.4) — no new endpoint. `trade_side`
      // and `quantity` come straight from the pure helper so the request can
      // never disagree with the on-screen preview.
      const body = {
        portfolio_id: portfolioId,
        instrument_id: holding.instrument_id,
        transaction_type: "TRADE",
        trade_side: adj.side,
        quantity: adj.quantity,
        price,
        fees: 0,
        currency: "USD",
        executed_at: `${tradeDateStr}T00:00:00Z`,
        external_ref: null,
      };

      const response = await fetch("/api/v1/transactions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // Stable per dialog instance → S1 de-dupes double-submits.
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
        } catch {
          /* fall back to the status code */
        }
        throw new Error(detail);
      }

      // Success — same UX as Add/Close: toast + parent refetch + close.
      toast.success("Adjustment recorded", {
        description: "Holdings update within seconds.",
      });
      onSuccess();
      onClose();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Failed to record the adjustment. Please try again.";
      // WHY keep the dialog OPEN on error (mirrors ClosePositionDialog): the user
      // keeps their entered values and can retry without re-typing.
      toast.error("Adjustment failed", { description: message });
    } finally {
      setIsSubmitting(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const ticker = holding.ticker || holding.name || "Unknown";

  return (
    // open is fixed true — the parent mounts/unmounts this component to control it
    // (same lifecycle pattern as ClosePositionDialog).
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="sm:max-w-[420px]">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm tracking-wide">
            Edit Position — {ticker}
          </DialogTitle>
        </DialogHeader>

        {/* ── Current position (read-only reference) ───────────────────────── */}
        {/* WHY read-only: the current qty / avg cost / market value are DERIVED
            facts the user cannot type over. Showing them frames the edit as
            "move from here → to a target", not "overwrite these numbers". */}
        <div className="grid grid-cols-3 gap-x-3 gap-y-1.5 rounded-[2px] border border-border/50 bg-muted/30 px-3 py-2.5 text-[11px] font-mono">
          <span className="text-muted-foreground">Current Qty</span>
          <span className="col-span-2 text-right tabular-nums text-foreground">
            {holding.quantity.toLocaleString()}
          </span>
          <span className="text-muted-foreground">Avg Cost</span>
          <span className="col-span-2 text-right tabular-nums text-foreground">
            {holding.average_cost > 0 ? formatPrice(holding.average_cost) : "—"}
          </span>
          <span className="text-muted-foreground">Mkt Value</span>
          <span className="col-span-2 text-right tabular-nums text-foreground">
            {defaultPrice > 0 ? formatPrice(defaultPrice * holding.quantity) : "—"}
          </span>
        </div>

        {/* ── Editable fields ──────────────────────────────────────────────── */}
        <div className="grid gap-4 py-2">
          {/* Target Quantity — the quantity the user wants to END UP holding.
              0 means "close entirely" (records a full SELL). */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="edit-target-qty"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Target Qty
            </Label>
            <div className="col-span-2 flex flex-col gap-1">
              <Input
                id="edit-target-qty"
                type="number"
                min="0"
                step="any"
                value={targetQtyStr}
                onChange={(e) => {
                  setTargetQtyStr(e.target.value);
                  if (qtyError) setQtyError(null);
                }}
                className="h-7 font-mono text-[12px]"
                autoFocus
              />
              {qtyError && (
                <p className="text-[10px] text-destructive">{qtyError}</p>
              )}
            </div>
          </div>

          {/* Adjustment Price — the price the delta trade is recorded at. */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="edit-price"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Price
            </Label>
            <div className="col-span-2 flex flex-col gap-1">
              <Input
                id="edit-price"
                type="number"
                min="0.000001"
                step="0.01"
                placeholder="0.00"
                value={priceStr}
                onChange={(e) => {
                  setPriceStr(e.target.value);
                  if (priceError) setPriceError(null);
                }}
                className="h-7 font-mono text-[12px]"
              />
              {priceError && (
                <p className="text-[10px] text-destructive">{priceError}</p>
              )}
            </div>
          </div>

          {/* Trade Date — defaults to today; future dates are blocked (max). */}
          <div className="grid grid-cols-3 items-center gap-3">
            <Label
              htmlFor="edit-date"
              className="text-right text-[11px] text-muted-foreground font-mono"
            >
              Trade Date
            </Label>
            <Input
              id="edit-date"
              type="date"
              max={todayStr}
              value={tradeDateStr}
              onChange={(e) => setTradeDateStr(e.target.value)}
              className="col-span-2 h-7 font-mono text-[12px]"
            />
          </div>
        </div>

        {/* ── Honest-ledger note (R-17) — unmissable ───────────────────────── */}
        {/* WHY this copy: an edit is a REAL adjusting trade, not a history rewrite.
            Stating it plainly is the mitigation for the "editing = dishonest"
            risk (PRD §11) and is pinned by test_edit_position_ledger_note_present. */}
        <p
          data-testid="edit-position-ledger-note"
          className="rounded-[2px] border border-border/50 bg-muted/20 px-3 py-2 text-[10px] leading-relaxed text-muted-foreground"
        >
          This records an <strong className="text-foreground">adjusting trade</strong>{" "}
          in your history (a BUY or SELL for the difference) — it does not rewrite
          past transactions. Your average cost is recalculated from your full
          trade history.
        </p>

        {/* ── Action buttons ───────────────────────────────────────────────── */}
        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => void handleConfirm()}
            // Disabled on a 0/invalid delta or invalid price — the label above
            // tells the user exactly what will be recorded when enabled.
            disabled={!canSubmit || isSubmitting}
          >
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
