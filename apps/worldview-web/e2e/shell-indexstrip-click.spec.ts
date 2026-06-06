/**
 * e2e/shell-indexstrip-click.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * Pins that clicking the SPY cell in the TopBar IndexStrip routes to
 * /indices/SPY (caret stripped for ^TNX → TNX).  Catches regressions
 * where the click handler is reverted to /instruments/{ticker} or worse.
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — IndexStrip cell click → /indices/{ticker}", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
  });

  test("clicking SPY routes to /indices/SPY", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });

    // IndexStrip cells expose aria-label "{displayName} — view index detail".
    // Use a substring match to tolerate the friendly-name format change.
    const spy = page.getByRole("button", { name: /S&P 500 ETF/i });
    await expect(spy).toBeVisible({ timeout: 5_000 });
    await spy.click();

    await expect(page).toHaveURL(/\/indices\/SPY/);
  });

  test("clicking the ^TNX cell routes to /indices/TNX (caret stripped)", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    const tnx = page.getByRole("button", { name: /10-Year Treasury Yield/i });
    await expect(tnx).toBeVisible({ timeout: 5_000 });
    await tnx.click();
    await expect(page).toHaveURL(/\/indices\/TNX(?!\^)/);
  });
});
