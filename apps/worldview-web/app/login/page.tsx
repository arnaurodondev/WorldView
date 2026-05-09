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

  // ── Probe whether Zitadel is available ────────────────────────────────
  //
  // PLAN-0053 T-F-6-12: tightened — the dev-login affordance now requires
  // BOTH conditions (logical AND, was OR):
  //   1. The S9 gateway returns 502 on /v1/auth/login (OIDC discovery failed)
  //   2. NEXT_PUBLIC_ZITADEL_URL is missing
  //
  // WHY both: prevents the dev-login button from appearing in production
  // deployments where the env var is set but the gateway has a transient
  // upstream hiccup. Previously, a single 502 from S9 (e.g. Zitadel
  // momentarily unreachable) was enough to flip a real user into a "dev
  // login bypass available" state — which is a security concern even if
  // the dev-login endpoint itself rejects the request when Zitadel is
  // actually configured. Tightening the probe means dev-login can ONLY
  // appear in genuine local-dev scenarios where the env var isn't set.
  useEffect(() => {
    const zitadelBaseUrl = process.env.NEXT_PUBLIC_ZITADEL_URL;
    const envMissing = !zitadelBaseUrl;

    // Fast path: if env IS configured, dev-login is never offered. Skip the
    // probe entirely — production deployments shouldn't pay a network round
    // trip on every login page render.
    if (!envMissing) {
      setDevLoginAvailable(false);
      return;
    }

    // Env var IS missing. Confirm with the gateway that OIDC is also
    // unconfigured server-side (502 == oidc_discovery_failed) before
    // showing the dev-login button. Belt-and-braces — if a misconfigured
    // build slips out without the env var but with a healthy Zitadel
    // (rare but possible), we still don't show the dev shortcut.
    async function probeOidc() {
      try {
        const resp = await fetch("/api/v1/auth/login", {
          method: "GET",
          redirect: "manual", // Don't follow the 302 redirect to Zitadel
        });
        // 302 = OIDC is working (Zitadel redirect); 502 = OIDC unavailable.
        // Only flip dev-login on when the gateway agrees with the env var.
        if (resp.status === 502) {
          setDevLoginAvailable(true);
        }
      } catch {
        // Network error (gateway not running) — env var is also missing,
        // so this is almost certainly a local dev environment.
        setDevLoginAvailable(true);
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
    try {
      const gw = createGateway();
      const response = await gw.devLogin();
      // Hydrate auth context with the demo JWT — same as a real OIDC callback
      setTokens(response.access_token, response.user, response.expires_in);
      // Navigate to the intended destination
      router.replace(redirectTo);
    } catch (err) {
      setIsDevLoggingIn(false);
      if (err instanceof GatewayError && err.status === 403) {
        // 403 means OIDC is actually configured — shouldn't happen but handle gracefully
        setDevLoginAvailable(false);
        setError("Dev login is disabled because Zitadel is configured. Use the normal login flow.");
      } else {
        setError(err instanceof Error ? err.message : "Dev login failed. Is the API Gateway running?");
      }
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
        scope: "openid profile email", // WHY these scopes: standard OIDC profile claims
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
            WHY separate button: Makes it visually obvious that this is a dev-only
            shortcut, not the real auth flow. The amber outline reinforces this. */}
        {devLoginAvailable && (
          <div className="space-y-3">
            <Button
              onClick={() => void handleDevLogin()}
              disabled={isDevLoggingIn}
              variant="outline"
              // WHY border-warning + text-warning (was off-palette amber-500):
              // --warning is the Terminal Dark amber token; using it keeps the
              // dev-login affordance aligned with the rest of the warning UI
              // language (stale badges, attention chips). Same visual hue,
              // managed via design token instead of a stale Tailwind shorthand.
              className="w-full border-warning/50 text-warning hover:bg-warning/10"
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
