/**
 * features/portfolio/components/DeletePortfolioDialog.tsx — F-013 archive confirm.
 *
 * WHY THIS EXISTS (PLAN-0059 E-2 follow-up): the inline 50-LOC Dialog block
 * sat at the page root. Lifting it here makes the destructive-action shape
 * a self-contained, props-driven component (open + portfolio name + the
 * mutation handle). The page no longer needs to import shadcn Dialog
 * primitives directly.
 *
 * BEHAVIOR PARITY: identical "Holdings will be unaffected" reassurance,
 * identical pending-state interlock (cannot dismiss while delete is in
 * flight), identical destructive-button styling.
 */

"use client";
// WHY "use client": shadcn Dialog uses Radix portals + focus traps that are
// browser-only.

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { Portfolio } from "@/types/api";

interface DeletePortfolioDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Portfolio being archived — drives the confirmation message. */
  activePortfolio: Portfolio;
  /** Portfolio id passed to the mutation when the user confirms. */
  activePortfolioId: string;
  /** True while the archive mutation is in flight (disables both buttons). */
  isPending: boolean;
  /** True when the last mutation attempt failed (renders the retry hint). */
  isError: boolean;
  /** Trigger the archive mutation — usually `mutation.mutate(portfolioId)`. */
  onConfirm: (portfolioId: string) => void;
}

export function DeletePortfolioDialog({
  open,
  onOpenChange,
  activePortfolio,
  activePortfolioId,
  isPending,
  isError,
  onConfirm,
}: DeletePortfolioDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        // Block the user from dismissing the dialog while a delete is in
        // flight — otherwise they could close it, navigate away, and then
        // get a stale invalidation when the request returns.
        if (!isPending) onOpenChange(o);
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
              delete) and existing holdings rows remain attached but no
              longer surface in queries. */}
          Delete portfolio &quot;{activePortfolio.name}&quot;? Holdings will be
          unaffected.
        </p>
        {isError && (
          <p className="text-[11px] text-negative font-mono">
            Failed to delete. Try again or check the server logs.
          </p>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => onConfirm(activePortfolioId)}
            disabled={isPending}
          >
            {isPending ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
