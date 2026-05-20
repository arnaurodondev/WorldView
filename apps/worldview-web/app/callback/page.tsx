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
// PLAN-0059 W0 fix F-001 (2026-04-30): ERROR_COPY/ERROR_MESSAGES/CallbackErrorType
// were inlined here previously, but Next.js 15 page files must not export
// arbitrary names — only the framework-recognised set is allowed. Inlining
// + exporting `ERROR_MESSAGES` for tests broke `tsc` (TS2344) and `next build`.
// Constants now live in a sibling module so both this page and the test file
// can import them safely. See docs/BUG_PATTERNS.md BP-NEW for the pattern.
import {
  type CallbackErrorType,
  ERROR_COPY,
} from "./error-messages";

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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setTokens is stable (AuthContext value, intentionally omitted to avoid re-running the one-shot exchange)
  }, [searchParams, router]);
  // WHY these deps: searchParams contains the code/state from Zitadel.
  // router is stable (memoised by Next.js). setTokens is intentionally
  // excluded — it is a stable AuthContext setter that never changes identity,
  // and including it would retrigger the PKCE exchange on every silent
  // token refresh (which updates the AuthContext value and invalidates
  // all downstream memo comparisons). FR-7.1.

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
