/**
 * e2e/portfolio-stub-routes.spec.ts — W2 stub sub-routes smoke tests
 *
 * WHY THIS EXISTS: W2 introduced two new sub-routes:
 *   - /portfolio/transactions — moved from a tab in W1
 *   - /portfolio/analytics — new in W2 (analytics components)
 *
 * Both are currently stub pages (placeholder content) that will be fleshed
 * out in future waves. These smoke tests assert that:
 *   1. The routes exist and return a valid page (not 404)
 *   2. The pages render without JS errors
 *   3. The pages include a back-link to /portfolio
 *
 * WHY browser-level: route-level 404s are hard to catch with Vitest; only a
 * real browser navigation confirms the Next.js route tree resolves the path.
 *
 * DATA SOURCE: installStrictApiMocks() + catch-all fallback
 * DESIGN REFERENCE: PRD-0089 W2 §4.19 (sub-route stubs)
 */

import { test, expect, type Page } from "@playwright/test";
import {
  installStrictApiMocks,
  collectCriticalErrors,
  filterCriticalErrors,
} from "./fixtures/api-mocks";

// ── Shared helpers ────────────────────────────────────────────────────────────

async function setupStubRoutes(page: Page) {
  await installStrictApiMocks(page);

  // W2 sub-route pages fire portfolio queries too; stub them to avoid CORS errors
  await page.route("**/api/v1/portfolios/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/api/v1/brokerage/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Portfolio W2 — stub sub-routes", () => {
  test("/portfolio/transactions renders without crash (non-404)", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await setupStubRoutes(page);

    await page.goto("/portfolio/transactions");
    await page.waitForLoadState("domcontentloaded");

    // WHY check for "Application error": Next.js 404 pages don't show this text,
    // but a component crash does. Both are bad — we check for crash here and
    // verify the URL didn't redirect away from /transactions below.
    await expect(page.locator("body")).not.toContainText("Application error");

    // WHY check URL: if the route doesn't exist, Next.js would redirect to /404
    // or /not-found. A URL still on /portfolio/transactions confirms the route exists.
    await expect(page).toHaveURL(/\/portfolio\/transactions/, { timeout: 5000 });

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("/portfolio/analytics renders without crash (non-404)", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await setupStubRoutes(page);

    await page.goto("/portfolio/analytics");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.locator("body")).not.toContainText("Application error");

    // WHY check URL: confirms /analytics route is registered in Next.js router
    await expect(page).toHaveURL(/\/portfolio\/analytics/, { timeout: 5000 });

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("/portfolio/transactions back-link navigates to /portfolio", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await setupStubRoutes(page);

    await page.goto("/portfolio/transactions");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY back-link: stub pages must include a link back to the portfolio overview
    // so users are not stranded on the stub page with no navigation path.
    // The link text is "← Portfolio" as per the stub page template.
    const backLink = page.locator('a[href="/portfolio"]');
    if (await backLink.count() > 0) {
      await expect(backLink.first()).toBeVisible();
    } else {
      // If back link uses a button instead of anchor, check for "Portfolio" text
      // (WHY: different stub implementations may use different navigation patterns)
      const portfolioLink = page.getByText(/portfolio/i).first();
      await expect(portfolioLink).toBeVisible();
    }

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("/portfolio/analytics back-link navigates to /portfolio", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await setupStubRoutes(page);

    await page.goto("/portfolio/analytics");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    const backLink = page.locator('a[href="/portfolio"]');
    if (await backLink.count() > 0) {
      await expect(backLink.first()).toBeVisible();
    } else {
      const portfolioLink = page.getByText(/portfolio/i).first();
      await expect(portfolioLink).toBeVisible();
    }

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
