/**
 * e2e/dashboard.spec.ts — Dashboard user journey e2e tests
 *
 * WHY THIS EXISTS: The dashboard is the entry point after login. These tests
 * verify that the page loads without crashing and key structural elements are
 * present — important for regression detection after new widget additions.
 *
 * NOTE: These tests require `pnpm dev` running at localhost:3001.
 * Unauthenticated tests work without a real S9 backend since they only
 * test what the page shows before data loads.
 */

import { test, expect } from "@playwright/test";

test.describe("Dashboard (unauthenticated redirect)", () => {
  test("redirects to login when not authenticated", async ({ page }) => {
    // The dashboard is behind ProtectedRoute — unauthenticated users redirect
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("login page has no JavaScript errors on load", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Filter out expected errors (e.g., network request to Zitadel that fails in test env)
    const criticalErrors = errors.filter(
      (e) =>
        !e.includes("Failed to fetch") &&
        !e.includes("NetworkError") &&
        !e.includes("net::ERR"),
    );

    expect(criticalErrors).toHaveLength(0);
  });
});

test.describe("Dashboard layout (visual checks)", () => {
  // WHY page.route() for auth mock: The AuthProvider on mount calls
  // POST /api/v1/auth/refresh to check if the httpOnly cookie session is valid.
  // We intercept this with a fake 200 response so isAuthenticated becomes true
  // without needing a real Zitadel backend. The token only needs a valid
  // base64 payload with a future exp claim (isTokenExpiringSoon checks exp only).

  /**
   * buildFakeToken — construct a JWT-shaped string with a far-future exp.
   * WHY: AuthContext's isTokenExpiringSoon() decodes only the payload to check exp.
   * It does not verify the RS256 signature client-side. So a fake sig is fine here.
   */
  function buildFakeToken(): string {
    const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
      .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
    const payload = btoa(JSON.stringify({
      sub: "e2e-test-user",
      tenant_id: "e2e-test-tenant",
      email: "e2e@test.local",
      name: "E2E Test User",
      exp: Math.floor(Date.now() / 1000) + 3600, // valid for 1 hour
    })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
    return `${header}.${payload}.fake-e2e-sig`;
  }

  test("authenticated user sees dashboard shell", async ({ page }) => {
    // WHY mock before goto: page.route() intercepts are registered before
    // navigation; the AuthProvider fires refresh on mount so the mock must
    // be in place before the component tree renders.
    const fakeToken = buildFakeToken();

    // Mock the auth refresh endpoint — returns a valid session
    await page.route("**/api/v1/auth/refresh", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: fakeToken,
          expires_in: 3600,
          user: {
            user_id: "e2e-test-user",
            tenant_id: "e2e-test-tenant",
            email: "e2e@test.local",
            name: "E2E Test User",
          },
        }),
      });
    });

    // Mock S9 data endpoints so dashboard widgets don't show error states
    // WHY: Without mocks, TanStack Query fires real requests to S9 which
    // is not running in the e2e environment → all widgets show error banners.
    await page.route("**/api/v1/**", (route) => {
      // Default stub: return empty success response for all other API calls
      void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    // Also mock the WebSocket auth token (AlertStreamContext uses this)
    await page.route("**/api/v1/auth/ws-token", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ token: "fake-ws-token" }),
      });
    });

    await page.goto("/dashboard");
    // Wait for the auth check to resolve — the dashboard should render the shell
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10000 });
  });

  test("dashboard does not crash with mocked auth (no JS errors)", async ({ page }) => {
    // WHY test for JS errors: finance terminals must be crash-free.
    // This catches unhandled promise rejections and TypeError crashes
    // that would otherwise silently break widgets.
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const fakeToken = buildFakeToken();

    await page.route("**/api/v1/auth/refresh", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: fakeToken,
          expires_in: 3600,
          user: { user_id: "e2e-test-user", tenant_id: "e2e-test-tenant", email: "e2e@test.local", name: "E2E Test User" },
        }),
      });
    });

    await page.route("**/api/v1/**", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Filter expected "fetch failed" errors from unmocked endpoints
    const criticalErrors = errors.filter(
      (e) => !e.includes("Failed to fetch") && !e.includes("NetworkError") && !e.includes("net::ERR"),
    );
    expect(criticalErrors).toHaveLength(0);
  });
});
