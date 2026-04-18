/**
 * app/callback/page.tsx — OIDC callback handler
 *
 * WHY THIS EXISTS: After a user authenticates with Zitadel, Zitadel redirects
 * back to this URL with an authorization code (?code=...&state=...).
 * This page completes the PKCE flow:
 * 1. Validate the state param (CSRF protection)
 * 2. Retrieve the code_verifier from sessionStorage
 * 3. POST code + verifier to S9 /api/v1/auth/callback
 * 4. S9 exchanges for tokens with Zitadel, sets httpOnly refresh cookie, returns access token
 * 5. Hydrate AuthContext with access token via setTokens()
 * 6. Navigate to the original destination (from sessionStorage auth_redirect_to)
 *
 * WHY S9 handles the exchange (not this page directly):
 * The token exchange requires a client_secret or is made server-to-server.
 * S9 acts as the secure backend that makes the token exchange with Zitadel and
 * sets the httpOnly cookie that browser JS can never read (XSS protection).
 * PRD-0028 §6.6, §8.1.
 *
 * WHO USES IT: Zitadel redirects here automatically after successful authentication.
 * DATA SOURCE: S9 POST /api/v1/auth/callback
 * DESIGN REFERENCE: PRD-0028 §6.6.1 PKCE Callback
 */

"use client";
// WHY "use client": Reads URL search params (useSearchParams), accesses sessionStorage,
// calls AuthContext (useAuth), and triggers navigation — all browser-side operations.

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { createGateway, GatewayError } from "@/lib/gateway";

// ── Error types for user-facing messages ──────────────────────────────────────

type CallbackErrorType =
  | "state_mismatch"    // CSRF: state in URL doesn't match sessionStorage
  | "missing_code"      // Zitadel didn't return a code (auth was cancelled or failed)
  | "exchange_failed"   // S9 token exchange returned an error
  | "missing_verifier"; // sessionStorage was cleared mid-flow (tab was closed and re-opened)

const ERROR_MESSAGES: Record<CallbackErrorType, string> = {
  state_mismatch:
    "Security check failed. The login session may have been tampered with. Please try again.",
  missing_code:
    "Authentication was cancelled or failed. Please try again.",
  exchange_failed:
    "Unable to complete sign-in. The server returned an error. Please try again.",
  missing_verifier:
    "Login session expired. Please start the login process again.",
};

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * CallbackContent — the actual callback logic (inner component)
 *
 * WHY separate from CallbackPage: useSearchParams() requires a Suspense boundary
 * in Next.js 15 App Router. Extracting the hook call into a child component
 * allows the parent (CallbackPage) to wrap it in <Suspense>. Without this,
 * `next build` fails with "missing-suspense-with-csr-bailout" error.
 */
function CallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setTokens } = useAuth();

  const [errorType, setErrorType] = useState<CallbackErrorType | null>(null);

  // WHY useRef for hasRun: In React 18 Strict Mode (dev), effects run twice.
  // The PKCE verifier is consumed on first run; the second run would fail with
  // "missing_verifier" (because sessionStorage was cleared). The ref prevents
  // the second run from executing the exchange logic.
  const hasRun = useRef(false);

  useEffect(() => {
    // Guard against double-invocation in React Strict Mode dev
    if (hasRun.current) return;
    hasRun.current = true;

    async function handleCallback() {
      // Step 1: Extract params from the callback URL
      const code = searchParams.get("code");
      const stateFromUrl = searchParams.get("state");
      const errorParam = searchParams.get("error");

      // WHY check error param: If user cancels auth, Zitadel returns ?error=access_denied
      if (errorParam ?? !code) {
        setErrorType("missing_code");
        return;
      }

      // Step 2: CSRF state validation
      // WHY: An attacker could forge a callback URL with a valid code from their
      // own session. The state param ties this callback to the specific login
      // initiation from this browser tab.
      const storedState = sessionStorage.getItem("pkce_state");
      if (!storedState || stateFromUrl !== storedState) {
        setErrorType("state_mismatch");
        return;
      }

      // Step 3: Retrieve the code verifier (consumed once, then deleted)
      const codeVerifier = sessionStorage.getItem("pkce_verifier");
      if (!codeVerifier) {
        setErrorType("missing_verifier");
        return;
      }

      // Clean up PKCE session storage — these values are now consumed
      sessionStorage.removeItem("pkce_verifier");
      sessionStorage.removeItem("pkce_state");

      // Step 4: Exchange code + verifier with S9
      try {
        const gw = createGateway(); // no token yet — we're getting the first token now
        const response = await gw.exchangeCode({
          code,
          code_verifier: codeVerifier,
          redirect_uri: `${window.location.origin}/callback`,
        });

        // Step 5: Hydrate AuthContext with the returned access token
        // WHY setTokens (not direct setState): Encapsulates the silent refresh timer setup
        setTokens(response.access_token, response.user, response.expires_in);

        // Step 6: Navigate to original destination (or dashboard as fallback)
        const redirectTo = sessionStorage.getItem("auth_redirect_to") ?? "/dashboard";
        sessionStorage.removeItem("auth_redirect_to");

        // WHY router.replace (not push): The callback URL should not remain
        // in browser history — hitting "back" should not re-trigger the exchange.
        router.replace(redirectTo);
      } catch (err) {
        if (err instanceof GatewayError) {
          setErrorType("exchange_failed");
        } else {
          setErrorType("exchange_failed");
        }
      }
    }

    void handleCallback();
  }, [searchParams, router, setTokens]); // eslint-disable-line react-hooks/exhaustive-deps
  // WHY these deps: searchParams contains the code/state from Zitadel.
  // router and setTokens are stable (memo'd by Next.js and React respectively).

  // Error state — show user-friendly message with option to retry
  if (errorType) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm space-y-4">
          <h1 className="text-lg font-semibold text-destructive">Sign-in failed</h1>
          <p className="text-sm text-muted-foreground">{ERROR_MESSAGES[errorType]}</p>
          <a
            href="/login"
            className="block text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Try again
          </a>
        </div>
      </div>
    );
  }

  // Loading state — shown while the token exchange is in progress (typically < 500ms)
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
        <p className="text-sm text-muted-foreground">Completing sign-in…</p>
      </div>
    </div>
  );
}

/**
 * CallbackPage — Suspense wrapper for the OIDC callback handler
 *
 * WHY Suspense: Next.js 15 requires any component using useSearchParams()
 * to be wrapped in a Suspense boundary. The fallback is the same loading
 * spinner shown while the token exchange runs, ensuring smooth UX.
 */
export default function CallbackPage() {
  return (
    // WHY this specific fallback: matches the loading state in CallbackContent
    // so there's no visual jump between suspense fallback and callback rendering
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="flex flex-col items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
            <p className="text-sm text-muted-foreground">Completing sign-in…</p>
          </div>
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
