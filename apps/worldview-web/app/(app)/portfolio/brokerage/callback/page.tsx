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
// WHY useQueryClient: after the callback completes (success or failure), we
// invalidate the "brokerage-connections" query so the Brokerages tab on the
// Portfolio page reflects the new connection state immediately when the user
// navigates back. Without this, TanStack Query serves stale cached data and
// the user sees the old list until the staleTime window expires.
import { useQueryClient } from "@tanstack/react-query";
import { createGateway } from "@/lib/gateway";
import { useAuth } from "@/hooks/useAuth";
// WHY qk: replaces inline ["brokerage-connections"] literals in invalidations.
import { qk } from "@/lib/query/keys";
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
  // WHY here (not in the effect): useQueryClient() is a hook and must be called
  // at the top level of the component, not inside useEffect.
  const queryClient = useQueryClient();

  // Read params from the URL.
  // WHY two source params for authId: SnapTrade Connection Portal v3 sends
  // "authorizationId"; Portal v4 renamed it to "connection_id". We accept
  // either (preferring v3) so the page works regardless of portal version.
  const connectionId = searchParams.get("connectionId") ?? "";
  const authorizationId = searchParams.get("authorizationId");
  const connectionIdSnap = searchParams.get("connection_id");
  // WHY prefer authorizationId: v3 explicit field beats v4 fallback when both
  // are somehow present (defensive — never observed in practice).
  const authId = authorizationId || connectionIdSnap || "";
  // WHY ?? "": userId and sessionId are absent in Connection Portal v4 callbacks.
  // The backend (services/portfolio/.../brokerage_connections.py:152-167) treats
  // an empty string as "not provided" and skips the userId anti-spoofing check
  // (JWT ownership verification on connectionId is sufficient on its own).
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

    // Guard: only the two truly critical IDs are required. userId/sessionId are
    // absent on v4 portal redirects and can be empty strings — the backend
    // tolerates that. Showing an error when only those two are missing would
    // block legitimate v4 callbacks.
    if (!connectionId || !authId) {
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
        // WHY pass authId under the legacy "authorizationId" key: the gateway/S9
        // contract still uses that name. v4's connection_id is normalised here
        // so backend code stays unchanged.
        authorizationId: authId,
        userId,
        sessionId,
      })
      .then(() => {
        // WHY invalidate on success: the connection status in TanStack Query cache
        // is still "pending" from when the modal first created it. After activation
        // it becomes "active". Invalidating forces ConnectedBrokeragesList to
        // re-fetch and show the correct status immediately when the user returns
        // to the Portfolio page via the "Go to Portfolio" button.
        void queryClient.invalidateQueries({ queryKey: qk.brokerage.connections() });
        setState("success");
      })
      .catch((err: unknown) => {
        // WHY also invalidate on error: a failed activation attempt may have left
        // the connection in an "error" status on the server. Invalidating ensures
        // ConnectedBrokeragesList shows the correct error badge + recovery options
        // (Sync Now / Disconnect) so the user is not stuck on a stale "pending" view.
        void queryClient.invalidateQueries({ queryKey: qk.brokerage.connections() });
        setState("error");
        setErrorMessage(
          err instanceof Error
            ? err.message
            : "Failed to activate brokerage connection. Please try again.",
        );
      });
  // WHY only [accessToken] in the dep array — URL params intentionally omitted:
  // connectionId/authorizationId/userId/sessionId are derived from useSearchParams()
  // at component level. On this page the URL is fully stable after the SnapTrade
  // redirect — SnapTrade never changes the callback URL while the component is
  // mounted. Including them would be safe but redundant. More importantly, the
  // hasActivated.current guard already prevents re-activation on any subsequent
  // re-render regardless of which deps change, so omitting the URL params has
  // no functional effect. The lint rule is suppressed to document this intent.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  // ── Loading UI ───────────────────────────────────────────────────────────
  if (state === "idle" || state === "loading") {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-3">
        <Loader2
          className="h-10 w-10 animate-spin text-primary"
          aria-label="Activating brokerage connection"
        />
        <div className="text-center">
          <p className="text-[14px] font-medium text-foreground">
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
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-3">
        <CheckCircle2
          className="h-12 w-12 text-positive"
          aria-hidden="true"
        />
        <div className="text-center">
          <p className="text-[16px] font-semibold text-foreground">
            Brokerage account connected successfully!
          </p>
          {/* Honest sync-timing copy — PRD-0122 §6.2 (R-9, R-10).
              WHY THIS COPY: the old "will begin syncing shortly" set a false
              expectation — the real import cycle can take hours, so users thought the
              connection was broken when nothing appeared in seconds. The new copy is
              explicit (minutes → up to a few hours) and gives them a concrete recovery
              action ("Sync Now" on the connected-brokerages list) instead of leaving
              them to guess. WHY the timing is qualitative ("up to a few hours"): the
              exact cycle length is a backend config value; describing it qualitatively
              means a future cycle-time change never falsifies this string.
              NOTE: the heading above is intentionally UNCHANGED — e2e/qa specs pin the
              exact "Brokerage account connected successfully!" string. */}
          <p className="mt-1 text-[14px] text-muted-foreground">
            Your first sync has started. Holdings usually appear within a few minutes,
            but a full import can take up to a few hours. If you don&apos;t see them yet,
            open the connected brokerage and press <span className="font-medium text-foreground">Sync Now</span> to
            pull the latest data.
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
    <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-3">
      <XCircle
        className="h-12 w-12 text-negative"
        aria-hidden="true"
      />
      <div className="text-center">
        <p className="text-[16px] font-semibold text-foreground">
          Connection failed
        </p>
        <p className="mt-1 text-[14px] text-muted-foreground">
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
