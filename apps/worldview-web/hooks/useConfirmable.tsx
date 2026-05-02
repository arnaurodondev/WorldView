/**
 * hooks/useConfirmable.ts — Three-Tier Confirm/Undo Ladder (PLAN-0059 F-4)
 *
 * ──────────────────────────────────────────────────────────────────────────────
 * CONFIRM/UNDO THREE-TIER LADDER
 *
 * This hook implements a graduated confirmation pattern for destructive actions.
 * The tier is selected automatically based on config.severity:
 *
 * T1 — Toast Undo (severity: "low")
 *   Show a toast: "[label] [Undo]". User has undoWindowMs seconds to click Undo.
 *   After undoWindowMs, the action is considered committed and executes.
 *   Good for: soft-deletes, preference changes, watchlist removals, dismiss.
 *   WHY toast-first (not execute-first): for low-severity actions we optimistically
 *   assume the user wants to proceed. The Undo button gives them a safety net
 *   without blocking the workflow with a modal. This matches Gmail's "Message
 *   sent [Undo]" and Linear's "Issue moved [Undo]" patterns.
 *
 * T2 — Modal Confirm (severity: "medium")
 *   Show a shadcn Dialog with title, description, Cancel, and Confirm buttons.
 *   User must explicitly confirm before the action executes.
 *   Good for: deleting alerts, clearing watchlists, removing portfolio entries.
 *   WHY modal: medium-severity actions have notable consequences that the user
 *   should consciously acknowledge. A modal is blocking — it demands attention.
 *
 * T3 — Type-to-Confirm (severity: "high")
 *   Return instructions to use <DestructiveButton tier="t3"> directly.
 *   The T3 pattern requires the user to type a specific phrase to unlock the
 *   action button, preventing accidental clicks on the most dangerous operations.
 *   Good for: account deletion, clearing all portfolio history, bulk data wipes.
 *   WHY not implemented here: T3 is inherently tied to the trigger element
 *   (the type-to-confirm input and the confirm button are tightly coupled).
 *   useConfirmable returning a generic ConfirmDialog for T3 would require the
 *   caller to add an input, which defeats the purpose of the hook. Instead,
 *   T3 callers use <DestructiveButton tier="t3"> which bundles the whole flow.
 *
 * USAGE:
 *   const { execute, ConfirmDialog, isPending } = useConfirmable({
 *     action: async () => { await api.deleteAlert(id); },
 *     severity: "medium",
 *     label: "Delete Alert",
 *     description: "This will permanently delete the alert and cannot be undone.",
 *   });
 *
 *   return (
 *     <>
 *       <button onClick={execute} disabled={isPending}>Delete</button>
 *       <ConfirmDialog />   {/* renders T2 modal when execute() is called * /}
 *     </>
 *   );
 *
 * For T1 (low severity) the ConfirmDialog component renders nothing — the
 * toast IS the UI. Just call execute() and render <ConfirmDialog /> for
 * completeness (no-op in T1).
 *
 * For T3 (high severity) execute() logs a warning and is a no-op. Use
 * <DestructiveButton tier="t3"> instead.
 * ──────────────────────────────────────────────────────────────────────────────
 */

"use client";
// WHY "use client": uses useState (dialog open state, isPending), useRef
// (timer ref for T1 undo window), useCallback. Cannot be used in Server Components.

import * as React from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UseConfirmableConfig {
  /** The async operation to execute after confirmation. */
  action: () => Promise<void>;
  /**
   * Severity determines which tier of the ladder is used:
   *   "low"    → T1 Toast Undo
   *   "medium" → T2 Modal Confirm
   *   "high"   → T3 Type-to-confirm (see DestructiveButton, execute() is a no-op)
   */
  severity: "low" | "medium" | "high";
  /** Short label for the action. Used as the toast message (T1) or dialog title (T2). */
  label: string;
  /**
   * Optional longer description. Used as:
   *   T1: toast description line (optional detail)
   *   T2: dialog description paragraph (recommended)
   *   T3: not used (type-to-confirm has its own description in DestructiveButton)
   */
  description?: string;
  /**
   * T1 only: milliseconds before the action is committed after execute() is called.
   * Defaults to 5000ms (5 seconds). The Undo toast stays visible during this window.
   *
   * WHY 5 seconds default: short enough to not feel like a delay, long enough
   * for a user who immediately regrets the action to click Undo. Gmail uses 5s.
   * For potentially impactful but low-severity actions (e.g., "Archive all"),
   * callers may pass a longer window (e.g., 10000ms).
   */
  undoWindowMs?: number;
}

export interface UseConfirmableReturn {
  /**
   * execute — trigger the tier-appropriate confirmation flow.
   *   T1: shows a toast with Undo; starts the undo window timer
   *   T2: opens the confirm dialog
   *   T3: logs a console warning (use DestructiveButton tier="t3" instead)
   */
  execute: () => void;
  /**
   * ConfirmDialog — React component to render in JSX. Required for T2 to show
   * the modal; for T1 and T3 this renders null (no-op).
   *
   * WHY a component (not a portal): rendering via JSX gives the component tree
   * control over z-index stacking context. A portal that bypasses React's tree
   * would fight with other modals (e.g., a ConfirmDialog inside a sheet would
   * appear below the sheet overlay without special z-index handling). JSX render
   * is simpler and correct for 95% of use cases.
   */
  ConfirmDialog: React.FC;
  /**
   * isPending — true while the action is executing (async). Use to disable
   * the trigger button and show a loading indicator.
   */
  isPending: boolean;
}

// ── Hook implementation ───────────────────────────────────────────────────────

/**
 * useConfirmable — graduated confirm/undo hook.
 *
 * See file-level comment for the full three-tier ladder documentation.
 */
export function useConfirmable(config: UseConfirmableConfig): UseConfirmableReturn {
  const { action, severity, label, description, undoWindowMs = 5000 } = config;

  // T2: controls whether the confirm dialog is open
  const [dialogOpen, setDialogOpen] = React.useState(false);

  // Shared: true while the async action is executing (between confirm and resolution)
  const [isPending, setIsPending] = React.useState(false);

  // T1: ref to the pending setTimeout so we can cancel it on Undo
  // WHY useRef (not useState): the timer ID doesn't need to trigger a re-render
  // when it changes. useRef is the correct tool for imperative side-effect state.
  const undoTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup: cancel any pending T1 timer when the component unmounts
  React.useEffect(() => {
    return () => {
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    };
  }, []);

  /**
   * runAction — shared action execution with isPending tracking and error handling.
   *
   * WHY separate helper: both T1 (after timer) and T2 (after confirm) call this
   * with the same error-recovery logic. Centralising avoids duplication.
   */
  const runAction = React.useCallback(async () => {
    if (isPending) return; // Guard: don't start a second execution while first is running
    setIsPending(true);
    try {
      await action();
    } catch (err) {
      // WHY reset isPending on error: the trigger button must re-enable so the
      // user can retry. Leaving isPending=true permanently locks the UI.
      // eslint-disable-next-line no-console
      console.error("[useConfirmable] action threw:", err);
    } finally {
      setIsPending(false);
    }
  }, [action, isPending]);

  /**
   * execute — tier router. Picks T1/T2/T3 based on severity.
   */
  const execute = React.useCallback(() => {
    // Guard: ignore if already pending (no double-execution)
    if (isPending) return;

    if (severity === "low") {
      // ── T1: Toast Undo ──────────────────────────────────────────────────────
      // Show the toast immediately with an Undo action. Start the undo window
      // timer. If the user clicks Undo within undoWindowMs, cancel the timer and
      // the action never runs. If the timer fires, run the action.
      //
      // WHY we don't run the action immediately and undo it: for many low-severity
      // actions (e.g., "Remove from watchlist"), the server mutation hasn't happened
      // yet. The "undo" is just cancelling before we ever sent the request.
      // Optimistic UI (run-then-undo) adds rollback complexity; deferred execution
      // is simpler and sufficient for low-risk operations.

      // Cancel any previous pending timer (user called execute() twice quickly)
      if (undoTimerRef.current) {
        clearTimeout(undoTimerRef.current);
        undoTimerRef.current = null;
      }

      undoTimerRef.current = setTimeout(() => {
        undoTimerRef.current = null;
        void runAction();
      }, undoWindowMs);

      // WHY use sonner's toast (not custom): sonner supports the `action` option
      // which adds a button to the toast. We use this for the Undo button.
      toast(label, {
        description: description ?? "Click Undo to cancel.",
        duration: undoWindowMs,
        action: {
          label: "Undo",
          onClick: () => {
            // Cancel the pending action timer — action never runs
            if (undoTimerRef.current) {
              clearTimeout(undoTimerRef.current);
              undoTimerRef.current = null;
            }
          },
        },
      });
    } else if (severity === "medium") {
      // ── T2: Modal Confirm ───────────────────────────────────────────────────
      // Simply open the dialog. The dialog's Confirm button calls runAction.
      setDialogOpen(true);
    } else {
      // ── T3: High severity — direct users to DestructiveButton ───────────────
      // WHY log (not throw): throwing would crash the component that called execute().
      // A console warning is visible during development without breaking the UI.
      // eslint-disable-next-line no-console
      console.warn(
        "[useConfirmable] severity='high' detected. " +
          "For type-to-confirm (T3), use <DestructiveButton tier='t3'> directly. " +
          "useConfirmable does not implement T3 because the type-input and confirm " +
          "button must be tightly coupled in the same UI element.",
      );
    }
  }, [isPending, severity, label, description, undoWindowMs, runAction]);

  /**
   * BoundConfirmDialog — the ConfirmDialog component with state bound from
   * this hook closure.
   *
   * WHY memoize the component: we create a new React.FC each render; without
   * memo the parent re-renders every time any hook state changes, causing the
   * dialog to flicker. useMemo stabilises the component reference.
   *
   * WHY a function component (not just JSX): the caller places <ConfirmDialog />
   * anywhere in their JSX tree. Returning a component gives them flexibility on
   * positioning (e.g., inside a table row vs. at the page root).
   *
   * WHY render null for T1/T3: T1 uses toast (no JSX component); T3 should not
   * be used via this hook. Rendering null is the clearest signal.
   */
  const BoundConfirmDialog: React.FC = React.useMemo(() => {
    if (severity !== "medium") {
      // T1 or T3: no dialog component needed
      return function NoOpDialog() {
        return null;
      };
    }

    // T2: return the ConfirmDialog wired to this hook's state
    return function T2Dialog() {
      return (
        <ConfirmDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          title={label}
          description={description ?? "Are you sure you want to proceed?"}
          severity={severity}
          onConfirm={() => void runAction()}
          // WHY onConfirm calls runAction (not action directly): runAction handles
          // isPending state tracking and error recovery. Calling action() directly
          // would bypass those guards.
        />
      );
    };
    // WHY include dialogOpen: the memo must re-run when dialogOpen changes so
    // the rendered dialog sees the updated open state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [severity, dialogOpen, label, description, runAction]);

  return {
    execute,
    ConfirmDialog: BoundConfirmDialog,
    isPending,
  };
}
