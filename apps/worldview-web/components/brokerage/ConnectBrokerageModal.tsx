/**
 * ConnectBrokerageModal — Dialog to initiate SnapTrade brokerage OAuth flow
 *
 * WHY THIS EXISTS: Connecting a brokerage requires explicit user consent (ToS)
 * before we call SnapTrade's API. A modal enforces this as a deliberate action
 * rather than an accidental click, and clearly communicates what will happen
 * (redirect to SnapTrade portal → broker selection → OAuth → callback).
 *
 * FLOW:
 *   1. User opens modal → reads ToS and ticks checkbox
 *   2. User clicks "Connect" → POST /api/v1/brokerage-connections
 *   3. S9 creates pending connection, returns { connection_id, redirect_uri }
 *   4. This component sets window.location.href = redirect_uri (SnapTrade portal)
 *   5. After OAuth, SnapTrade redirects to /portfolio/brokerage/callback
 *
 * WHY window.location.href (not router.push): The redirect_uri points to an
 * external SnapTrade domain. Next.js router.push() only works for internal routes.
 * window.location.href is a full browser navigation — the correct mechanism for
 * cross-origin redirects.
 *
 * WHO USES IT: app/(app)/portfolio/page.tsx — Brokerages tab header button
 * DATA SOURCE: S9 POST /api/v1/brokerage-connections
 * DESIGN REFERENCE: PRD-0022 §6.6
 */

"use client";
// WHY "use client": uses mutation hooks (TanStack Query), useState for checkbox,
// and window.location.href for redirect — all require client-side runtime.

import { useState } from "react";
import { Link2, Loader2, AlertCircle } from "lucide-react";
import { useInitiateBrokerageConnection } from "@/hooks/use-brokerage-connections";

// ── shadcn/ui imports ─────────────────────────────────────────────────────────
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";

// ── Props ─────────────────────────────────────────────────────────────────────

interface ConnectBrokerageModalProps {
  /** The portfolio that will receive synced transactions */
  portfolioId: string;
  /** Portfolio display name (shown in the modal so user knows which portfolio) */
  portfolioName?: string;
  /** Controlled open state from parent */
  open: boolean;
  /** Called when the dialog should open or close */
  onOpenChange: (open: boolean) => void;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function ConnectBrokerageModal({
  portfolioId,
  portfolioName,
  open,
  onOpenChange,
}: ConnectBrokerageModalProps) {
  // WHY local checkbox state: ToS consent is ephemeral UI state that should reset
  // each time the modal opens. Using local state (not a form library) keeps this
  // component simple and avoids form submission complexity for a single checkbox.
  const [tosAccepted, setTosAccepted] = useState(false);

  const { mutate: initiate, isPending, error, reset } = useInitiateBrokerageConnection();

  /**
   * handleConnect — trigger the brokerage connection initiation
   *
   * WHY void cast on mutate: the mutation fires-and-forgets; we handle the
   * result in the callbacks. TypeScript requires void for the fire-and-forget
   * pattern when we don't await the return value.
   */
  function handleConnect() {
    initiate(portfolioId, {
      onSuccess: (data) => {
        // WHY window.location.href: redirect_uri points to external SnapTrade domain.
        // Next.js router only handles internal routes; this requires full navigation.
        window.location.href = data.redirect_uri;
        // Note: modal will unmount during navigation — no need to call onOpenChange(false)
      },
    });
  }

  /**
   * handleOpenChange — reset state when dialog closes
   *
   * WHY reset mutation: if the user closes the modal after an error, the error
   * state should clear so the next open shows a fresh form (not a stale error).
   */
  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      // Reset checkbox and mutation state for next open
      setTosAccepted(false);
      reset();
    }
    onOpenChange(nextOpen);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        // WHY max-w-md: the modal content is text-heavy (ToS notice, broker list).
        // md width gives enough horizontal space without becoming full-screen.
        className="max-w-md"
      >
        {/* ── Header ───────────────────────────────────────────────────────── */}
        <DialogHeader>
          <div className="flex items-center gap-2">
            {/* Link icon communicates "connecting two things" */}
            <Link2 className="h-4 w-4 text-primary" aria-hidden="true" />
            <DialogTitle className="text-base">Connect Brokerage Account</DialogTitle>
          </div>
          <DialogDescription className="text-sm text-muted-foreground">
            Import your transaction history automatically. SnapTrade connects to
            25+ brokerages including IBKR, Robinhood, Fidelity, and Schwab.
          </DialogDescription>
        </DialogHeader>

        {/* ── Body ─────────────────────────────────────────────────────────── */}
        <div className="space-y-4 py-2">

          {/* Portfolio badge — tells the user which portfolio gets the transactions */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Importing to:</span>
            <Badge variant="secondary" className="font-mono text-xs tabular-nums">
              {portfolioName ?? "Selected Portfolio"}
            </Badge>
          </div>

          {/* ToS notice — regulatory requirement: explicit consent before SnapTrade API call */}
          <p className="rounded-md border border-border/50 bg-muted/30 px-3 py-2.5 text-xs text-muted-foreground">
            By connecting, you agree to{" "}
            {/* WHY target="_blank" rel="noopener noreferrer": opens in new tab so the
                user doesn't lose their place in the app. noopener prevents the opened
                page from gaining access to the opener's window object (security). */}
            <a
              href="https://snaptrade.com/tos"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-2 hover:text-primary/80"
            >
              SnapTrade&apos;s End User Terms of Service
            </a>
            .
          </p>

          {/* Consent checkbox — must be ticked before Connect button activates */}
          <div className="flex items-start gap-3">
            <Checkbox
              id="tos-accept"
              checked={tosAccepted}
              onCheckedChange={(checked: boolean | "indeterminate") =>
                // WHY === true: onCheckedChange receives boolean | "indeterminate".
                // "indeterminate" means partially checked (used for parent checkboxes
                // in multi-select trees). For a simple consent checkbox it's always
                // true or false — we treat "indeterminate" as false for safety.
                setTosAccepted(checked === true)
              }
              // WHY mt-0.5: vertically aligns checkbox center with first line of label text
              className="mt-0.5 shrink-0"
            />
            <label
              htmlFor="tos-accept"
              // WHY cursor-pointer: makes the entire label text clickable to toggle checkbox
              className="cursor-pointer text-xs leading-relaxed text-foreground"
            >
              I agree to SnapTrade&apos;s Terms of Service and authorize
              read-only access to my transaction history
            </label>
          </div>

          {/* Error state — shown only when the mutation fails */}
          {error && (
            <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2">
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />
              <p className="text-xs text-destructive">
                {/* WHY error.message fallback: GatewayError always has a message;
                    unknown errors may not. The fallback is a safe generic message. */}
                {error instanceof Error
                  ? error.message
                  : "Failed to initiate connection. Please try again."}
              </p>
            </div>
          )}
        </div>

        {/* ── Footer actions ────────────────────────────────────────────────── */}
        <DialogFooter className="gap-2 sm:gap-0">
          {/* Cancel — closes without any API call */}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => handleOpenChange(false)}
            disabled={isPending}
          >
            Cancel
          </Button>

          {/* Connect — disabled until ToS accepted; shows spinner while pending */}
          <Button
            size="sm"
            // WHY disabled when !tosAccepted: legal/compliance requirement.
            // SnapTrade requires documented consent before we initiate the connection.
            disabled={!tosAccepted || isPending}
            onClick={handleConnect}
            className="gap-1.5"
          >
            {isPending ? (
              // Spinner while waiting for S9 to create the connection
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                Connecting…
              </>
            ) : (
              <>
                <Link2 className="h-3.5 w-3.5" aria-hidden="true" />
                Connect
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
