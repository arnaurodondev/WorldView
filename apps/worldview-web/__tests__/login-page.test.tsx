/**
 * __tests__/login-page.test.tsx — Unit tests for the /login page dev-login gating.
 *
 * WHY THIS EXISTS: The login page decides between the real Zitadel OIDC flow and
 * a local "Dev Login" shortcut based on probing the gateway's OIDC-init route
 * (`GET /api/v1/auth/login`). A regression here blocks ALL local UI access
 * (you cannot log in), so the probe → button-visibility contract is covered
 * explicitly.
 *
 * The contract under test (see app/login/page.tsx):
 *   • probe returns 502 (oidc_discovery_failed) → SHOW "Dev Login", HIDE Zitadel
 *   • probe returns 302 (OIDC configured)       → HIDE "Dev Login", SHOW Zitadel
 *   • clicking Dev Login → calls gw.devLogin(), hydrates auth, redirects
 *
 * WHY mock gateway + fetch + next/navigation: the page calls createGateway()
 * (devLogin), global fetch (the probe), and useRouter()/useSearchParams(). We
 * stub all three so the test runs with no S9 server and no real Next runtime.
 *
 * DATA SOURCE: Mocked createGateway (lib/gateway.ts), mocked global.fetch.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import type { AuthCallbackResponse } from "@/types/api";

// ── next/navigation mock ──────────────────────────────────────────────────────
// WHY: the page uses useRouter() (for redirect after login) and useSearchParams()
// (to read redirect_to). Neither exists outside the Next.js runtime.
const mockReplace = vi.fn();
const mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
}));

// ── useAuth mock ──────────────────────────────────────────────────────────────
// WHY: the page calls setTokens() from the auth context after a successful
// dev-login. We assert it is invoked with the demo JWT.
const mockSetTokens = vi.fn();
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ setTokens: mockSetTokens }),
}));

// ── gateway mock ──────────────────────────────────────────────────────────────
// WHY: handleDevLogin() calls createGateway().devLogin(). GatewayError is used
// by the page to detect the 403 "OIDC actually configured" case.
const mockDevLogin = vi.fn();
vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ devLogin: mockDevLogin })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "GatewayError";
      this.status = status;
    }
  },
}));

// Import AFTER mocks are registered so the page picks up the stubs.
import LoginPage from "@/app/login/page";

// ── Test helpers ──────────────────────────────────────────────────────────────

/** Build a Response-like stub for the OIDC-init probe with a given status. */
function probeResponse(status: number): Response {
  // Only `.status` is read by the probe; a minimal object satisfies the contract.
  return { status } as Response;
}

const DEV_LOGIN_RESPONSE: AuthCallbackResponse = {
  access_token: "header.payload.signature",
  expires_in: 3600,
  user: {
    user_id: "user-dev",
    tenant_id: "tenant-dev",
    email: "dev@worldview.local",
    name: "Dev User",
    avatar_url: null,
  },
};

describe("LoginPage dev-login gating", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDevLogin.mockResolvedValue(DEV_LOGIN_RESPONSE);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows Dev Login (and hides Zitadel) when the OIDC probe returns 502", async () => {
    // Gateway reports OIDC is unconfigured → dev login must be offered.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(probeResponse(502)),
    );

    render(<LoginPage />);

    // The dev-login button appears once the async probe resolves.
    const devButton = await screen.findByRole("button", {
      name: /dev login/i,
    });
    expect(devButton).toBeInTheDocument();
    // The real OIDC button must NOT be shown when dev login is offered.
    expect(
      screen.queryByRole("button", { name: /sign in with zitadel/i }),
    ).not.toBeInTheDocument();
  });

  it("clicking Dev Login calls devLogin(), hydrates auth, and redirects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(probeResponse(502)),
    );

    render(<LoginPage />);

    const devButton = await screen.findByRole("button", {
      name: /dev login/i,
    });

    await act(async () => {
      fireEvent.click(devButton);
    });

    await waitFor(() => {
      expect(mockDevLogin).toHaveBeenCalledTimes(1);
    });
    // Auth context hydrated with the demo JWT (same shape as real OIDC callback).
    expect(mockSetTokens).toHaveBeenCalledWith(
      DEV_LOGIN_RESPONSE.access_token,
      DEV_LOGIN_RESPONSE.user,
      DEV_LOGIN_RESPONSE.expires_in,
    );
    // Redirect into the app (default destination when no redirect_to param).
    expect(mockReplace).toHaveBeenCalledTimes(1);
  });

  it("shows the Zitadel button (and hides Dev Login) when the OIDC probe returns 302", async () => {
    // Gateway redirects to Zitadel → real OIDC works → dev login must be hidden.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(probeResponse(302)),
    );

    render(<LoginPage />);

    // Real OIDC CTA is present.
    const zitadelButton = await screen.findByRole("button", {
      name: /sign in with zitadel/i,
    });
    expect(zitadelButton).toBeInTheDocument();

    // Give any pending probe state update a chance to flush, then assert the
    // dev-login button is absent.
    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: /dev login/i }),
      ).not.toBeInTheDocument();
    });
  });
});

// ── Zitadel authorize-URL scope (refresh-token fix, audit 2026-07-19) ──────────
//
// WHY THIS EXISTS: Zitadel only issues a refresh_token when `offline_access` is
// among the authorize scopes. If initiateLogin() omits it, S9 never receives a
// refresh_token, sets no httpOnly cookie, and every silent refresh 401s → the
// user is bounced to the sign-in page on each access-token expiry. This test
// pins `offline_access` into the authorize URL so the regression cannot recur.
describe("LoginPage Zitadel authorize URL", () => {
  // Capture the URL passed to window.location.replace() during initiateLogin().
  let replacedUrl = "";

  beforeEach(() => {
    vi.clearAllMocks();
    replacedUrl = "";

    // The page reads these NEXT_PUBLIC_* vars to build the authorize URL.
    vi.stubEnv("NEXT_PUBLIC_ZITADEL_URL", "https://example.zitadel.cloud");
    vi.stubEnv("NEXT_PUBLIC_ZITADEL_CLIENT_ID", "test-client-id");

    // 302 probe → the real "Sign in with Zitadel" button is rendered.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(probeResponse(302)));

    // Replace window.location with a stub that records replace() and exposes
    // origin (read by the page to build the callback URL). jsdom's real
    // location.replace is not spy-able, so we swap the whole object.
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        origin: "https://app.worldview-labs.com",
        replace: (url: string) => {
          replacedUrl = url;
        },
      },
    });

    // Deterministic crypto so PKCE verifier/challenge generation does not depend
    // on the test environment's WebCrypto availability.
    vi.stubGlobal("crypto", {
      getRandomValues: (arr: Uint8Array) => {
        for (let i = 0; i < arr.length; i++) arr[i] = i % 256;
        return arr;
      },
      subtle: {
        digest: async () => new Uint8Array(32).buffer,
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("requests the offline_access scope so Zitadel returns a refresh_token", async () => {
    render(<LoginPage />);

    const zitadelButton = await screen.findByRole("button", {
      name: /sign in with zitadel/i,
    });

    await act(async () => {
      fireEvent.click(zitadelButton);
    });

    await waitFor(() => {
      expect(replacedUrl).toContain("/oauth/v2/authorize");
    });

    // Parse the scope param and assert all four scopes are present. Query-string
    // encoding turns spaces into "+" / "%20"; URLSearchParams decodes both.
    const query = replacedUrl.split("?")[1] ?? "";
    const scope = new URLSearchParams(query).get("scope") ?? "";
    expect(scope.split(/\s+/)).toEqual(
      expect.arrayContaining(["openid", "profile", "email", "offline_access"]),
    );
  });
});
