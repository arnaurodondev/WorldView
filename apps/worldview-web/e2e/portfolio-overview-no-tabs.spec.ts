/**
 * e2e/portfolio-overview-no-tabs.spec.ts — Assert W2 tab removal
 *
 * WHY THIS EXISTS: PRD-0089 W2 §4.19 removes all <Tabs> from the portfolio
 * overview page. Holdings, Transactions, and Watchlists each moved to dedicated
 * sub-routes (/portfolio/transactions, /watchlists). These tests confirm that
 * no tab buttons with those labels remain in the DOM after W2.
 *
 * WHY browser-level (not Vitest): Tabs are rendered server-side via Next.js RSC
 * and client-hydrated. We need to verify the final DOM, not just the component
 * props passed into the tab component (which may conditionally render tabs based
 * on feature flags or URL params injected at runtime).
 *
 * DATA SOURCE: Route mocks via page.route() — no real S9 running in e2e.
 * DESIGN REFERENCE: PRD-0089 W2 §4.19
 */

import { test, expect } from "@playwright/test";
import { forceAdvancedMode } from "./utils/forceAdvancedMode";
import {
  installStrictApiMocks,
  collectCriticalErrors,
  filterCriticalErrors,
} from "./fixtures/api-mocks";

// PLAN-0122 W-B (T-A-B-05): the portfolio page now defaults to SIMPLE. Every
// spec below asserts the full Advanced layout, so force Advanced before each
// navigation (R19 — no assertion weakened, only the mode that shows the layout).
test.beforeEach(async ({ page }) => {
  await forceAdvancedMode(page);
});

test.describe("Portfolio W2 — no tab buttons in DOM", () => {
  test("has no 'Holdings' tab button after W2 redesign", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    // WHY also mock brokerage + exposure: W2 page fires these queries on mount;
    // without mocks they'd fail loudly in the console, masking real errors.
    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**/exposure**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );
    await page.route("**/api/v1/portfolios/**/performance**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );
    await page.route("**/api/v1/portfolios/**/bundle**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY role=tab: the old W1 layout used <TabsTrigger> which has role="tab".
    // W2 removed all <Tabs> — none of these elements should exist.
    await expect(page.getByRole("tab", { name: "Holdings" })).not.toBeVisible();

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("has no 'Transactions' tab button after W2 redesign", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY: W2 §4.19 — "T" hotkey navigates to /portfolio/transactions; there
    // is no Transactions tab button in the DOM.
    await expect(page.getByRole("tab", { name: "Transactions" })).not.toBeVisible();

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("has no 'Watchlist' tab button after W2 redesign", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY: W2 §4.19 — watchlists moved to /watchlists route; no tab in DOM.
    await expect(page.getByRole("tab", { name: "Watchlist" })).not.toBeVisible();

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("page renders without crash (no JS errors)", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });
    await expect(page.locator("body")).not.toContainText("Application error");

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
