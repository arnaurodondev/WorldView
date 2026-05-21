/**
 * e2e/shell-density.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * Density floor canary per NFR-1 tier: at 1440x900, the TopBar must
 * surface ≥17 information slots (wordmark + GlobalSearch trigger +
 * PortfolioSwitcher chip + 10 IndexStrip cells + UtcClock + MarketStatus
 * pill + AskAi button + RefreshAll + Bell + Avatar).  Counts interactive
 * elements with role="button" / role="link" inside the <header>.
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — TopBar density floor", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
    await page.setViewportSize({ width: 1600, height: 900 });
  });

  test("TopBar surfaces >=17 interactive information slots at 2xl", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });

    // Scope to the header element — the TopBar is the only <header> in the
    // (app) layout.  Count buttons + links inside it; the IndexStrip alone
    // contributes 10 of the 17 expected slots.
    const header = page.locator("header").first();
    const interactives = header.locator("button, [role='link']");
    const count = await interactives.count();
    expect(count).toBeGreaterThanOrEqual(17);
  });
});
