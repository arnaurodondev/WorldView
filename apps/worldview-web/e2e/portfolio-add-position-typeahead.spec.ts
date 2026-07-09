/**
 * e2e/portfolio-add-position-typeahead.spec.ts — PLAN-0122 W-F (T-A-F-03), PRD §9.
 *
 * SCENARIO (PRD §9 "portfolio-add-position-typeahead"): open Add Position, type
 * "AAPL", pick the dropdown result, set a PAST trade date, submit — and verify
 * the POST /v1/transactions request carries `executed_at` derived from the picked
 * date (not "now"). This is the W-C typeahead + trade-date unlock; W-C flagged the
 * e2e as W-F scope.
 *
 * WHY NOT forceAdvancedMode: the Add Position button lives in the header, which is
 * present in BOTH modes, so the default (Simple) is fine — the dialog is identical.
 *
 * NO REAL BACKEND: all S9 calls mocked; the transaction POST is intercepted so we
 * can assert its body.
 */

import { test, expect } from "@playwright/test";
import { installPortfolioPage } from "./utils/portfolioMocks";
import { collectCriticalErrors, filterCriticalErrors } from "./fixtures/api-mocks";

test.describe("PLAN-0122 W-F — Add Position typeahead + trade date", () => {
  test("type → pick → past date → submit sends executed_at from the picked date", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installPortfolioPage(page, { withSearch: true });

    // Capture the transaction POST body so we can assert executed_at.
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
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // Open Add Position from the header (data-tour-target anchors it too).
    await page.getByRole("button", { name: /add a new position/i }).click();
    await expect(page.getByText("Add Position")).toBeVisible({ timeout: 10000 });

    // Debounced typeahead: type a ticker, wait for the dropdown result.
    await page.getByPlaceholder(/search ticker or company/i).fill("AAPL");
    const option = page.getByRole("option", { name: /AAPL/i }).first();
    await expect(option).toBeVisible({ timeout: 10000 });
    await option.click();

    // Quantity + a PAST trade date.
    await page.getByLabel("Quantity").fill("5");
    await page.getByLabel("Trade date").fill("2026-01-15");

    // Submit.
    await page.getByRole("button", { name: /^add position$/i }).click();

    // The gateway must send executed_at anchored to the picked date, not "now".
    await expect.poll(() => postedBody).toBeTruthy();
    // Optional chaining (not a cast) avoids TS narrowing postedBody to null at
    // this read — the non-null assignment happens inside the route closure.
    expect(String(postedBody?.executed_at ?? "")).toContain("2026-01-15");

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
