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

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";

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

  // WHY track isInitiating: Prevents double-clicks from firing two PKCE flows
  // (second click before the first redirect completes would overwrite sessionStorage)
  const [isInitiating, setIsInitiating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WHY read redirect_to from URL: The (app) layout guard appends this param
  // when redirecting unauthenticated users. After login succeeds, /callback
  // reads it from sessionStorage and navigates back to the original destination.
  const redirectTo = searchParams.get("redirect_to") ?? "/dashboard";

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
            className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {error}
          </div>
        )}

        {/* Primary CTA — initiates PKCE flow */}
        <Button
          onClick={() => void initiateLogin()}
          disabled={isInitiating}
          className="w-full"
          size="lg"
        >
          {isInitiating ? "Redirecting to Zitadel…" : "Sign in with Zitadel"}
        </Button>

        {/* Register link — navigates to register page which redirects to Zitadel self-registration */}
        <p className="text-center text-sm text-muted-foreground">
          Don&apos;t have an account?{" "}
          <a
            href="/register"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Register
          </a>
        </p>
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
