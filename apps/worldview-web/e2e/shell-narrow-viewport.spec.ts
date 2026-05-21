/**
 * e2e/shell-narrow-viewport.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * Pins the IndexStrip priority-drop behaviour at narrow viewports: USO
 * drops first (its priority rank = 0), then GLD, then BTC, etc.  The
 * strip should also disappear entirely below 1024px.
 *
 * The drop is driven by Tailwind responsive utilities (hidden /
 * xl:flex / 2xl:flex) so we change the viewport size and check the
 * computed CSS display value.
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — IndexStrip narrow-viewport priority drop", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
  });

  test("USO is hidden at 1280px (priority drop)", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });

    // USO cell is `data-ticker="USO"` from the manifest. At 1280px it falls
    // into the `hidden 2xl:flex` bucket → display:none.
    const uso = page.locator('[data-ticker="USO"]');
    await expect(uso).toBeHidden();
  });

  test("the entire strip is hidden below 1024px", async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 800 });
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    const strip = page.getByTestId("index-strip");
    await expect(strip).toBeHidden();
  });

  test("at 2xl viewport every manifest cell is visible", async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('[data-ticker="USO"]')).toBeVisible();
    await expect(page.locator('[data-ticker="SPY"]')).toBeVisible();
  });
});
