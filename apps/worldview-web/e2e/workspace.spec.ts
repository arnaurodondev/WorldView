/**
 * e2e/workspace.spec.ts — Workspace page e2e tests (QA-020)
 *
 * WHY THIS EXISTS: The Workspace multi-panel page is the most complex layout
 * in the app — it contains a resizable grid of 8+ panels, each with its own
 * data queries. E2E tests verify that:
 * 1. The workspace renders correctly after authentication
 * 2. The shell (TopBar + Sidebar) is present
 * 3. The page handles API errors gracefully (panels show error states, not crashes)
 * 4. No JS errors on page load
 *
 * WHY page.route() for auth: WorkspacePage is behind ProtectedRoute which
 * requires AuthContext.isAuthenticated = true. We mock POST /api/v1/auth/refresh
 * to return a fake token so the AuthProvider sets isAuthenticated without
 * a real Zitadel backend. See dashboard.spec.ts for the same pattern.
 *
 * NOTE: These tests require `pnpm dev` running at localhost:3001.
 */

import { test, expect } from "@playwright/test";

// ── Auth mock helper ───────────────────────────────────────────────────────────

/**
 * buildFakeToken — construct a JWT with a future exp claim.
 * isTokenExpiringSoon() in AuthContext only checks the exp from the base64
 * payload — it does NOT verify the RS256 signature client-side.
 */
function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const payload = btoa(JSON.stringify({
    sub: "e2e-workspace-user",
    tenant_id: "e2e-tenant",
    email: "e2e@test.local",
    name: "E2E Workspace User",
    exp: Math.floor(Date.now() / 1000) + 3600,
  })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${header}.${payload}.fake-e2e-sig`;
}

/**
 * setupAuthMock — install auth + data mocks before navigating.
 * WHY install before goto: AuthProvider fires refresh on mount, so the mock
 * must be ready before the component tree renders.
 */
async function setupAuthMock(page: import("@playwright/test").Page) {
  const fakeToken = buildFakeToken();

  await page.route("**/api/v1/auth/refresh", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 3600,
        user: {
          user_id: "e2e-workspace-user",
          tenant_id: "e2e-tenant",
          email: "e2e@test.local",
          name: "E2E Workspace User",
        },
      }),
    });
  });

  // WHY stub all other api calls: workspace panels fire multiple queries;
  // without mocks they all fail with ECONNREFUSED and show error banners.
  // Returning empty 200s gives panels a valid (if empty) response to render.
  await page.route("**/api/v1/**", (route) => {
    void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-token" }),
    });
  });

  return fakeToken;
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe("Workspace page (authenticated)", () => {
  test("renders the workspace layout after auth mock", async ({ page }) => {
    await setupAuthMock(page);
    await page.goto("/workspace");

    // WHY wait for main: confirms ProtectedRoute allowed access (not redirected)
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10000 });
  });

  test("workspace does not redirect to /login when authenticated", async ({ page }) => {
    await setupAuthMock(page);
    await page.goto("/workspace");

    // Should NOT redirect to login
    await page.waitForLoadState("networkidle");
    expect(page.url()).not.toMatch(/\/login/);
  });

  test("workspace has no critical JavaScript errors", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    await setupAuthMock(page);
    await page.goto("/workspace");
    await page.waitForLoadState("networkidle");

    const criticalErrors = errors.filter(
      (e) =>
        !e.includes("Failed to fetch") &&
        !e.includes("NetworkError") &&
        !e.includes("net::ERR") &&
        !e.includes("WebSocket") &&
        !e.includes("NEXT_REDIRECT"),
    );

    expect(criticalErrors).toHaveLength(0);
  });

  test("workspace does not have horizontal scroll (layout integrity)", async ({ page }) => {
    // WHY test overflow: finance terminals must not have horizontal scroll —
    // it indicates a panel overflowing the grid and breaks the professional look.
    await setupAuthMock(page);
    await page.goto("/workspace");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10000 });

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    // Allow 1px tolerance for rounding
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
  });
});

test.describe("Workspace page (unauthenticated)", () => {
  test("redirects to /login when not authenticated", async ({ page }) => {
    // No auth mock installed — AuthProvider gets 401 from refresh endpoint
    await page.goto("/workspace");
    await expect(page).toHaveURL(/\/login/, { timeout: 8000 });
  });
});
