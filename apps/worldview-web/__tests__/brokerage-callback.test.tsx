/**
 * __tests__/brokerage-callback.test.tsx — Unit tests for the SnapTrade OAuth callback page
 *
 * WHY THIS EXISTS: BrokerageCallbackPage has 4 distinct UI states:
 *   idle/loading → shown while the activation API call is in flight
 *   success      → shown when S9 activates the connection successfully
 *   error        → shown when URL params are missing OR the API call fails
 *
 * Without tests, silent regressions could leave users stranded on the callback
 * URL with no feedback after a SnapTrade OAuth redirect. Each state has specific
 * copy and CTAs that need deterministic verification.
 *
 * WHY SEPARATE FILE (not in brokerage.test.tsx):
 * The callback page requires per-test useSearchParams configuration to simulate
 * different URL param scenarios (success: all 4 params, missing-params: empty,
 * etc.). The mutable-variable pattern used in callback-page.test.tsx is cleaner
 * in an isolated file than overriding the static mock already set in brokerage.test.tsx.
 *
 * WHO USES IT: SnapTrade portal redirects here after the user completes OAuth.
 * DATA SOURCE: S9 GET /api/v1/brokerage-connections/{id}/callback (mocked)
 * DESIGN REFERENCE: PRD-0022 §6.6, app/(app)/portfolio/brokerage/callback/page.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ── Navigation mock ───────────────────────────────────────────────────────────
// WHY mutable variable (not inline URLSearchParams): each test needs different
// URL params — success: all 4 required params, missing-params: empty, etc.
// The factory returns the variable by reference so reassigning it before render
// (mockSearchParams = new URLSearchParams(...)) takes effect in that test.
const mockRouterPush = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    push: mockRouterPush,
    replace: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/portfolio/brokerage/callback"),
  // WHY arrow returning variable (not inline): captures the mutable reference
  // so per-test assignment is visible when useSearchParams() is called.
  useSearchParams: vi.fn(() => mockSearchParams),
}));

// ── Auth mock ─────────────────────────────────────────────────────────────────
// WHY provide accessToken: the callback page guards on !!accessToken before
// calling the activation API. Tests need a non-null token so the effect fires.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    accessToken: "test-token",
    isAuthenticated: true,
    isLoading: false,
    user: {
      user_id: "u1",
      tenant_id: "t1",
      email: "trader@example.com",
      name: "Test Trader",
      avatar_url: null,
    },
    setTokens: vi.fn(),
    logout: vi.fn(),
  })),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// WHY mock activateBrokerageConnection: it makes an HTTP call to S9 which
// activates the pending brokerage connection. Each test scenario configures
// whether this resolves successfully, rejects, or never resolves (loading state).
const mockActivateBrokerageConnection = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({
    activateBrokerageConnection: mockActivateBrokerageConnection,
    // WHY refreshToken mock: AuthContext calls this on mount; without a mock
    // it would throw and break component tree initialization.
    refreshToken: vi.fn().mockResolvedValue({
      access_token: "test-token",
      user: { user_id: "u1", tenant_id: "t1", email: "t@e.com", name: "T", avatar_url: null },
      expires_in: 900,
    }),
    logout: vi.fn(),
  })),
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

// ── Fixtures ──────────────────────────────────────────────────────────────────

/**
 * VALID_CALLBACK_PARAMS — the four URL query params that SnapTrade appends to
 * our redirect_uri after a successful OAuth authorization.
 *   connectionId      — our pre-created connection ID (embedded in redirect_uri)
 *   authorizationId   — SnapTrade's authorization identifier
 *   userId            — SnapTrade's user identifier
 *   sessionId         — SnapTrade's session identifier
 */
const VALID_CALLBACK_PARAMS = new URLSearchParams({
  connectionId: "conn-abc123",
  authorizationId: "auth-xyz789",
  userId: "snaptrade-user-001",
  sessionId: "session-def456",
});

/**
 * ACTIVATED_CONNECTION — minimal S9 response after successful activation.
 * Status transitions from "pending" → "active" after S9 processes the callback.
 */
const ACTIVATED_CONNECTION = {
  connection_id: "conn-abc123",
  portfolio_id: "port-1",
  brokerage_name: "Interactive Brokers",
  status: "active" as const,
  last_synced_at: null,
  created_at: "2026-04-23T00:00:00Z",
};

// ── Test helpers ───────────────────────────────────────────────────────────────

/**
 * makeWrapper — fresh QueryClient per test.
 * WHY retry: false: prevents hanging tests due to TanStack Query retry delays.
 * (The callback page uses useEffect + useState, not TanStack Query directly,
 * but the wrapper is still required for any child components in the tree.)
 */
function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

// ── Import (after mocks) ──────────────────────────────────────────────────────
// WHY dynamic import after vi.mock(): avoids hoisting issues — the module is
// captured with all mocks already in place.
const BrokerageCallbackPage = (
  await import("@/app/(app)/portfolio/brokerage/callback/page")
).default;

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("BrokerageCallbackPage — SnapTrade OAuth callback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset to empty params so each test starts clean
    mockSearchParams = new URLSearchParams();
  });

  // ── State: loading ─────────────────────────────────────────────────────────

  it("shows loading UI while activation is in progress", () => {
    // WHY never-resolve: keeps the component in loading state for this assertion.
    // A resolved promise would immediately transition to success/error.
    mockActivateBrokerageConnection.mockReturnValue(new Promise(() => {}));
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    // Loading state is the visible UI while the activation API call is in flight
    expect(
      screen.getByText("Activating your brokerage connection…"),
    ).toBeInTheDocument();
  });

  // ── State: success ─────────────────────────────────────────────────────────

  it("shows success confirmation after activation completes", async () => {
    mockActivateBrokerageConnection.mockResolvedValue(ACTIVATED_CONNECTION);
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText("Brokerage account connected successfully!"),
      ).toBeInTheDocument();
    });

    // WHY check secondary copy: users need to know their data will appear soon
    // (sync is async — transactions don't appear instantly after connection).
    // PLAN-0122 W-C (R-9/R-10): the misleading "begin syncing shortly" copy was
    // replaced with explicit, honest timing (minutes → up to a few hours + the
    // "Sync Now" recovery hint). The heading above stays pinned.
    expect(screen.getByText(/few minutes/i)).toBeInTheDocument();
    expect(screen.getByText(/few hours/i)).toBeInTheDocument();
    expect(screen.getByText(/Sync Now/i)).toBeInTheDocument();
  });

  it("renders Go to Portfolio button in success state", async () => {
    mockActivateBrokerageConnection.mockResolvedValue(ACTIVATED_CONNECTION);
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // The primary CTA guides users to the portfolio page where the new
      // connection will appear in the Brokerages tab
      expect(
        screen.getByRole("button", { name: /go to portfolio/i }),
      ).toBeInTheDocument();
    });
  });

  it("navigates to /portfolio when Go to Portfolio is clicked", async () => {
    const user = userEvent.setup();
    mockActivateBrokerageConnection.mockResolvedValue(ACTIVATED_CONNECTION);
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /go to portfolio/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /go to portfolio/i }));

    // WHY /portfolio (not /dashboard): the user arrived here from the Portfolio
    // page's Brokerages tab. Taking them back to Portfolio lets them immediately
    // see the newly connected broker in the list.
    expect(mockRouterPush).toHaveBeenCalledWith("/portfolio");
  });

  // ── State: error — missing params ──────────────────────────────────────────

  it("shows error UI immediately when required URL params are missing", async () => {
    // WHY empty searchParams: simulates a user who navigated directly to the
    // callback URL without completing the SnapTrade OAuth flow (e.g., bookmarked
    // the URL, or a URL truncation issue in the redirect).
    mockSearchParams = new URLSearchParams(); // no connectionId, authorizationId, etc.

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(/Missing required callback parameters/i),
      ).toBeInTheDocument();
    });

    // WHY assert no API call: calling activation without params would return a
    // 404 from S9 (connectionId is required). Preventing the call is correct.
    expect(mockActivateBrokerageConnection).not.toHaveBeenCalled();
  });

  // ── State: error — API failure ─────────────────────────────────────────────

  it("shows the API error message when activation fails", async () => {
    // WHY specific error message: BrokerageCallbackPage surfaces the error.message
    // directly so users see actionable text (e.g., "Authorization session expired")
    // instead of a generic failure notice.
    mockActivateBrokerageConnection.mockRejectedValue(
      new Error("Authorization session expired"),
    );
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText("Authorization session expired"),
      ).toBeInTheDocument();
    });
  });

  it("renders Back to Portfolio and Try Again buttons in error state", async () => {
    mockActivateBrokerageConnection.mockRejectedValue(new Error("API error"));
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      // WHY two buttons: Back to Portfolio = give up; Try Again = reconnect.
      // Both navigate to /portfolio where the Connect Brokerage button lives.
      expect(
        screen.getByRole("button", { name: /back to portfolio/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /try again/i }),
      ).toBeInTheDocument();
    });
  });

  // ── State: v4 portal callback (connection_id, no userId/sessionId) ─────────

  it("allows activation when userId and sessionId are absent (v4 portal)", async () => {
    // WHY this test: SnapTrade Connection Portal v4 dropped userId and sessionId
    // from the callback redirect, and renamed authorizationId → connection_id.
    // The page must still complete activation in that case — JWT ownership is
    // sufficient anti-spoofing without those legacy fields.
    mockActivateBrokerageConnection.mockResolvedValue(ACTIVATED_CONNECTION);
    // Only the two v4 params: our connectionId + SnapTrade's connection_id.
    mockSearchParams = new URLSearchParams({
      connectionId: "conn-v4-001",
      connection_id: "snap-v4-auth-002",
    });

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    // No "Missing required callback parameters" error
    await waitFor(() => {
      expect(
        screen.getByText("Brokerage account connected successfully!"),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/Missing required callback parameters/i),
    ).not.toBeInTheDocument();

    // Activation fired — connection_id forwarded under the legacy
    // "authorizationId" key, userId/sessionId fall back to empty strings.
    expect(mockActivateBrokerageConnection).toHaveBeenCalledTimes(1);
    expect(mockActivateBrokerageConnection).toHaveBeenCalledWith("conn-v4-001", {
      authorizationId: "snap-v4-auth-002",
      userId: "",
      sessionId: "",
    });
  });

  // ── Strict Mode double-fire guard ─────────────────────────────────────────

  it("calls the activation API exactly once (hasActivated guard prevents double-fire)", async () => {
    // WHY this test: React 18 Strict Mode runs effects twice in development.
    // The hasActivated ref (set to true BEFORE the async call) prevents a
    // second activation attempt on the second effect invocation. A second call
    // would fail because the connection is already active after the first call.
    mockActivateBrokerageConnection.mockResolvedValue(ACTIVATED_CONNECTION);
    mockSearchParams = VALID_CALLBACK_PARAMS;

    render(<BrokerageCallbackPage />, { wrapper: makeWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText("Brokerage account connected successfully!"),
      ).toBeInTheDocument();
    });

    // Exactly one call regardless of Strict Mode double-fire
    expect(mockActivateBrokerageConnection).toHaveBeenCalledTimes(1);

    // WHY verify exact params: ensures the correct connection ID and SnapTrade
    // params are forwarded to S9. Wrong params would return a 404 or auth failure.
    expect(mockActivateBrokerageConnection).toHaveBeenCalledWith("conn-abc123", {
      authorizationId: "auth-xyz789",
      userId: "snaptrade-user-001",
      sessionId: "session-def456",
    });
  });
});
