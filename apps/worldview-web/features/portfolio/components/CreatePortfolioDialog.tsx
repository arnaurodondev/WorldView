"use client";

/**
 * features/portfolio/components/CreatePortfolioDialog.tsx
 *
 * Modal for creating a new manually-managed portfolio.
 *
 * WHY a separate component (extracted from portfolio/page.tsx in PLAN-0059
 * Wave E-2): isolating dialog state (name input, loading, error) keeps the
 * parent page component lean and the dialog independently testable. The
 * dialog has its own mini state machine: idle → submitting → success/error.
 *
 * DATA FLOW:
 *   1. User types a portfolio name
 *   2. On submit → calls gateway.createPortfolio(name)
 *   3. On success → calls onSuccess(newPortfolio) so the page can select it
 *   4. Parent invalidates ["portfolios"] query → TanStack Query refetches the list
 *
 * WHY onOpenChange instead of onClose: shadcn Dialog uses onOpenChange(false)
 * to signal close — from both the X button and the overlay click. This pattern
 * is idiomatic for shadcn dialogs throughout this app.
 */

import { useState, useCallback } from "react";
import { createGateway } from "@/lib/gateway";
import type { Portfolio } from "@/types/api";
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

export interface CreatePortfolioDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: (portfolio: Portfolio) => void;
  accessToken: string | null | undefined;
}

export function CreatePortfolioDialog({
  open,
  onOpenChange,
  onSuccess,
  accessToken,
}: CreatePortfolioDialogProps) {
  // Local form state — only lives while the dialog is mounted.
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // handleSubmit — async handler that calls S9 POST /v1/portfolios.
  const handleSubmit = useCallback(async () => {
    // WHY trim + guard: whitespace-only names would pass server validation
    // but look wrong in the UI. Catch it client-side for instant feedback
    // (no network round-trip).
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Portfolio name is required.");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      // createPortfolio sends POST /v1/portfolios to S9, which injects
      // owner_user_id from the JWT claim before forwarding to S1. We only
      // send name + currency.
      const newPortfolio = await createGateway(accessToken).createPortfolio(
        trimmedName,
        currency,
      );

      // Reset form state before closing so the dialog is clean on next open.
      setName("");
      setCurrency("USD");
      setError(null);

      // Notify parent: it will invalidate ["portfolios"] and select the new portfolio.
      onSuccess(newPortfolio);
    } catch (err) {
      // WHY string cast: GatewayError.message is a string, but unknown
      // errors may not be. Extract the message or fall back to a generic
      // string rather than crashing.
      const message =
        err instanceof Error ? err.message : "Failed to create portfolio.";
      setError(message);
    } finally {
      // Always clear loading state, even if the request failed.
      setIsSubmitting(false);
    }
  }, [name, currency, accessToken, onSuccess]);

  // handleOpenChange — reset form when dialog is closed externally (X or overlay).
  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        // Don't reset if a submission is in progress — user may have hit
        // overlay by accident.
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
        // WHY max-w-sm: a portfolio creation form only has 2 fields — it
        // doesn't need a wide modal. Narrow dialogs feel more intentional
        // than wide ones.
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
              // WHY onKeyDown: allow pressing Enter to submit (standard form
              // UX). Avoid wrapping in a <form> element since we're inside a
              // Dialog with its own focus management — nested form elements
              // cause accessibility issues.
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isSubmitting) void handleSubmit();
              }}
              disabled={isSubmitting}
              // WHY autoFocus: the modal just opened and the name field is
              // the only required input. Focus it immediately so the user
              // can start typing.
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
              // WHY toUpperCase(): S1 validates that currency is a 3-letter
              // uppercase code. Convert on change so the user can type
              // lowercase without errors.
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
            // WHY font-mono: all action text in terminal UI uses monospace
            // for consistency.
            className="text-[11px] font-mono"
          >
            {isSubmitting ? "Creating…" : "Create Portfolio"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
