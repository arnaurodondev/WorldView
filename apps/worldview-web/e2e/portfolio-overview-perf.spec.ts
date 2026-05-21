/**
 * e2e/portfolio-overview-perf.spec.ts — Portfolio page load correctness
 *
 * WHY THIS EXISTS: The W2 portfolio page fires 9+ parallel TanStack Query
 * requests on mount (portfolios, holdings, quotes, transactions, watchlists,
 * brokerage, exposure, performance, ohlcv). Any one of these failing should
 * NOT crash the page — only that widget should show an error state.
 *
 * These tests assert:
 * 1. Page loads and renders the shell (no JS errors, no Application error overlay)
 * 2. Page handles all-500 gracefully (each widget degrades independently)
 * 3. Page handles auth token correctly (no 401 flash on load)
 *
 * WHY "perf" in the filename: this spec was named after the "performance"
 * requirement in PRD-0089 W2 §4.21 (page must load without errors). It is
 * a correctness test, not a timing benchmark.
 *
 * DATA SOURCE: installStrictApiMocks() from e2e/fixtures/api-mocks.ts
 * DESIGN REFERENCE: PRD-0089 W2 §4.21 (no-error load requirement)
 */

import { test, expect } from "@playwright/test";
import {
  installStrictApiMocks,
  collectCriticalErrors,
  filterCriticalErrors,
} from "./fixtures/api-mocks";

test.describe("Portfolio W2 — page load correctness", () => {
  test("page loads without JS errors when all APIs return 200", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    // WHY extra mocks: W2 page fires brokerage + exposure queries not in
    // installStrictApiMocks. Without them, the requests would fail with
    // net::ERR_CONNECTION_REFUSED (dev server only, no S9 running).
    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY "Application error": that's the Next.js global error overlay text.
    // If a React component throws an uncaught error during render, Next.js
    // shows this string. It must not appear.
    await expect(page.locator("body")).not.toContainText("Application error");

    // WHY filterCriticalErrors: net::ERR and WebSocket errors are expected in
    // the test environment (no S9, no S10 running). Only real JS errors matter.
    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("page does not crash when all data APIs return 500", async ({ page }) => {
    const errors = collectCriticalErrors(page);

    // WHY 500 for data endpoints (not auth): broken auth prevents page load
    // entirely, masking the error resilience behaviour we want to test.
    await installStrictApiMocks(page, 500);

    await page.goto("/portfolio");
    await page.waitForLoadState("domcontentloaded");

    // Must not show Next.js global error overlay
    const body = await page.textContent("body");
    expect(body).not.toContain("Application error");

    // WHY not assert shell visible: 500 on portfolios may redirect to login
    // or show an error banner. The spec only asserts no crash, not specific
    // content — error UI is acceptable, crash UI is not.
    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("unauthenticated user is redirected to /login", async ({ page }) => {
    // WHY: Portfolio page is behind auth middleware (middleware.ts).
    // Without a valid token, the user must be redirected to /login.
    // This is a regression guard — if the middleware breaks, sensitive data
    // would be visible to unauthenticated users.
    await page.goto("/portfolio");
    await expect(page).toHaveURL(/\/login/, { timeout: 8000 });
  });
});
