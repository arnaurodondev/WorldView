/**
 * e2e/shell-watchlist-click.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * Pins that clicking a watchlist row in the sidebar routes to
 * /instruments/{TICKER} — NOT a UUID (C-08, F2 ticker-URL lock).  Catches
 * any regression where someone re-wires the click handler to use
 * `member.entity_id` instead of `member.ticker`.
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — watchlist row click → /instruments/{TICKER}", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
  });

  test("clicking AAPL row navigates to /instruments/AAPL (not entity_id)", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });

    // WatchlistPanel emits aria-label="AAPL — view instrument detail" on the row.
    const aaplRow = page.getByLabel(/AAPL — view instrument detail/i);
    await expect(aaplRow).toBeVisible({ timeout: 5_000 });
    await aaplRow.click();

    // Route must be the ticker form, not the e-aapl UUID.
    await expect(page).toHaveURL(/\/instruments\/AAPL/);
    await expect(page).not.toHaveURL(/\/instruments\/e-/);
  });
});
