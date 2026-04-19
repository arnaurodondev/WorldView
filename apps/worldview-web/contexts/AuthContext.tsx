/**
 * contexts/AuthContext.tsx — OIDC authentication state manager
 *
 * WHY THIS EXISTS: The entire application needs to know:
 * 1. Is the user authenticated? (to decide whether to redirect to login)
 * 2. What is the access token? (to attach to S9 API calls)
 * 3. Who is the user? (for display in TopBar, audit logging)
 *
 * WHY CONTEXT (not URL state or global variable):
 * React Context propagates state to any nested component without prop drilling.
 * The auth state is consumed by layout guards, the TopBar, and every TanStack
 * Query hook that calls an authenticated S9 endpoint.
 *
 * SECURITY CRITICAL:
 * - accessToken lives ONLY in React state (this context)
 * - NEVER localStorage, NEVER sessionStorage, NEVER a JS-writable cookie
 * - WHY: localStorage is accessible to injected scripts (XSS attacks).
 *   React state cannot be read from the outside — it's garbage-collected with
 *   the component tree. This is the standard auth pattern for SPAs (OWASP).
 *
 * OIDC FLOW (Zitadel PKCE):
 * 1. App mounts → AuthProvider checks if token is fresh via isTokenExpiringSoon()
 * 2. If fresh: skip POST /auth/refresh (ADR-F-18)
 * 3. If expired/missing: POST /api/v1/auth/refresh → 200 sets authenticated,
 *    401 means session expired → user must log in again
 * 4. After callback: CallbackPage calls setTokens() to hydrate context
 * 5. Silent refresh: timer fires 60s before expiry to refresh proactively
 *
 * WHO USES IT: All protected-route components, TopBar, every useQuery hook.
 * DATA SOURCE: POST /api/v1/auth/refresh (httpOnly cookie-based token store)
 * DESIGN REFERENCE: PRD-0028 §6.6 Auth Flows, §8.1 Security Design
 */

"use client";
// WHY "use client": This component uses useState, useEffect, createContext —
// all React hooks that can only run in the browser. Server Components cannot
// have state. Auth state MUST be client-side (user-specific, not cached SSR).

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createGateway, GatewayError } from "@/lib/gateway";
import type { UserProfile } from "@/types/api";

// ── Types ─────────────────────────────────────────────────────────────────

interface AuthContextValue {
  /** true once the initial refresh check resolves (either success or 401) */
  isLoading: boolean;
  /** true after successful refresh OR after CallbackPage calls setTokens() */
  isAuthenticated: boolean;
  /** RS256 Bearer token from S9 — NEVER stored in localStorage */
  accessToken: string | null;
  /** User profile from S9 (user_id, tenant_id, email, name) */
  user: UserProfile | null;
  /**
   * Called by CallbackPage after the OIDC code exchange succeeds.
   * Sets state and schedules the silent refresh timer.
   */
  setTokens: (token: string, user: UserProfile, expiresIn: number) => void;
  /**
   * Calls POST /api/v1/auth/logout to revoke the httpOnly refresh token cookie,
   * then clears all in-memory auth state.
   */
  logout: () => Promise<void>;
}

// ── Token expiry helper (ADR-F-18) ────────────────────────────────────────

/**
 * isTokenExpiringSoon — check if a JWT is about to expire
 *
 * WHY THIS EXISTS: To avoid calling POST /auth/refresh on every page mount
 * when the user just logged in and the token is still valid for 14+ minutes.
 * Reading the exp claim from the JWT payload is safe:
 * - The payload is public (base64url, not encrypted)
 * - We are NOT bypassing S9's RS256 signature verification
 * - We're just deciding whether to make a network call
 *
 * Returns true if: no token, malformed token, or token expires in < 60 seconds.
 * 60s buffer ensures we don't try to use a token that expires mid-request.
 */
function isTokenExpiringSoon(token: string | null): boolean {
  if (!token) return true; // no token → must refresh

  try {
    // JWT structure: header.payload.signature (base64url encoded)
    // The payload contains {sub, exp, tenant_id, ...}
    const payloadB64 = token.split(".")[1];
    if (!payloadB64) return true;

    // atob() decodes base64 to string; JSON.parse() parses the claims object
    const payload = JSON.parse(atob(payloadB64)) as { exp?: number };
    if (!payload.exp) return true;

    // Compare expiry timestamp (seconds) against current time (milliseconds)
    const expiresInMs = payload.exp * 1000 - Date.now();
    return expiresInMs < 60_000; // refresh if < 60 seconds left
  } catch {
    // Malformed JWT → force refresh to be safe
    return true;
  }
}

// ── Context ───────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  // ── State ──────────────────────────────────────────────────────────────

  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [user, setUser] = useState<UserProfile | null>(null);

  // Ref to the silent refresh interval — cleaned up on unmount to prevent leaks
  // WHY useRef (not useState): the interval ID is not UI state; changing it
  // should not trigger a re-render. useRef is the right tool for imperative handles.
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Security invariant (dev only) ──────────────────────────────────────

  useEffect(() => {
    // WHY useEffect (not render body): Running this check in the render body
    // causes an error on every render cycle, which can trigger error boundary
    // loops in Strict Mode. useEffect runs once on mount, which is sufficient
    // to catch accidental localStorage writes during development.
    // In production, dead code elimination removes this entire block.
    if (process.env.NODE_ENV === "development") {
      if (typeof window !== "undefined" && window.localStorage.getItem("access_token")) {
        // WHY console.error (not throw): Throwing in useEffect crashes the error boundary.
        // console.error still surfaces the issue prominently in the dev console.
        console.error(
          "SECURITY VIOLATION: access_token found in localStorage. " +
            "Auth tokens must live in React state only (PRD-0028 §8.1).",
        );
      }
    }
  }, []); // only on mount

  // ── Silent refresh scheduler ───────────────────────────────────────────

  /**
   * scheduleRefresh — set a timer to refresh the token before it expires
   *
   * WHY proactive refresh (not on-demand): Reactive refresh (retry on 401)
   * causes failed requests during the refresh window, which shows error states
   * to the user mid-session. Proactive refresh keeps the session seamless.
   *
   * The timer fires 60 seconds before expiry, leaving a buffer for the
   * refresh network request to complete.
   */
  const scheduleRefresh = (expiresInSeconds: number) => {
    // Clear any existing timer before scheduling a new one
    // WHY: Multiple setTokens() calls (e.g., rapid navigation) would otherwise
    // accumulate multiple concurrent refresh timers
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }

    // Schedule refresh 60s before expiry
    const refreshAfterMs = Math.max(0, (expiresInSeconds - 60) * 1000);

    refreshTimerRef.current = setTimeout(async () => {
      try {
        const gw = createGateway(); // no token yet — uses httpOnly refresh cookie
        const response = await gw.refreshToken();
        // On success: update state with new token and re-schedule
        setAccessToken(response.access_token);
        setUser(response.user);
        setIsAuthenticated(true);
        scheduleRefresh(response.expires_in);
      } catch (err) {
        // Refresh failed: session expired. Clear state so layout guard redirects to login.
        if (err instanceof GatewayError && err.status === 401) {
          setAccessToken(null);
          setUser(null);
          setIsAuthenticated(false);
        }
        // For other errors (network), keep existing token — it may still be valid
      }
    }, refreshAfterMs);
  };

  // ── Initial auth check on mount ────────────────────────────────────────

  useEffect(() => {
    /**
     * checkAuth — determine if the user has an active session on page load
     *
     * WHY on mount (not SSR): Auth state is user-specific and depends on
     * httpOnly cookies which are only readable server-side. But we want
     * client-side routing (no full-page reloads), so we check on mount.
     *
     * Two paths:
     * 1. Token in state is fresh (exp > 60s): skip refresh call (ADR-F-18)
     * 2. Token is missing/expiring: POST /auth/refresh to get new one
     *    - httpOnly refresh token cookie is sent automatically by the browser
     *    - 200: authenticated; 401: no session (user must log in)
     */
    async function checkAuth() {
      // Path 1: Already have a fresh token (e.g., after navigation within app)
      // This branch is hit when AuthProvider remounts (rare in App Router, but safe)
      if (!isTokenExpiringSoon(accessToken)) {
        setIsLoading(false);
        return;
      }

      // Path 2: No token or expiring — try silent refresh
      try {
        const gw = createGateway(); // no Bearer token — relies on httpOnly cookie
        const response = await gw.refreshToken();
        setAccessToken(response.access_token);
        setUser(response.user);
        setIsAuthenticated(true);
        scheduleRefresh(response.expires_in);
      } catch (err) {
        if (err instanceof GatewayError && err.status === 401) {
          // Normal case: no active session (user hasn't logged in)
          // isAuthenticated stays false; protected layout will redirect to login
          setIsAuthenticated(false);
        }
        // Other errors (500, network failure): also treat as unauthenticated
        // User can retry login; losing auth state is safer than showing wrong data
      } finally {
        // Always resolve isLoading — components need to know the check is complete
        // even if it failed, so they can redirect or show the login button
        setIsLoading(false);
      }
    }

    checkAuth();

    // Cleanup: clear silent refresh timer when the component unmounts
    // WHY: Without cleanup, timers fire after unmount and try to set state
    // on an unmounted component, causing "Can't perform a React state update on
    // an unmounted component" warnings and potential memory leaks
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Empty deps: runs once on mount. We DON'T want to re-run on token changes
  // because the silent refresh timer handles re-authentication mid-session.

  // ── Public API ──────────────────────────────────────────────────────────

  /**
   * setTokens — called by CallbackPage after successful OIDC code exchange
   *
   * WHY a separate function (not direct setState): Encapsulates the side effect
   * of scheduling the silent refresh timer. CallbackPage only needs to know
   * "here are the tokens" — not how to schedule refreshes.
   */
  const setTokens = (token: string, newUser: UserProfile, expiresIn: number) => {
    setAccessToken(token);
    setUser(newUser);
    setIsAuthenticated(true);
    setIsLoading(false);
    scheduleRefresh(expiresIn);
  };

  /**
   * logout — revoke session and clear state
   *
   * WHY POST /auth/logout (not just clear state): S9 revokes the httpOnly refresh
   * token cookie server-side. If we only clear client state, the cookie persists
   * and the next page load would silently re-authenticate the "logged out" user.
   */
  const logout = async () => {
    // Clear the silent refresh timer immediately
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }

    // Clear state first — even if the logout API call fails, we clear locally
    // WHY: Better to be "logged out" locally and have a stale server cookie
    // than to stay "logged in" locally after a failed logout request.
    const currentToken = accessToken;
    setAccessToken(null);
    setUser(null);
    setIsAuthenticated(false);

    // Then revoke the server-side httpOnly refresh token cookie
    try {
      if (currentToken) {
        const gw = createGateway(currentToken);
        await gw.logout();
      }
    } catch {
      // Logout API errors are non-fatal — local state is already cleared above
      // The httpOnly cookie will expire naturally (15 min → 1 day depending on config)
    }
  };

  return (
    <AuthContext.Provider
      value={{ isLoading, isAuthenticated, accessToken, user, setTokens, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ── Consumer hook (see hooks/useAuth.ts) ─────────────────────────────────

/**
 * useAuthContext — internal hook for the context value
 * External consumers use useAuth() from hooks/useAuth.ts (cleaner import path)
 */
export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error(
      "useAuthContext must be used inside <AuthProvider>. " +
        "Did you forget to wrap the app in AuthProvider in providers.tsx?",
    );
  }
  return ctx;
}
