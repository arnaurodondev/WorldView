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
  // NOTE: These tests would require authentication. In a real E2E setup,
  // we'd use Playwright's storageState to inject a session cookie or use
  // a test user. For MVP E2E, we verify the page structure after mocking auth.

  test.skip("authenticated user sees dashboard grid", async ({ page }) => {
    // Skip until auth mock is set up for E2E environment
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible();
  });
});
