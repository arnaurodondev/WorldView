/**
 * e2e/portfolio-simple-mode.spec.ts — PLAN-0122 W-F (T-A-F-03), PRD §9.
 *
 * SCENARIO (PRD §9 "portfolio-simple-mode"): a default load shows the SIMPLE
 * layout (no tab bar, the direct Holdings body); switching the mode toggle to
 * Advanced reveals the full 4-tab layout; the choice persists across a reload.
 *
 * WHY NO forceAdvancedMode here: this spec is the one that asserts the NEW public
 * default (Simple), so it deliberately does NOT seed Advanced. Every other
 * full-layout spec forces Advanced (R19); this one proves the default flipped.
 *
 * NO REAL BACKEND: all S9 calls are mocked (see utils/portfolioMocks).
 */

import { test, expect } from "@playwright/test";
import { installPortfolioPage } from "./utils/portfolioMocks";
import { collectCriticalErrors, filterCriticalErrors } from "./fixtures/api-mocks";

test.describe("PLAN-0122 W-F — portfolio dual-mode (Simple default)", () => {
  test("default load renders Simple: no tab bar, direct Holdings body", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page);

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // Simple hides the tab bar entirely and renders the Holdings body directly.
    await expect(page.getByTestId("portfolio-simple-holdings")).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("tab", { name: "Holdings" })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Transactions" })).toHaveCount(0);

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("toggling Advanced reveals the full tab layout and persists across reload", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page);

    await page.goto("/portfolio");
    await expect(page.getByTestId("portfolio-simple-holdings")).toBeVisible({ timeout: 10000 });

    // Flip to Advanced via the header segmented control (role=radiogroup).
    const group = page.getByRole("radiogroup", { name: "Portfolio detail level" });
    await group.getByRole("radio", { name: "Advanced" }).click();

    // Advanced shows the 4-tab bar; the Simple direct-render container is gone.
    await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole("tab", { name: "Transactions" })).toBeVisible();
    await expect(page.getByTestId("portfolio-simple-holdings")).toHaveCount(0);

    // Persistence: the choice is written to localStorage + ?mode=; reload keeps it.
    await page.reload();
    await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible({ timeout: 10000 });

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
