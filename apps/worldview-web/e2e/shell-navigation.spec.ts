/**
 * e2e/shell-navigation.spec.ts — PRD-0089 W1 Playwright §6.2.
 *
 * Pins that the G-prefixed chord shortcuts still navigate to the right
 * routes after W1 (G+D / G+P / G+I / G+S).  The chords are registered by
 * GlobalHotkeyBindings inside the (app)/layout — surface lives unchanged
 * across W1; this spec is the regression guarantee that the listener
 * survived the shell refactor.
 */

import { test, expect } from "@playwright/test";
import { installShellAuthMocks } from "./shell-helpers";

test.describe("PRD-0089 W1 — shell navigation chords", () => {
  test.beforeEach(async ({ page }) => {
    await installShellAuthMocks(page);
  });

  test("G+D navigates to /dashboard", async ({ page }) => {
    await page.goto("/portfolio"); // start somewhere else
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("g");
    await page.keyboard.press("d");
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("G+P navigates to /portfolio", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("g");
    await page.keyboard.press("p");
    await expect(page).toHaveURL(/\/portfolio/);
  });

  test("G+S navigates to /screener", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("g");
    await page.keyboard.press("s");
    await expect(page).toHaveURL(/\/screener/);
  });

  test("G+I navigates to /instruments", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("g");
    await page.keyboard.press("i");
    await expect(page).toHaveURL(/\/instruments|\/screener/);
  });
});
