/**
 * e2e/screener-fundamentals-columns.spec.ts — Playwright e2e for the
 * 6 opt-in fundamentals snapshot columns + the 14-column horizontal-scroll
 * guard (PRD-0089 Wave I-B Block IB-L2, T-IB-09).
 *
 * WHY THIS EXISTS:
 *   Vitest covers the renderer logic in isolation, but the AG-Grid integration
 *   path (column visibility toggle → DOM header → no horizontal scroll
 *   below 14 columns) crosses too many layers (popover, localStorage,
 *   ag-grid) to test reliably outside a browser. The e2e pins the column
 *   plumbing wired by T-IB-05 + the popover popular-column warning shipped
 *   in Wave I-A.
 *
 * AUTH GATE: like every other screener spec (density-screener.spec.ts,
 * screener-overview.spec.ts), skip when E2E_AUTH is unset — the page is
 * gated behind dev-login and CI may not have a credential.
 *
 * VIEWPORT: 1440px wide — the platform's design target (see
 * docs/ui/DESIGN_SYSTEM.md). The horizontal-scroll assertion below uses
 * `scrollWidth <= clientWidth` on the AG-Grid viewport container.
 *
 * WHAT IT DOES NOT TEST:
 *   - Backend data correctness (covered by services/market-data tests).
 *   - The 6 numeric formatters (covered by fundamentals-columns.test.tsx).
 *   This spec only validates the AG-Grid wiring + viewport regression.
 */

import { test, expect } from "@playwright/test";

test.describe("PRD-0089 Wave I-B Block IB-L2 — fundamentals snapshot columns", () => {
  // WHY skip on missing E2E_AUTH: mirrors density-screener.spec.ts convention.
  // R19 reminder — we do NOT delete the spec when auth is unset; the harness
  // sees it as "skipped" and the test is still version-controlled / runnable
  // locally when the operator exports an E2E_AUTH credential.
  test.skip(
    () => !process.env.E2E_AUTH,
    "skipped — E2E_AUTH not set (no auth credential for /screener)",
  );

  test.beforeEach(async ({ page }) => {
    // 1440px viewport matches the design target. AG-Grid sizes columns based
    // on viewport width; testing at 1024px would mask real overflow bugs.
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/screener");
    await page.waitForSelector('[data-testid="screener-results"]', {
      timeout: 15_000,
    });
  });

  test("toggle AVG VOL column via ColumnSettingsPopover → AG-Grid renders header", async ({
    page,
  }) => {
    // Open the column-settings popover (the ⚙ icon next to the filter bar).
    // aria-label="Configure columns" is the stable selector defined in
    // ColumnSettingsPopover.tsx.
    await page.getByRole("button", { name: "Configure columns" }).click();
    // The popover lists every column. WHY a checkbox aria-label match:
    // each row's <input> has aria-label="Toggle {label} column visibility"
    // (ColumnSettingsPopover.tsx). The new opt-in column shows up as
    // "Avg Vol" per the lib/screener-columns.ts label.
    const avgVolToggle = page.getByRole("checkbox", {
      name: /toggle avg vol column visibility/i,
    });
    await expect(avgVolToggle).toBeVisible();
    // Click to enable.
    await avgVolToggle.click();
    // Dismiss the popover.
    await page.keyboard.press("Escape");

    // AG-Grid renders the column header text "AVG VOL" once visible.
    const header = page.getByRole("columnheader", { name: /^avg vol$/i });
    await expect(header).toBeVisible({ timeout: 5_000 });
  });

  test("with ≤14 selected columns, no horizontal scroll at 1440px viewport", async ({
    page,
  }) => {
    // The default layout ships ~14 visible columns. Pin that the viewport
    // doesn't already overflow before any opt-in toggle (regression guard
    // against future column-width inflation).
    const viewport = page.locator(".ag-body-viewport").first();
    await expect(viewport).toBeVisible();
    const { scrollWidth, clientWidth } = await viewport.evaluate((el) => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }));
    // Allow a 1px tolerance for sub-pixel rounding; AG-Grid occasionally
    // reports scrollWidth=clientWidth+1 even when no scrollbar is drawn.
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
  });

  test("popover footer warns when >14 columns selected (column-count regression)", async ({
    page,
  }) => {
    // Open popover.
    await page.getByRole("button", { name: "Configure columns" }).click();

    // Read current visible-count then toggle on enough opt-in columns to
    // exceed the MAX_VISIBLE_COLUMNS=14 threshold. WHY toggle multiple
    // L-2 + earlier opt-ins (avgVol/epsTtm/fcf/fcfMargin/intCov/ndEbitda
    // + opMargin/evEbitda): the baseline already includes 14 default
    // columns; any single opt-in pushes the count to 15, but we toggle
    // several to be unambiguous about firing the warning footer.
    const labelsToEnable = [
      /toggle avg vol column visibility/i,
      /toggle eps \(ttm\) column visibility/i,
      /toggle fcf column visibility/i,
    ];
    for (const re of labelsToEnable) {
      const toggle = page.getByRole("checkbox", { name: re });
      if (await toggle.isVisible()) {
        // Only toggle ON if currently unchecked. WHY: defends against the
        // user's existing localStorage already having one of these on.
        const isChecked = await toggle.isChecked();
        if (!isChecked) await toggle.click();
      }
    }

    // The popover footer text matches the literal string in
    // ColumnSettingsPopover.tsx line 304-306.
    const footer = page.getByText(
      /more than 14 columns will horizontally scroll past the 1440 px viewport/i,
    );
    await expect(footer).toBeVisible();
    // The footer flips to text-warning when over the threshold.
    await expect(footer).toHaveClass(/text-warning/);
  });
});
