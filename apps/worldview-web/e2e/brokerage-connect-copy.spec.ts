/**
 * e2e/brokerage-connect-copy.spec.ts — PLAN-0122 W-F (T-A-F-03), PRD §9.
 *
 * SCENARIO (PRD §9 "brokerage-connect-copy"): the connect modal shows the
 * credentials-safety trust block (W-C, R-8); the OAuth callback shows the HONEST
 * timing sub-copy while keeping the pinned success heading (W-C, R-9/R-10).
 *
 * NO REAL BACKEND: S9 calls mocked. The callback activation endpoint is stubbed to
 * a success so the success state (and its copy) renders.
 */

import { test, expect } from "@playwright/test";
import { installPortfolioPage, installAuthMocks } from "./utils/portfolioMocks";
import { forceAdvancedMode } from "./utils/forceAdvancedMode";
import { collectCriticalErrors, filterCriticalErrors } from "./fixtures/api-mocks";

test.describe("PLAN-0122 W-F — brokerage connect trust + timing copy", () => {
  test("connect modal shows the credentials-stay-with-SnapTrade trust block", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    // The Connect modal is reached from the Transactions tab (Advanced only).
    await forceAdvancedMode(page);
    await installPortfolioPage(page);

    await page.goto("/portfolio");
    await page.getByRole("tab", { name: "Transactions" }).click();

    // Expand the Connected Brokerages panel and open the connect modal.
    await page.getByText(/Connected Brokerages/i).click();
    await page.getByRole("button", { name: /connect/i }).first().click();

    // The trust block (data-testid pinned in W-C) must be visible with its copy.
    const trust = page.getByTestId("brokerage-trust-block");
    await expect(trust).toBeVisible({ timeout: 10000 });
    await expect(trust).toContainText(/credentials stay with SnapTrade/i);
    await expect(trust).toContainText(/read-only/i);

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("callback keeps the pinned heading and shows honest timing sub-copy", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installAuthMocks(page);

    // Stub the activation callback → success so the success state renders.
    await page.route("**/api/v1/brokerage-connections/**/callback**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "active", connection_id: "conn-1" }),
      }),
    );
    // Any brokerage-connections list query fired by the page.
    await page.route("**/api/v1/brokerage-connections", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    await page.goto(
      "/portfolio/brokerage/callback?connectionId=conn-1&authorizationId=auth-1&userId=u-1&sessionId=sess-1",
    );

    // Pinned heading (e2e-asserted, unchanged by W-C).
    await expect(page.getByText("Brokerage account connected successfully!")).toBeVisible({
      timeout: 10000,
    });
    // Honest timing sub-copy replaces "syncing shortly".
    await expect(page.getByText(/few minutes/i)).toBeVisible();
    await expect(page.getByText(/few hours/i)).toBeVisible();
    await expect(page.getByText(/Sync Now/i)).toBeVisible();

    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });
});
