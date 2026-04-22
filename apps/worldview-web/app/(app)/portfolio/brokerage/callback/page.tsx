/**
 * app/(app)/portfolio/brokerage/callback/page.tsx — SnapTrade OAuth callback page
 *
 * WHY THIS EXISTS: After the user selects their broker and authorises access on
 * the SnapTrade portal, SnapTrade redirects them back to this URL with four
 * query parameters: connectionId, authorizationId, userId, sessionId.
 *
 * This page completes the OAuth flow by calling S9's GET callback endpoint which
 * activates the connection (status changes from "pending" → "active").
 *
 * FLOW:
 *   SnapTrade portal redirects to:
 *   /portfolio/brokerage/callback?connectionId=xxx&authorizationId=yyy&userId=zzz&sessionId=www
 *   ↓
 *   This page reads the params and calls S9 GET /api/v1/brokerage-connections/{id}/callback
 *   ↓
 *   Success: shows confirmation + "Go to Portfolio" button
 *   Error:   shows error message + "Try Again" button
 *
 * WHY connectionId comes from the URL (not SnapTrade): SnapTrade only returns
 * authorizationId, userId, sessionId. The connectionId was pre-created by S9
 * when we called POST /brokerage-connections and embedded in the redirect_uri
 * that was passed to SnapTrade. SnapTrade appends its own params to that URI
 * and redirects back, so our connectionId arrives alongside SnapTrade's params.
 *
 * WHO USES IT: SnapTrade portal redirect after OAuth completion
 * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/callback
 * DESIGN REFERENCE: PRD-0022 §6.6
 */

"use client";
// WHY "use client": useSearchParams() is a browser-only hook (reads URL query
// params from window.location). useEffect for the activation call and
// useRouter for navigation both require client-side runtime.

import { useEffect, useState, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";

// ── State machine ─────────────────────────────────────────────────────────────

/** WHY union type: explicit state machine prevents impossible UI states.
 *  "idle" only exists before the effect fires (< 50ms on fast connections). */
type ActivationState = "idle" | "loading" | "success" | "error";

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BrokerageCallbackPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { accessToken } = useAuth();

  // Read all four required params from the URL
  // WHY ?? "": useSearchParams().get() returns null for missing params;
  // empty string allows the type to be string (easier to work with than string | null)
  const connectionId = searchParams.get("connectionId") ?? "";
  const authorizationId = searchParams.get("authorizationId") ?? "";
  const userId = searchParams.get("userId") ?? "";
  const sessionId = searchParams.get("sessionId") ?? "";

  const [state, setState] = useState<ActivationState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // WHY hasActivated ref: React 18 Strict Mode runs effects twice in development.
  // Using a ref (not state) prevents a second activation API call which would
  // fail (the connection is already active after the first call).
  const hasActivated = useRef(false);

  useEffect(() => {
    // Guard: don't activate if we already did (Strict Mode double-fire protection)
    if (hasActivated.current) return;

    // Guard: if params are missing, show an error immediately without calling S9
    if (!connectionId || !authorizationId || !userId || !sessionId) {
      setState("error");
      setErrorMessage(
        "Missing required callback parameters. Please try connecting your brokerage again.",
      );
      return;
    }

    // Guard: wait for the auth token (may be null on very first render)
    if (!accessToken) {
      // WHY return without setting error: accessToken is loaded async.
      // The effect will re-run when accessToken resolves (it's in the deps array).
      return;
    }

    // Mark as activated BEFORE the async call to prevent double-fire
    hasActivated.current = true;
    setState("loading");

    // Call S9 to activate the connection server-side
    createGateway(accessToken)
      .activateBrokerageConnection(connectionId, {
        authorizationId,
        userId,
        sessionId,
      })
      .then(() => {
        setState("success");
      })
      .catch((err: unknown) => {
        setState("error");
        setErrorMessage(
          err instanceof Error
            ? err.message
            : "Failed to activate brokerage connection. Please try again.",
        );
      });
  // WHY accessToken in deps: the effect must re-run if the token becomes available
  // after the initial render (e.g., token refresh on page load).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  // ── Loading UI ───────────────────────────────────────────────────────────
  if (state === "idle" || state === "loading") {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-8">
        <Loader2
          className="h-10 w-10 animate-spin"
          style={{ color: "#0EA5E9" }}
          aria-label="Activating brokerage connection"
        />
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">
            Activating your brokerage connection…
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            This takes just a moment.
          </p>
        </div>
      </div>
    );
  }

  // ── Success UI ───────────────────────────────────────────────────────────
  if (state === "success") {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-8">
        <CheckCircle2
          className="h-12 w-12"
          style={{ color: "#26A69A" }}
          aria-hidden="true"
        />
        <div className="text-center">
          <p className="text-base font-semibold text-foreground">
            Brokerage account connected successfully!
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Your transaction history will begin syncing shortly.
            New transactions will be imported automatically.
          </p>
        </div>

        {/* Navigation CTA — most users will want to verify the connection in Portfolio */}
        <Button
          size="sm"
          className="mt-2"
          onClick={() => router.push("/portfolio")}
        >
          Go to Portfolio
        </Button>
      </div>
    );
  }

  // ── Error UI ─────────────────────────────────────────────────────────────
  return (
    <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-8">
      <XCircle
        className="h-12 w-12"
        style={{ color: "#EF5350" }}
        aria-hidden="true"
      />
      <div className="text-center">
        <p className="text-base font-semibold text-foreground">
          Connection failed
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {errorMessage ?? "An unexpected error occurred. Please try again."}
        </p>
      </div>

      {/* Try Again — navigates back to Portfolio where user can re-open the modal */}
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push("/portfolio")}
        >
          Back to Portfolio
        </Button>
        <Button
          size="sm"
          onClick={() => {
            // Reset and retry by navigating back to portfolio where the
            // Connect Brokerage button lives. We don't retry inline because
            // the SnapTrade session params may have expired.
            router.push("/portfolio");
          }}
        >
          Try Again
        </Button>
      </div>
    </div>
  );
}
