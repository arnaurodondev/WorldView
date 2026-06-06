/**
 * e2e/density-screener.spec.ts — PRD-0089 F1 density canary
 *
 * WHY THIS EXISTS: Acceptance gate #9 in plan §9 — verify the Screener page
 * still shows ≥240 visible cells after the F1 token + layout changes.  If
 * the density drops below 240, either the table virtualisation is broken
 * or the row geometry got loosened by a regression.
 *
 * NOTE ON PATH: The plan asked for `tests/e2e/density-screener.spec.ts`,
 * but Playwright's testDir in `playwright.config.ts` is `./e2e/`. We honour
 * the actual test runner config; the spec is still discovered via the
 * existing pnpm test:e2e command.
 *
 * AUTH GATE: If E2E_AUTH is not set, the test is skipped — the Screener
 * page is gated behind dev-login and CI may not have a credential set
 * available.
 */

import { test, expect } from "@playwright/test";

test.describe("PRD-0089 F1 density canary", () => {
  test.skip(
    () => !process.env.E2E_AUTH,
    "skipped — E2E_AUTH not set (no auth credential for /screener)",
  );

  test("Screener renders ≥240 visible cells", async ({ page }) => {
    await page.goto("/screener");
    // Wait for the results table to render. The Screener uses AG Grid,
    // and per docs/apps/worldview-web.md the table has data-testid="screener-results".
    await page.waitForSelector('[data-testid="screener-results"]', {
      timeout: 15_000,
    });
    // [data-cell] is the convention from PLAN-0089 for density-trackable cells.
    // If your screener uses a different attribute, swap the selector here.
    const cells = page.locator("[data-cell]");
    const count = await cells.count();
    expect(count).toBeGreaterThanOrEqual(240);
  });
});
