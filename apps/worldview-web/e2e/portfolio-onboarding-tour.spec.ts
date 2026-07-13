/**
 * e2e/portfolio-onboarding-tour.spec.ts — PLAN-0122 W-F (T-A-F-03), PRD §9.
 *
 * SCENARIO (PRD §9 "portfolio-onboarding-tour"): after a first portfolio create
 * the tour appears; Skip dismisses it; it does NOT reappear on reload (the flag is
 * persisted "done").
 *
 * HOW WE SIMULATE "first create": rather than drive the full create flow, we seed
 * the tour flag to "pending" (exactly what CreatePortfolioDialog.markTourPending
 * writes) BEFORE the app boots. The init script is ONLY-IF-UNSET, so the app's own
 * write of "done" on tour-start survives the reload (the script does not clobber
 * it) — which is precisely how persistence is proven.
 *
 * NO forceAdvancedMode: the tour runs in the default Simple mode; its Simple
 * anchors (header, mode toggle, Add Position) all resolve, and the Advanced-only
 * column-toggle step self-skips.
 */

import { test, expect } from "@playwright/test";
import { installPortfolioPage } from "./utils/portfolioMocks";
import { collectCriticalErrors, filterCriticalErrors } from "./fixtures/api-mocks";

const TOUR_KEY = "worldview:portfolioTourSeen:v1";

test.describe("PLAN-0122 W-F — onboarding tour trigger + dismiss persistence", () => {
  test("tour auto-starts on first create, Skip dismisses, and it does not reappear", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page);

    // Arm the tour exactly as a first-ever create would — only if unset, so the
    // app's later "done" write is not overwritten on reload.
    await page.addInitScript((key: string) => {
      if (window.localStorage.getItem(key) == null) {
        window.localStorage.setItem(key, "pending");
      }
    }, TOUR_KEY);

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // The tour popover auto-starts.
    await expect(page.getByTestId("portfolio-tour")).toBeVisible({ timeout: 10000 });

    // Skip dismisses it and persists "done".
    await page.getByTestId("portfolio-tour-skip").click();
    await expect(page.getByTestId("portfolio-tour")).toHaveCount(0);
    expect(await page.evaluate((k) => window.localStorage.getItem(k), TOUR_KEY)).toBe("done");

    // Reload → the tour must NOT reappear (flag is "done"; the init script is
    // only-if-unset so it does not re-arm).
    await page.reload();
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId("portfolio-tour")).toHaveCount(0);

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("existing users (no flag) are backfilled to done and never see the tour", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page);

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // No tour for a user who already had a portfolio (flag was unset → backfilled).
    await expect(page.getByTestId("portfolio-tour")).toHaveCount(0);
    await expect
      .poll(() => page.evaluate((k) => window.localStorage.getItem(k), TOUR_KEY))
      .toBe("done");

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
