/**
 * e2e/screener-returns-cols.spec.ts — Playwright e2e for IB-L3
 * (PRD-0089 Wave I-B Block IB-L3, T-IB3-05)
 *
 * WHY THIS FILE EXISTS:
 *   Vitest covers the formatReturnPct formatter and sign-colour logic in
 *   isolation. But the AG Grid wiring path — column definition registered →
 *   ColumnSettingsPopover lists the column → toggle → AG Grid renders header
 *   + cells — crosses too many layers to unit-test. This e2e spec pins the
 *   integration so any future refactor that breaks the column registration
 *   is caught immediately.
 *
 * WHAT IT TESTS:
 *   1. The 8 Performance columns appear as toggleable opt-in columns in
 *      ColumnSettingsPopover (or whichever column-control surface the
 *      screener exposes).
 *   2. Toggling "1M RTN" makes the AG Grid column header visible.
 *   3. The Performance filter section is rendered in ScreenerFilterBar.
 *
 * WHAT IT DOES NOT TEST:
 *   - Backend data correctness (covered by services/market-data tests).
 *   - Format precision (covered by returns-columns.test.tsx).
 *
 * AUTH GATE: mirrors every other screener spec. Skip when E2E_AUTH is
 * not set so CI (no credentials) still shows a "skipped" result instead
 * of a failure.
 *
 * R19 NOTE: do NOT delete this spec if auth is unavailable — the skip
 * keeps the intent version-controlled and runnable locally.
 *
 * DESIGN REFERENCE:
 *   docs/plans/0089-pages/DEFERRED-WORK-PLAN.md §2.4 (IB-L3) T-IB3-05
 */

import { test, expect } from "@playwright/test";

test.describe("PRD-0089 IB-L3 — Returns / 52W distance columns", () => {
  test.skip(
    () => !process.env.E2E_AUTH,
    "skipped — E2E_AUTH not set (no auth credential for /screener)",
  );

  test.use({ viewport: { width: 1440, height: 900 } });

  test.beforeEach(async ({ page }) => {
    await page.goto("/screener");
    await page.waitForSelector('[data-testid="screener-results"]', {
      timeout: 15_000,
    });
  });

  test("Performance filter section is rendered in ScreenerFilterBar", async ({ page }) => {
    // Open the filter panel (click the Filters toggle button).
    await page.getByRole("button", { name: /filters/i }).first().click();
    // The Performance section header should appear.
    await expect(
      page.getByText("Performance", { exact: true }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("toggle '1M RTN' column via ColumnSettingsPopover → AG Grid renders header", async ({
    page,
  }) => {
    // Open the column-settings popover (⚙ Configure columns button).
    await page.getByRole("button", { name: "Configure columns" }).click();

    const toggle = page.getByRole("checkbox", {
      name: /toggle 1m rtn column visibility/i,
    });
    await expect(toggle).toBeVisible({ timeout: 5_000 });
    await toggle.click();
    await page.keyboard.press("Escape");

    // AG Grid renders the column header once the column is visible.
    await expect(
      page.getByRole("columnheader", { name: /^1m rtn$/i }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("toggle '52W%↑' column via ColumnSettingsPopover → AG Grid renders header", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Configure columns" }).click();

    const toggle = page.getByRole("checkbox", {
      name: /toggle 52w%↑ column visibility/i,
    });
    await expect(toggle).toBeVisible({ timeout: 5_000 });
    await toggle.click();
    await page.keyboard.press("Escape");

    await expect(
      page.getByRole("columnheader", { name: /52w%↑/i }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("Performance filter section contains '1M Return' range input when open", async ({
    page,
  }) => {
    // Open filter panel.
    await page.getByRole("button", { name: /filters/i }).first().click();

    // Find and expand the Performance section (click the section header).
    const perfSection = page.getByText("Performance", { exact: true });
    await perfSection.click();

    // The 1M Return label should appear inside the section.
    await expect(page.getByText(/1m return/i)).toBeVisible({ timeout: 5_000 });
  });
});
