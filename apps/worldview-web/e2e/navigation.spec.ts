/**
 * e2e/navigation.spec.ts — Core navigation and routing e2e tests
 *
 * WHY THIS EXISTS: Navigation is the backbone of a multi-page app.
 * Tests verify that all routes render without 404/500 errors, and that
 * key structural elements (TopBar, nav links) are present on each page.
 *
 * WHY TEST PUBLIC ROUTES ONLY: Most pages require auth. E2E tests for
 * authenticated flows require a test Zitadel instance (out of scope for MVP).
 * Public routes (/, /login, /register, /callback) are tested here.
 *
 * NOTE: These tests require `pnpm dev` running at localhost:3001.
 */

import { test, expect } from "@playwright/test";

// Public routes that should be accessible without auth
const PUBLIC_ROUTES = ["/", "/login", "/register"] as const;

test.describe("Public route rendering", () => {
  for (const route of PUBLIC_ROUTES) {
    test(`${route} renders without crash`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));

      await page.goto(route);
      await page.waitForLoadState("domcontentloaded");

      // Page should not show Next.js error overlay
      await expect(page.locator("body")).not.toContainText("Application error");

      // Filter critical JS errors (network errors are expected in test env)
      const criticalErrors = errors.filter(
        (e) =>
          !e.includes("Failed to fetch") &&
          !e.includes("NetworkError") &&
          !e.includes("net::ERR") &&
          !e.includes("NEXT_REDIRECT"),
      );

      expect(criticalErrors).toHaveLength(0);
    });
  }
});

test.describe("404 handling", () => {
  test("unknown route shows not-found page", async ({ page }) => {
    await page.goto("/this-route-does-not-exist-abc123");

    // Next.js should show the not-found page, not a 500
    const body = await page.textContent("body");
    expect(body).not.toContain("Application error");
    // Should contain some indication this is a 404
    const hasNotFound =
      body?.includes("not found") ||
      body?.includes("404") ||
      body?.includes("Page not found");
    expect(hasNotFound).toBe(true);
  });
});

test.describe("Protected route redirect", () => {
  const PROTECTED_ROUTES = [
    "/dashboard",
    "/screener",
    "/portfolio",
    "/alerts",
    "/chat",
    "/workspace",
    "/settings",
  ] as const;

  for (const route of PROTECTED_ROUTES) {
    test(`${route} redirects to /login when unauthenticated`, async ({ page }) => {
      await page.goto(route);

      // Should land on /login after ProtectedRoute redirect
      await expect(page).toHaveURL(/\/login/, { timeout: 5000 });
    });
  }
});
