/**
 * __tests__/callback-page.test.tsx — Unit tests for the OIDC callback page
 *
 * WHY THIS EXISTS: CallbackPage handles the most security-sensitive step of the
 * PKCE auth flow: exchanging the authorization code for tokens. Tests verify:
 * 1. Successful exchange → setTokens called + navigate to destination
 * 2. Error param (user cancelled or IdP error) → user-friendly error message
 * 3. State mismatch (CSRF check failed) → security error shown, no navigation
 *
 * WHY mock sessionStorage: The callback reads pkce_verifier and pkce_state
 * from sessionStorage (written by the login page during flow initiation).
 * Tests seed sessionStorage directly to simulate the login→callback handoff.
 *
 * WHY mock useAuth (not mount AuthProvider): CallbackPage only needs setTokens().
 * Mounting the full AuthProvider would trigger a POST /auth/refresh on mount,
 * making this a broader integration test. A direct hook mock keeps this unit-focused.
 *
 * DATA SOURCE: S9 POST /api/v1/auth/callback (mocked via gateway)
 * DESIGN REFERENCE: PRD-0028 §6.6.1 PKCE Callback, app/callback/page.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import CallbackPage from "@/app/callback/page";

// ── Next.js navigation mock ───────────────────────────────────────────────────
// WHY mutable variable (not inline new URLSearchParams()): each test needs
// different URL params — success: code+state, error: error param, mismatch: wrong state.
// The mock factory captures the variable by reference so reassigning it
// before render changes what useSearchParams() returns in that test.
const mockRouterReplace = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  // WHY arrow returning mockSearchParams (not inline object): captures the
  // mutable reference so test setup via `mockSearchParams = new URLSearchParams(...)`
  // is visible to the mocked hook when it is called during render.
  useSearchParams: vi.fn(() => mockSearchParams),
  useRouter: vi.fn(() => ({
    replace: mockRouterReplace,
    push: vi.fn(),
    prefetch: vi.fn(),
  })),
  usePathname: vi.fn(() => "/callback"),
}));

// ── Gateway mock ──────────────────────────────────────────────────────────────
// WHY: exchangeCode makes a real HTTPS call to S9 → Zitadel. Unit tests must
// not touch real infrastructure. The mock resolves/rejects per-test scenario.
const mockExchangeCode = vi.fn();

vi.mock("@/lib/gateway", () => ({
  createGateway: vi.fn(() => ({ exchangeCode: mockExchangeCode })),
  // WHY replicate GatewayError: CallbackPage imports the class to check `instanceof`.
  // Returning a plain Error from mockExchangeCode would bypass that check.
  GatewayError: class GatewayError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "GatewayError";
      this.status = status;
    }
  },
}));

// ── Auth hook mock ────────────────────────────────────────────────────────────
const mockSetTokens = vi.fn();

vi.mock("@/hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({
    setTokens: mockSetTokens,
    isLoading: false,
    isAuthenticated: false,
    accessToken: null,
    user: null,
    logout: vi.fn(),
  })),
}));

// ── Test setup ────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks();
  // Reset per-test URL params to empty (each test sets its own params)
  mockSearchParams = new URLSearchParams();
  // Clear PKCE session state seeded in previous tests
  sessionStorage.clear();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("CallbackPage — OIDC code exchange", () => {
  it("calls setTokens and navigates on successful token exchange", async () => {
    /**
     * Happy path: Zitadel redirected here with code + matching state.
     * LoginPage stored pkce_state and pkce_verifier in sessionStorage.
     * S9 exchanges code+verifier for an access token.
     * CallbackPage stores the token in AuthContext and navigates to destination.
     */

    // Seed the PKCE session values that LoginPage would have stored
    sessionStorage.setItem("pkce_state", "csrf-state-token-abc");
    sessionStorage.setItem("pkce_verifier", "code-verifier-xyz");
    // Simulate no stored redirect target (falls back to "/")
    sessionStorage.removeItem("auth_redirect_to");

    // URL that Zitadel returns — state must match what LoginPage stored
    mockSearchParams = new URLSearchParams(
      "code=auth-code-from-zitadel&state=csrf-state-token-abc",
    );

    // S9 responds with access token and user profile
    mockExchangeCode.mockResolvedValue({
      access_token: "eyJhbGciOiJSUzI1NiJ9.test.signature",
      user: {
        user_id: "user-001",
        tenant_id: "tenant-001",
        email: "trader@hedge.fund",
        name: "Hedge Fund Trader",
        avatar_url: null,
      },
      expires_in: 900, // 15 minutes
    });

    render(<CallbackPage />);

    // Wait for the async useEffect (code exchange) to complete
    await waitFor(() => {
      expect(mockSetTokens).toHaveBeenCalledTimes(1);
    });

    // setTokens must be called with the token, user, and expiry from S9
    expect(mockSetTokens).toHaveBeenCalledWith(
      "eyJhbGciOiJSUzI1NiJ9.test.signature",
      expect.objectContaining({ email: "trader@hedge.fund" }),
      900,
    );

    // After success, must navigate away from /callback to avoid re-exchange.
    // WHY "/dashboard" (not "/"): sanitizeRedirect(null) returns "/dashboard"
    // as the safe fallback when no auth_redirect_to was stored in sessionStorage.
    // The root "/" is the public landing page; authenticated users land on the dashboard.
    expect(mockRouterReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("shows user-facing error message when Zitadel returns an error param", async () => {
    /**
     * Zitadel returns ?error=access_denied when:
     * - User clicked "cancel" on the Zitadel consent screen
     * - User's account is suspended or blocked
     * - The OAuth scope was rejected
     *
     * The page must show a human-readable message and NOT navigate.
     * It must NOT log the raw error string (KNOWN_OIDC_ERRORS whitelist prevents injection).
     */
    mockSearchParams = new URLSearchParams("error=access_denied");

    render(<CallbackPage />);

    // "missing_code" error type is used for any ?error= param (includes cancellation)
    await waitFor(() => {
      expect(
        screen.getByText(/Authentication was cancelled or failed/i),
      ).toBeInTheDocument();
    });

    // Must offer the user a way to try again
    expect(screen.getByRole("link", { name: /Try again/i })).toBeInTheDocument();

    // Must NOT complete the exchange or navigate when auth fails
    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(mockRouterReplace).not.toHaveBeenCalled();
  });

  it("shows security error and blocks navigation when state parameter mismatches", async () => {
    /**
     * CSRF protection: The state param Zitadel echoes back must match the state
     * that LoginPage stored in sessionStorage. If they differ, it means:
     * - The callback URL was forged (attacker-controlled state)
     * - The session state was tampered with
     *
     * The page must show a "Security check failed" message and abort.
     * No token exchange, no navigation.
     */

    // Seed PKCE session as LoginPage would — with a different state than the URL carries
    sessionStorage.setItem("pkce_state", "legitimate-state-from-login-page");
    sessionStorage.setItem("pkce_verifier", "test-verifier");

    // URL carries a state that does NOT match what sessionStorage has
    mockSearchParams = new URLSearchParams(
      "code=some-code&state=attacker-controlled-state",
    );

    render(<CallbackPage />);

    await waitFor(() => {
      expect(screen.getByText(/Security check failed/i)).toBeInTheDocument();
    });

    // No exchange attempted, no navigation — auth flow aborted
    expect(mockExchangeCode).not.toHaveBeenCalled();
    expect(mockSetTokens).not.toHaveBeenCalled();
    expect(mockRouterReplace).not.toHaveBeenCalled();
  });
});
