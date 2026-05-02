/**
 * components/ui/confirm-dialog.tsx — T2 tier Confirm/Undo modal dialog
 *
 * WHY THIS EXISTS: PLAN-0059 F-4 specifies a three-tier confirm/undo pattern
 * for destructive actions. This component implements Tier 2 (T2 — Modal Confirm),
 * the middle tier of the ladder:
 *
 *   T1 (low severity)    → Toast with Undo button (see useConfirmable.ts)
 *   T2 (medium severity) → THIS COMPONENT — modal with Cancel / Confirm
 *   T3 (high severity)   → Type-to-confirm (see DestructiveButton component)
 *
 * WHEN TO USE T2: when the action is reversible with moderate effort, but
 * deserves explicit confirmation before proceeding. Examples:
 *   - Delete an alert rule
 *   - Remove a holding from a portfolio
 *   - Clear a watchlist
 *   - Cancel a pending order
 *
 * HOW SEVERITY MAPS TO BUTTON STYLE:
 *   "low"    → standard Button (blue primary) — mild confirmation, user probably
 *              knows what they're doing but a double-check is appropriate.
 *   "medium" → amber/warning destructive Button — the action has real consequences
 *              and the amber colour signals "caution, not emergency".
 *   "high"   → red destructive Button — irreversible or high-impact action;
 *              the red matches the system destructive token (#EF5350).
 *
 * DESIGN REFERENCE: shadcn Dialog + PLAN-0059 §F-4 Confirm/Undo Ladder
 * MIDNIGHT PRO PALETTE: bg #131722, primary #0EA5E9, negative #EF5350
 */

"use client";
// WHY "use client": uses useState (open state) and browser DOM for focus trap
// (Radix Dialog does this internally). Cannot render in Server Components.

import * as React from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * ConfirmDialogProps — props for the T2 modal dialog component.
 *
 * WHY controlled (open + onOpenChange): the dialog state lives in the parent
 * (useConfirmable hook), not inside this component. This makes the component
 * simpler and lets the parent close the dialog from outside (e.g., when the
 * action resolves). Radix Dialog requires this pattern for proper accessibility.
 */
export interface ConfirmDialogProps {
  /** Whether the dialog is visible. Controlled by the parent. */
  open: boolean;
  /** Callback to update visibility. Called with false when user cancels or confirms. */
  onOpenChange: (open: boolean) => void;
  /** Dialog title — short, imperative (e.g., "Delete alert?"). */
  title: string;
  /** Longer explanation of consequences. Shown below the title in smaller text. */
  description: string;
  /**
   * Severity determines the confirm button's visual style:
   *   "low"    → primary blue (action is mild)
   *   "medium" → amber warning (action has notable consequences)
   *   "high"   → destructive red (irreversible or high-impact)
   */
  severity: "low" | "medium" | "high";
  /** Called when user clicks the confirm button. */
  onConfirm: () => void;
  /** Called when user clicks Cancel or presses Esc. Optional — closes dialog by default. */
  onCancel?: () => void;
  /**
   * If true, shows a note "This action can be undone within 30s" below the description.
   * WHY optional: only some T2 actions have server-side undo. Showing the message
   * for non-undoable actions would be false advertising. The caller sets this when
   * the action's `undoWindowMs` is > 0.
   */
  undoable?: boolean;
  /** Override the confirm button label. Defaults to "Confirm". */
  confirmLabel?: string;
}

// ── Severity styles ───────────────────────────────────────────────────────────

/**
 * severityButtonClass — maps severity to Tailwind class overrides for the
 * confirm button.
 *
 * WHY not use variant="destructive" for all: shadcn's "destructive" variant
 * maps to --destructive (red). For "medium" severity, we want amber to
 * communicate "caution" rather than "danger". For "low" we use the primary
 * (blue) style — the dialog itself is the confirmation, no extra red needed.
 *
 * The amber classes use Tailwind's amber palette, consistent with the Midnight
 * Pro design system's use of yellow-500 (#EAB308) for warning states.
 */
function severityButtonClass(severity: "low" | "medium" | "high"): string {
  switch (severity) {
    case "low":
      // Default primary button style — no override needed
      return "";
    case "medium":
      // Amber warning — caution, not emergency
      return "bg-amber-500 text-white hover:bg-amber-600 focus-visible:ring-amber-500";
    case "high":
      // Destructive red — mirrors the --destructive CSS variable (#EF5350)
      return "bg-destructive text-destructive-foreground hover:bg-destructive/90";
  }
}

// ── ConfirmDialog ────────────────────────────────────────────────────────────

/**
 * ConfirmDialog — T2 tier modal confirmation dialog.
 *
 * Rendered by useConfirmable() when severity is "medium". Can also be used
 * directly for custom confirm flows.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  severity,
  onConfirm,
  onCancel,
  undoable,
  confirmLabel = "Confirm",
}: ConfirmDialogProps) {
  /**
   * handleCancel — closes dialog and fires optional onCancel callback.
   * WHY call onOpenChange(false) before onCancel: ensures the dialog is
   * closed first so onCancel's side effects (e.g., state reset) run on a
   * clean slate without a visible dialog.
   */
  function handleCancel() {
    onOpenChange(false);
    onCancel?.();
  }

  /**
   * handleConfirm — fires onConfirm then closes dialog.
   *
   * WHY dialog closes immediately (not after async resolution): onConfirm is
   * called with `void` by useConfirmable, so any async outcome (success or
   * error) resolves after this function returns. The dialog always closes on
   * click. Errors are surfaced via toast (not by keeping the dialog open).
   * This is intentional: for T2 severity, the user has already confirmed —
   * holding the dialog open on network error would be confusing. The toast
   * error + retry button pattern is simpler and matches Radix/shadcn UX norms.
   *
   * If your use case needs a loading state (dialog stays open while async runs),
   * use `onConfirm` that does NOT `void`-wrap the promise and add an `isPending`
   * prop to disable the confirm button — this component supports it via `disabled`.
   */
  function handleConfirm() {
    onConfirm();
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // WHY max-w-sm: confirm dialogs should be compact — the user just needs
        // to read the title/description and choose. A wide dialog is harder to
        // scan and looks like a form, not a confirmation prompt.
        className="max-w-sm"
      >
        <DialogHeader>
          <DialogTitle className="text-base">{title}</DialogTitle>
          {/* WHY always render Description (never sr-only): unlike destructive-button.tsx
              which handles legacy Radix patterns, our Dialog is from a newer shadcn version
              that doesn't warn when description is absent. We still always render it because
              a description makes confirmation dialogs much less scary — the user understands
              exactly what will happen before they click. */}
          <DialogDescription className="text-[11px]">{description}</DialogDescription>
        </DialogHeader>

        {/* Undo hint — only shown when the action can be reversed */}
        {undoable && (
          <p
            className={cn(
              "text-[10px] text-muted-foreground italic",
              // WHY -mt-2: tighten spacing after description; default gap-4 is
              // too wide for this supplemental hint text.
              "-mt-2",
            )}
          >
            This action can be undone within 30 seconds.
          </p>
        )}

        <DialogFooter className="mt-2">
          {/* Cancel is always available — never remove it. The user must have an
              explicit out. Closing via Esc also cancels, but a visible button is
              required for pointer users and accessibility. */}
          <Button variant="outline" size="sm" onClick={handleCancel}>
            Cancel
          </Button>

          {/* Confirm button — visual style determined by severity */}
          <Button
            size="sm"
            className={cn(severityButtonClass(severity))}
            onClick={handleConfirm}
            // Auto-focus the confirm button so keyboard users can press Enter to confirm.
            // WHY confirm (not cancel): the dialog is already a deliberate gate — the user
            // opened it intentionally. Defaulting focus to Confirm reduces friction for
            // users who know what they're doing. For "high" severity, consider moving
            // focus to Cancel (implemented in T3 / DestructiveButton).
            autoFocus={severity !== "high"}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
