/**
 * e2e/portfolio-edit-partial-close.spec.ts — PLAN-0122 W-F (T-A-F-03), PRD §9.
 *
 * SCENARIO (PRD §9 "portfolio-edit-partial-close"): from the row-kebab (the
 * always-visible ACTIONS affordance added in W-D), open Edit Position and change
 * the target quantity → an adjusting BUY/SELL is recorded via POST
 * /v1/transactions; and Close Position now supports a PARTIAL sell (editable
 * quantity, default full).
 *
 * WHY forceAdvancedMode: the holdings TABLE (and its pinned-right ACTIONS kebab)
 * is an Advanced surface — Simple renders the Core list without the full grid
 * chrome, so these specs force Advanced (R19: mode that shows the surface).
 *
 * NO REAL BACKEND: S9 calls mocked; the transaction POST is intercepted to assert
 * the honest adjusting-trade body.
 */

import { test, expect } from "@playwright/test";
import { installPortfolioPage } from "./utils/portfolioMocks";
import { forceAdvancedMode } from "./utils/forceAdvancedMode";
import { collectCriticalErrors, filterCriticalErrors } from "./fixtures/api-mocks";

test.beforeEach(async ({ page }) => {
  // The holdings grid + kebab live in Advanced only.
  await forceAdvancedMode(page);
});

test.describe("PLAN-0122 W-F — Edit Position (adjusting trade) + partial close", () => {
  test("kebab → Edit → higher target qty records an adjusting BUY of the delta", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page);

    let postedBody: Record<string, unknown> | undefined;
    await page.route("**/api/v1/transactions", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      try {
        postedBody = route.request().postDataJSON() as Record<string, unknown>;
      } catch {
        postedBody = undefined;
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ transaction_id: "tx-1", status: "recorded" }),
      });
    });

    await page.goto("/portfolio");
    await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible({ timeout: 10000 });

    // Open the row actions kebab (aria-label="Actions for AAPL").
    await page.getByRole("button", { name: /actions for aapl/i }).first().click();
    await page.getByText("Edit Position").click();

    // The honest-ledger dialog opens; current qty is 10 → target 15 → BUY 5.
    await expect(page.getByText(/Edit Position — AAPL/i)).toBeVisible({ timeout: 10000 });
    await page.getByLabel("Target Qty").fill("15");
    await page.getByLabel("Price").fill("200");
    // Submit label reflects the derived action.
    await page.getByRole("button", { name: /record buy of 5/i }).click();

    await expect.poll(() => postedBody).toBeTruthy();
    expect(postedBody?.trade_side).toBe("BUY");
    expect(Number(postedBody?.quantity)).toBe(5);

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("kebab → Close → partial quantity records a SELL of the entered amount", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page);

    let postedBody: Record<string, unknown> | undefined;
    await page.route("**/api/v1/transactions", (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      try {
        postedBody = route.request().postDataJSON() as Record<string, unknown>;
      } catch {
        postedBody = undefined;
      }
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ transaction_id: "tx-2", status: "recorded" }),
      });
    });

    await page.goto("/portfolio");
    await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible({ timeout: 10000 });

    await page.getByRole("button", { name: /actions for aapl/i }).first().click();
    await page.getByText("Close Position").click();

    await expect(page.getByText(/Close Position — AAPL/i)).toBeVisible({ timeout: 10000 });
    // Default quantity is the full holding (10); enter a smaller PARTIAL amount.
    await page.getByLabel("Quantity").fill("4");
    await page.getByLabel(/sale price/i).fill("200");
    await page.getByRole("button", { name: /sell 4|close position/i }).click();

    await expect.poll(() => postedBody).toBeTruthy();
    expect(postedBody?.trade_side).toBe("SELL");
    expect(Number(postedBody?.quantity)).toBe(4);

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
