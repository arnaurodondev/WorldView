/**
 * e2e/shell-narrow-viewport.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * W1 originally relied on per-cell `hidden lg:flex / hidden xl:flex /
 * hidden 2xl:flex` Tailwind utilities so USO/GLD/BTC dropped first at
 * narrow viewports. W1.1 H-001 reverted that approach when user feedback
 * showed the static strip was clipping cells: the marquee now scrolls
 * horizontally so every ticker becomes visible over one cycle regardless
 * of viewport width. Nothing "drops" anymore.
 *
 * Surviving pins:
 *   - The whole strip is still hidden below the `lg` breakpoint (1024px)
 *     so mobile viewports don't render the marquee.
 *   - At lg+ every manifest cell renders in the DOM (the marquee may have
 *     them off-screen at a given animation frame, but they exist).
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — IndexStrip responsive behaviour", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
  });

  test("the entire strip is hidden below the lg breakpoint (1024px)", async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 800 });
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    const strip = page.getByTestId("index-strip");
    await expect(strip).toBeHidden();
  });

  test("at lg+ viewport every manifest cell is in the DOM (marquee scrolls them through view)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    // Every manifest ticker must be present (the marquee duplicates the
    // list internally, so each data-ticker appears twice — we assert ≥1).
    for (const ticker of ["SPY", "QQQ", "IWM", "VIX", "DIA", "TLT", "^TNX", "BTC-USD", "GLD", "USO"]) {
      const sel = page.locator(`[data-ticker="${ticker}"]`).first();
      await expect(sel).toBeAttached();
    }
  });
});
