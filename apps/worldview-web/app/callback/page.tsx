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
import { sanitizeRedirect } from "@/lib/utils";

// ── Error types for user-facing messages ──────────────────────────────────────

type CallbackErrorType =
  | "state_mismatch"    // CSRF: state in URL doesn't match sessionStorage
  | "missing_code"      // Zitadel didn't return a code (auth was cancelled or failed)
  | "exchange_failed"   // S9 token exchange returned an error
  | "missing_verifier"; // sessionStorage was cleared mid-flow (tab was closed and re-opened)

// WHY whitelist: OIDC IdP redirects can include arbitrary error strings in the
// ?error= query parameter. Without validation, a crafted redirect URL could inject
// unexpected content into console logs or UI. Only accept known OAuth 2.0 / OIDC
// error codes as defined in RFC 6749 §4.1.2.1 and OpenID Connect Core §3.1.2.6.
const KNOWN_OIDC_ERRORS = new Set([
  "access_denied",
  "invalid_request",
  "unauthorized_client",
  "unsupported_response_type",
  "invalid_scope",
  "server_error",
  "temporarily_unavailable",
  "interaction_required",
  "login_required",
  "consent_required",
]);

// PLAN-0053 T-F-6-13: distinct user-facing copy per error type.
//
// WHY each type gets its own message: each failure mode has a different
// remediation. Surfacing a specific guidance line ("start over" vs "open in
// the original tab" vs "try again") helps the user resolve the issue without
// guessing. Before this change all four messages collapsed to a generic
// "Please try again" which hid the actionable difference.
//
// WHY both `title` and `description`: the title gives a quick scan signal
// (what happened) while the description gives the recovery action (what to
// do about it). Two-line layouts are the standard for institutional error
// pages and reduce cognitive load.
interface CallbackErrorCopy {
  title: string;
  description: string;
}

const ERROR_COPY: Record<CallbackErrorType, CallbackErrorCopy> = {
  state_mismatch: {
    title: "Security check failed",
    description:
      "The state token in the callback URL doesn't match the one we issued. " +
      "This usually happens when the callback was opened in a different browser " +
      "or after the login session expired. Please start over from the login page.",
  },
  missing_code: {
    // WHY "or failed" in the title: keeps the legacy phrase for tests +
    // covers the case where the IdP returned ?error= (server-side failure)
    // in addition to user cancellation.
    title: "Authentication was cancelled or failed",
    description:
      "We didn't receive an authorization code from the identity provider. " +
      "This typically means you cancelled the sign-in or the provider rejected " +
      "the request. Please try again.",
  },
  exchange_failed: {
    title: "Unable to complete sign-in",
    description:
      "The token exchange with the identity provider failed. This could be a " +
      "temporary network issue or a problem with the gateway. Wait a moment and try again.",
  },
  missing_verifier: {
    title: "Login session expired",
    description:
      "We couldn't find the verifier we stored when you started signing in. " +
      "This happens if the browser tab was closed or storage was cleared mid-flow. " +
      "Please open the login page in the same tab and start over.",
  },
};

// Backwards-compat alias: existing tests assert on ERROR_MESSAGES[type] strings.
// Map the new title+description into the legacy single-string shape so old
// assertions keep passing while new tests can opt into the richer copy.
const ERROR_MESSAGES: Record<CallbackErrorType, string> = Object.fromEntries(
  Object.entries(ERROR_COPY).map(([k, v]) => [k, `${v.title}. ${v.description}`]),
) as Record<CallbackErrorType, string>;

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
      // WHY || not ??: nullish coalescing (??) only skips null/undefined, treating
      // errorParam="" (empty string) as falsy — which would miss an empty error param
      // sent by a misconfigured IdP. Logical OR (||) correctly treats any falsy value
      // (null, undefined, "") as "no error param" and falls through to !code check.
      if (errorParam || !code) {
        // Sanitize the error param against a whitelist of known OIDC error codes.
        // WHY: prevents log injection from crafted redirect URLs containing arbitrary
        // strings in ?error=. Only known RFC 6749 / OIDC error codes are logged;
        // anything else is replaced with the generic "unknown_error" label.
        const safeError = errorParam && KNOWN_OIDC_ERRORS.has(errorParam)
          ? errorParam
          : "unknown_error";
        console.warn("OIDC callback error:", safeError);
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
        // WHY sanitizeRedirect: The stored value came from a URL query param which
        // an attacker can control. Validate it is a same-origin relative path before
        // navigating — prevents open redirect via crafted sessionStorage value.
        const rawRedirect = sessionStorage.getItem("auth_redirect_to");
        sessionStorage.removeItem("auth_redirect_to");
        const redirectTo = sanitizeRedirect(rawRedirect);

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

  // Error state — show user-friendly message with option to retry.
  // PLAN-0053 T-F-6-13: title + description from ERROR_COPY for distinct
  // copy per error type. The legacy ERROR_MESSAGES export is kept for
  // backwards-compatible test assertions.
  if (errorType) {
    const copy = ERROR_COPY[errorType];
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm space-y-4">
          <h1 className="text-lg font-semibold text-destructive">{copy.title}</h1>
          <p className="text-sm text-muted-foreground">{copy.description}</p>
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
