/**
 * lib/api/auth.ts — Auth domain API (PKCE callback, refresh, logout, ws-token, dev-login).
 *
 * WHY split out: auth methods are exercised by AuthContext only — keeping them
 * isolated from the 100+ data-fetching methods makes the auth surface easier
 * to audit and reason about. PRD-0025 §8 is the canonical reference.
 */

import type { AuthCallbackResponse, WsTokenResponse } from "@/types/api";
import { apiFetch } from "./_client";

export function createAuthApi(t: string | undefined) {
  return {
    /**
     * exchangeCode — PKCE token exchange with S9
     *
     * WHY POST (not GET): The code_verifier is sensitive (it proves ownership of
     * the code_challenge sent during authorization). GET params appear in server
     * logs, proxy logs, and browser history. POST body is not logged or cached.
     *
     * WHY S9 handles the exchange (not direct Zitadel): S9 calls Zitadel's token
     * endpoint server-to-server, sets the httpOnly refresh cookie, and returns
     * only the access token to the browser. The refresh token never touches
     * browser-side JS — it stays in the httpOnly cookie (XSS-safe).
     */
    exchangeCode(params: {
      code: string;
      code_verifier: string;
      redirect_uri: string;
    }): Promise<AuthCallbackResponse> {
      return apiFetch<AuthCallbackResponse>("/v1/auth/callback", {
        method: "POST",
        body: params,
      });
    },

    /**
     * refreshToken — silent token refresh using httpOnly refresh token cookie
     * Called by AuthContext on 401 responses and on app mount
     */
    refreshToken(): Promise<AuthCallbackResponse> {
      return apiFetch<AuthCallbackResponse>("/v1/auth/refresh", {
        method: "POST",
        token: t,
      });
    },

    /**
     * logout — revoke refresh token and clear cookie
     */
    logout(): Promise<void> {
      return apiFetch<void>("/v1/auth/logout", {
        method: "POST",
        token: t,
      });
    },

    /**
     * getWsToken — get short-lived (30s) WebSocket auth token
     * Called by useAlertStream immediately before opening the WS connection.
     * The WS token goes in ?token= on the WS URL (browsers can't set WS headers).
     */
    getWsToken(): Promise<WsTokenResponse> {
      return apiFetch<WsTokenResponse>("/v1/auth/ws-token", { token: t });
    },

    /**
     * devLogin — skip Zitadel entirely; get a demo JWT from S9
     *
     * WHY THIS EXISTS: During local development, Zitadel is often not running.
     * S9 exposes POST /v1/auth/dev-login ONLY when OIDC discovery was skipped
     * (oidc_config=None). This endpoint returns the same shape as the real
     * callback response so AuthContext.setTokens() works identically.
     *
     * SECURITY: Returns 403 in production (where OIDC config IS loaded).
     * This method is only called by the login page "Dev Login" button.
     */
    devLogin(): Promise<AuthCallbackResponse> {
      return apiFetch<AuthCallbackResponse>("/v1/auth/dev-login", {
        method: "POST",
      });
    },
  };
}
