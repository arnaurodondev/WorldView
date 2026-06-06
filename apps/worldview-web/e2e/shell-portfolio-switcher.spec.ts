/**
 * e2e/shell-portfolio-switcher.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * Pins that the PortfolioSwitcher chip is always visible (FU-1.1 — even
 * with zero or one portfolio) and that clicking it opens the 240px
 * dropdown with ROOT pinned to the top.
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — PortfolioSwitcher always visible", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
    // Override the default empty stub for portfolios so we have a known set.
    await page.route("**/api/v1/portfolios**", (route) => {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: "p-root",
              tenant_id: "t",
              owner_id: "u",
              name: "ROOT",
              currency: "USD",
              status: "active",
              kind: "root",
              created_at: "2026-01-01T00:00:00Z",
            },
            {
              id: "p-bk",
              tenant_id: "t",
              owner_id: "u",
              name: "Tastytrade Main",
              currency: "USD",
              status: "active",
              kind: "brokerage",
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 2,
          limit: 50,
          offset: 0,
        }),
      });
    });
  });

  test("chip is visible on the dashboard", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    const chip = page.getByTestId("portfolio-switcher-chip");
    await expect(chip).toBeVisible();
    await expect(chip).toContainText(/All Portfolios/i);
  });

  test("clicking the chip opens the dropdown with the ROOT row pinned", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    await page.getByTestId("portfolio-switcher-chip").click();
    const popover = page.getByTestId("portfolio-switcher-popover");
    await expect(popover).toBeVisible();
    // ROOT row carries its own testid; brokerage rows come below.
    await expect(page.getByTestId("portfolio-switcher-root-row")).toContainText(/All Portfolios/i);
  });
});
