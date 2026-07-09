/**
 * lib/portfolio/adjusting-transaction.ts — PLAN-0122 W-D (T-A-D-01).
 *
 * WHY THIS EXISTS (the honest-ledger mechanism, PRD-0122 §6.4 / §1.2.4):
 *   Portfolio holdings are DERIVED from the transaction ledger — the recompute
 *   consumer folds every BUY/SELL into the current quantity + average cost. There
 *   is NO `PATCH /transactions` and NO in-place holding mutation on the backend
 *   (S1 exposes only `POST /transactions` + read GETs). Therefore "editing" a
 *   position can only ever mean posting a NEW, adjusting trade that reconciles the
 *   ledger to the user's desired target quantity:
 *
 *     - want MORE shares than you hold  → record a BUY  of the difference
 *     - want FEWER shares than you hold → record a SELL of the difference
 *     - want exactly what you hold      → nothing to record (no-op)
 *
 *   This keeps the Transactions tab TRUTHFUL: an edit shows up as a real,
 *   visible BUY or SELL — never a silent rewrite of past history or a hidden
 *   average-cost overwrite. The average cost is always recomputed from the full
 *   trade history by the backend, not typed in directly.
 *
 * WHY A PURE FUNCTION (no I/O): the delta maths is the single load-bearing rule
 *   behind EditPositionDialog. Isolating it here makes it exhaustively
 *   unit-testable (positive / negative / zero / full-exit / invalid) without
 *   mounting a dialog, and gives the dialog one obvious place to derive both the
 *   request body (`trade_side` + `quantity`) and the submit-button label.
 */

/** The direction of the adjusting trade, matching S1's `trade_side` field. */
export type AdjustmentSide = "BUY" | "SELL";

/**
 * The adjusting trade that reconciles a holding from its current derived
 * quantity to the user's target quantity. `null` means "no trade needed"
 * (the target already equals what the user holds) — the caller disables Submit.
 */
export interface Adjustment {
  side: AdjustmentSide;
  /** Always > 0 (S1 validates `quantity` as strictly positive). */
  quantity: number;
}

/**
 * computeAdjustment — derive the honest adjusting trade from (current, target).
 *
 * @param currentQty  The position's current DERIVED quantity (from holdings).
 * @param targetQty   The quantity the user wants to hold after the edit. `0`
 *                    means "close the position entirely" → a full SELL.
 * @returns The `{ side, quantity }` delta trade, or `null` when nothing needs
 *          to be recorded (delta === 0).
 * @throws  RangeError when the target is negative or either input is not a
 *          finite number — an invalid target the caller must surface as an
 *          inline validation error rather than silently posting garbage.
 *
 * WHY throw (not return null) on invalid input: a `null` return is a MEANINGFUL,
 *   expected outcome (delta === 0 → Submit disabled). Overloading it to also mean
 *   "bad input" would hide validation bugs. A thrown RangeError forces the caller
 *   to validate the target before calling, keeping the two failure modes distinct.
 */
export function computeAdjustment(
  currentQty: number,
  targetQty: number,
): Adjustment | null {
  // Guard the inputs first — NaN/Infinity or a negative target can never map to
  // a valid trade. The dialog validates the field, but this keeps the helper
  // honest for any caller (and documents the contract for tests).
  if (!Number.isFinite(currentQty) || !Number.isFinite(targetQty)) {
    throw new RangeError("computeAdjustment: quantities must be finite numbers");
  }
  if (targetQty < 0) {
    throw new RangeError("computeAdjustment: target quantity cannot be negative");
  }

  const delta = targetQty - currentQty;

  // No change → nothing to record. The dialog reads this null to disable Submit.
  if (delta === 0) return null;

  // delta > 0 → the user wants MORE shares → BUY the difference.
  // delta < 0 → the user wants FEWER shares → SELL the absolute difference
  //             (targetQty === 0 falls here: a full SELL of the whole position).
  return delta > 0
    ? { side: "BUY", quantity: delta }
    : { side: "SELL", quantity: Math.abs(delta) };
}
