/**
 * app/login/page.tsx — OIDC login initiation page
 *
 * WHY THIS EXISTS: Unauthenticated users are redirected here by the (app) layout
 * guard. This page constructs the Zitadel OIDC PKCE authorization URL and
 * redirects the browser to begin the auth flow.
 *
 * WHY PKCE (not implicit flow): PKCE is the current OWASP-recommended flow for
 * SPAs. It prevents authorization code interception attacks without requiring a
 * client secret (which would be unsafe to embed in browser-side code).
 * Zitadel supports PKCE natively. PRD-0028 §6.6.
 *
 * PKCE FLOW (this page handles step 1 of 3):
 * 1. [THIS PAGE] Generate code_verifier (random), derive code_challenge (SHA-256),
 *    store verifier in sessionStorage, redirect to Zitadel with challenge
 * 2. [ZITADEL] User authenticates, Zitadel redirects to /callback?code=...&state=...
 * 3. [/callback] Exchange code + verifier → tokens via S9 POST /api/v1/auth/callback
 *
 * WHY sessionStorage (not localStorage) for code_verifier:
 * The verifier is short-lived (single auth round-trip, seconds to minutes).
 * sessionStorage is tab-scoped (safer than localStorage for this transient value).
 * The verifier itself is NOT a secret token — it's a random value used only once.
 * No sensitive user data or access tokens are ever in sessionStorage.
 *
 * WHO USES IT: All unauthenticated users attempting to access a protected route.
 * DATA SOURCE: None (no S9 calls — this is a pure redirect page)
 * DESIGN REFERENCE: PRD-0028 §6.6.1 Login Flow, canvas State E (login screen)
 */

"use client";
// WHY "use client": Uses browser APIs — crypto.subtle for PKCE SHA-256,
// window.location.replace() for redirect, sessionStorage for code_verifier.
// None of these are available in Server Components.

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { createGateway, GatewayError } from "@/lib/gateway";
import { sanitizeRedirect } from "@/lib/utils";

// ── PKCE helpers ──────────────────────────────────────────────────────────────

/**
 * generateCodeVerifier — produce a cryptographically random PKCE code verifier
 * WHY 128 chars: RFC 7636 requires 43-128 characters. 128 maximises entropy.
 * WHY crypto.getRandomValues: Math.random() is not cryptographically secure.
 */
function generateCodeVerifier(): string {
  const array = new Uint8Array(96); // 96 bytes → 128 base64url chars
  crypto.getRandomValues(array);
  // base64url encoding: replace +, /, = to make it URL-safe
  return btoa(String.fromCharCode(...array))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

/**
 * generateCodeChallenge — SHA-256 hash of the verifier, base64url encoded
 * WHY S256 method: Plain method (no hash) is vulnerable to interception.
 * S256 is the only method Zitadel accepts for production PKCE flows.
 */
async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", data);
  // Convert ArrayBuffer to base64url string
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

/**
 * generateState — random CSRF protection token
 * WHY: Zitadel echoes the state param back in the callback. We verify it
 * matches to prevent CSRF attacks (an attacker can't forge a matching state).
 */
function generateState(): string {
  const array = new Uint8Array(16);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, "0")).join("");
}

// ── Component ─────────────────────────────────────────────────────────────────

/**
 * LoginContent — inner component that uses useSearchParams()
 * WHY separated: Next.js 15 requires useSearchParams() to be inside a Suspense boundary.
 * Splitting keeps the export default clean and avoids the build-time prerender error.
 */
function LoginContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setTokens } = useAuth();

  // WHY track isInitiating: Prevents double-clicks from firing two PKCE flows
  // (second click before the first redirect completes would overwrite sessionStorage)
  const [isInitiating, setIsInitiating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Dev Login state ───────────────────────────────────────────────────
  // WHY devLoginAvailable: When Zitadel is not running (local dev), the
  // gateway's /v1/auth/login returns 502 (oidc_discovery_failed). We detect
  // this and show a "Dev Login" button that calls POST /v1/auth/dev-login.
  // This lets developers use the full frontend without configuring Zitadel.
  const [devLoginAvailable, setDevLoginAvailable] = useState(false);
  const [isDevLoggingIn, setIsDevLoggingIn] = useState(false);

  // WHY read redirect_to from URL: The (app) layout guard appends this param
  // when redirecting unauthenticated users. After login succeeds, /callback
  // reads it from sessionStorage and navigates back to the original destination.
  // WHY sanitizeRedirect: Prevent open redirect — an attacker could craft
  // /login?redirect_to=https://evil.com to redirect the user after authentication.
  // Only same-origin relative paths (starting with "/") are allowed.
  const redirectTo = sanitizeRedirect(searchParams.get("redirect_to"));

  // ── Probe whether Zitadel OIDC is available ───────────────────────────
  //
  // BUGFIX (local-dev login blocker): the gateway's OIDC-init route
  // (`GET /api/v1/auth/login`) is the AUTHORITATIVE signal for whether real
  // OIDC login works. When Zitadel is configured it returns a 302 redirect to
  // Zitadel; when OIDC is NOT configured (local dev) it returns 502 with body
  // `{"error":"oidc_discovery_failed"}`. The correct semantics for that 502 is
  // "OIDC unavailable → OFFER dev login", not "auth broken → hide everything".
  //
  // WHY THIS CHANGED (was PLAN-0053 T-F-6-12 AND-gate):
  // The previous logic required BOTH a 502 probe AND `NEXT_PUBLIC_ZITADEL_URL`
  // to be unset, with an early return that skipped the probe entirely whenever
  // the env var WAS set. That AND-gate silently hid the Dev Login button for a
  // very common local setup: a developer who sets `NEXT_PUBLIC_ZITADEL_URL`
  // (as `.env.example` shows for PKCE testing) but does NOT actually have
  // Zitadel running. In that case the OIDC-init route 502s, real login is
  // impossible, AND the dev-login button was hidden — leaving no way to log in
  // through the UI at all. It also made the affordance depend on a client-side
  // env var whose absence is easy to get wrong.
  //
  // NEW SEMANTICS — the gateway probe decides, so prod stays safe:
  //   • 502  → OIDC is explicitly unconfigured  → SHOW dev login.
  //   • 2xx/3xx (302) → OIDC works (Zitadel)    → HIDE dev login (prod path).
  //   • network error / timeout → gateway unreachable (ambiguous) → fall back
  //     to the env-var hint: only offer dev login if the OIDC env var is also
  //     missing, so a real production infra outage does not surface a dev
  //     bypass affordance. In prod the env var is set, so a gateway outage
  //     keeps the button hidden; in local dev the env var is typically unset,
  //     so a not-yet-started gateway still offers dev login.
  //
  // Production safety is preserved because a configured Zitadel returns 302
  // (button hidden), and even in the unlikely event of a transient prod 502
  // the dev-login endpoint itself returns 403 when OIDC is configured — which
  // handleDevLogin() below catches and uses to hide the button again.
  useEffect(() => {
    // Whether the client build has an OIDC issuer configured. Used ONLY as a
    // tie-breaker when the gateway is unreachable (see below).
    const envMissing = !process.env.NEXT_PUBLIC_ZITADEL_URL;

    async function probeOidc() {
      // WHY AbortController: without a timeout this fetch hangs until the
      // browser's internal limit (~25 s) when the gateway is cold or slow.
      // 5 s matches the dev-login handler's hard timeout; on abort we treat it
      // as "gateway unreachable" and defer to the env-var tie-breaker.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);
      try {
        const resp = await fetch("/api/v1/auth/login", {
          method: "GET",
          redirect: "manual", // Don't follow the 302 redirect to Zitadel
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        // 502 == oidc_discovery_failed → OIDC unconfigured → offer dev login.
        // Anything else (302 redirect to Zitadel, or a 2xx) means real OIDC is
        // available → hide the dev-login shortcut and show the Zitadel button.
        setDevLoginAvailable(resp.status === 502);
      } catch {
        clearTimeout(timeoutId);
        // Network error or AbortError (timeout): the gateway did not answer, so
        // we can't confirm OIDC status. Defer to the env-var hint — offer dev
        // login only when the OIDC issuer is also unconfigured (local dev),
        // never on a production build where the issuer env var is set.
        setDevLoginAvailable(envMissing);
      }
    }
    void probeOidc();
  }, []);

  // ── Dev Login handler ──────────────────────────────────────────────────
  // WHY useCallback: This function is only created once (empty deps).
  // It calls POST /v1/auth/dev-login on S9, which issues a JWT for the
  // demo user. The response has the same shape as the real OIDC callback
  // so we can reuse AuthContext.setTokens() identically.
  const handleDevLogin = useCallback(async () => {
    setIsDevLoggingIn(true);
    setError(null);

    // FR-7.2: hard timeout guard — if the dev-login round-trip hangs (e.g.
    // the API Gateway is slow to respond), the loading spinner would never
    // clear without this. After 5 s we abort the in-progress visual state and
    // show an error so the user can retry or diagnose the issue.
    // WHY 5 s: long enough for a cold-start Docker container but short enough
    // that a broken gateway doesn't leave the login button permanently disabled.
    const hardTimeout = window.setTimeout(() => {
      setIsDevLoggingIn(false);
      setError("Dev login timed out after 5 s. Is the API Gateway running?");
    }, 5000);

    try {
      const gw = createGateway();
      const response = await gw.devLogin();
      // Hydrate auth context with the demo JWT — same as a real OIDC callback
      setTokens(response.access_token, response.user, response.expires_in);
      // Navigate to the intended destination
      router.replace(redirectTo);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[dev-login] failed:", err);
      if (err instanceof GatewayError && err.status === 403) {
        // 403 means OIDC is actually configured — shouldn't happen but handle gracefully
        setDevLoginAvailable(false);
        setError("Dev login is disabled because Zitadel is configured. Use the normal login flow.");
      } else {
        setError(err instanceof Error ? err.message : "Dev login failed. Is the API Gateway running?");
      }
    } finally {
      // WHY clearTimeout in finally: if the request succeeds (router.replace
      // triggers navigation) or fails (catch block sets error), we must cancel
      // the hard-timeout timer so it doesn't fire after the component has
      // already cleaned up. finally guarantees this runs even if the try block
      // throws synchronously.
      clearTimeout(hardTimeout);
      setIsDevLoggingIn(false);
    }
  }, [redirectTo, router, setTokens]);

  // WHY initiateLogin is async: crypto.subtle.digest() is Promise-based (Web Crypto API)
  const initiateLogin = async () => {
    setIsInitiating(true);
    setError(null);

    try {
      const verifier = generateCodeVerifier();
      const challenge = await generateCodeChallenge(verifier);
      const state = generateState();

      // Store verifier and redirect target in sessionStorage.
      // WHY sessionStorage: Tab-scoped, cleaned up when tab closes.
      // The verifier is only needed for the callback round-trip (seconds to minutes).
      sessionStorage.setItem("pkce_verifier", verifier);
      sessionStorage.setItem("pkce_state", state);
      sessionStorage.setItem("auth_redirect_to", redirectTo);

      // Construct the Zitadel OIDC authorization URL
      // All OIDC params come from environment variables set via next.config.ts
      const zitadelBaseUrl = process.env.NEXT_PUBLIC_ZITADEL_URL;
      const clientId = process.env.NEXT_PUBLIC_ZITADEL_CLIENT_ID;
      const callbackUrl = `${window.location.origin}/callback`;

      if (!zitadelBaseUrl || !clientId) {
        throw new Error(
          "Missing NEXT_PUBLIC_ZITADEL_URL or NEXT_PUBLIC_ZITADEL_CLIENT_ID. " +
            "Check .env.local — these must be set for auth to work.",
        );
      }

      const params = new URLSearchParams({
        response_type: "code",
        client_id: clientId,
        redirect_uri: callbackUrl,
        // WHY offline_access: Zitadel only returns a refresh_token when
        // offline_access is among the authorize scopes. Without it, S9's
        // /v1/auth/callback receives no refresh_token, sets no httpOnly cookie,
        // and every silent POST /api/v1/auth/refresh 401s → the user is bounced
        // to the Zitadel sign-in page on each access-token expiry.
        // This MUST match the S9 GET /v1/auth/login scope (auth.py:142), which
        // already requests offline_access. See audit 2026-07-19-refresh-token-failure.
        scope: "openid profile email offline_access", // WHY these scopes: standard OIDC profile claims + refresh token
        code_challenge: challenge,
        code_challenge_method: "S256",
        state,
      });

      // Full page redirect to Zitadel — user leaves the SPA temporarily
      window.location.replace(`${zitadelBaseUrl}/oauth/v2/authorize?${params.toString()}`);
    } catch (err) {
      setIsInitiating(false);
      setError(err instanceof Error ? err.message : "Failed to initiate login. Please try again.");
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
      {/* Login card — centered, compact, no decorative whitespace */}
      <div className="w-full max-w-sm space-y-6">
        {/* Wordmark — text-only for crisp rendering at small sizes */}
        <div className="text-center">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            Worldview
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Market intelligence terminal
          </p>
        </div>

        {/* Error state — shown if PKCE setup fails (missing env vars, crypto error) */}
        {error && (
          <div
            role="alert"
            // WHY rounded-[2px] (was rounded-md=6px): Terminal Dark uses 2px
            // for all corner radii; 6px reads as a consumer-app pattern.
            className="rounded-[2px] border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </div>
        )}

        {/* Primary CTA — initiates PKCE flow (hidden when Zitadel is unavailable) */}
        {!devLoginAvailable && (
          <Button
            onClick={() => void initiateLogin()}
            disabled={isInitiating}
            className="w-full"
            size="lg"
          >
            {isInitiating ? "Redirecting to Zitadel…" : "Sign in with Zitadel"}
          </Button>
        )}

        {/* Dev Login — shown only when Zitadel OIDC is not configured.
            FR-7.3: restyled to ghost/muted (was amber/warning) so it does not
            read as a "warning" CTA in local dev — it is a neutral shortcut.
            Amber was visually alarming; muted-foreground communicates "secondary
            tool" without implying an error state. */}
        {devLoginAvailable && (
          <div className="space-y-3">
            <Button
              onClick={() => void handleDevLogin()}
              disabled={isDevLoggingIn}
              // FR-7.3: ghost variant + muted text instead of amber/warning border.
              variant="ghost"
              className="w-full text-[11px] text-muted-foreground hover:text-foreground"
              size="lg"
            >
              {isDevLoggingIn ? "Signing in…" : "Dev Login (no Zitadel)"}
            </Button>
            {/* WHY this caption: Developers need to know this bypasses real auth.
                If they see this in a context where Zitadel SHOULD be running,
                it signals a misconfiguration. */}
            <p className="text-center text-xs text-muted-foreground">
              Zitadel is not configured. Using local demo credentials.
              <br />
              Run <code className="text-xs">make seed</code> first to create the demo user.
            </p>
          </div>
        )}

        {/* Register link — navigates to register page which redirects to Zitadel self-registration */}
        {!devLoginAvailable && (
          <p className="text-center text-sm text-muted-foreground">
            Don&apos;t have an account?{" "}
            <a
              href="/register"
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              Register
            </a>
          </p>
        )}
      </div>
    </div>
  );
}

/** LoginPage — Suspense wrapper (required for useSearchParams in Next.js 15) */
export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-border border-t-primary" />
        </div>
      }
    >
      <LoginContent />
    </Suspense>
  );
}
