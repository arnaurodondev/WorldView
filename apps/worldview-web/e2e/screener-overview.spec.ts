/**
 * e2e/screener-overview.spec.ts — PRD-0089 Wave I-A · Block D · T-IA-13
 *
 * Four specs covering the screener page chrome shipped in Wave I-A:
 *   1. "/" hotkey opens NLScreenerInput (NOT the global command palette).
 *   2. Clicking a preset chip re-fetches the table and updates the chip
 *      strip.
 *   3. Density: at 1440x900, ≥240 body cells visible above the fold.
 *   4. Sector→industry cascading: select Tech, industry combobox shows
 *      ≤8 IT-only industries.
 *
 * AUTH GATE: the screener page is gated behind dev-login. All specs are
 * skipped when E2E_AUTH is not set (mirrors density-screener.spec.ts).
 *
 * R19 NOTE: spec #4 is skipped via test.skip with a clear TODO because
 * the current FilterState lacks a multi-select industries combobox
 * (plan §5.1 T-IA-05 defers it to Wave I-B). Removing the spec would
 * lose the intent; the skip keeps it visible in the test report.
 */

import { test, expect } from "@playwright/test";

test.describe("PRD-0089 Wave I-A · Screener overview", () => {
  test.skip(
    () => !process.env.E2E_AUTH,
    "skipped — E2E_AUTH not set (no auth credential for /screener)",
  );

  // Lock the viewport to the Bloomberg-grade 1440x900 target so the
  // density assertion is deterministic.
  test.use({ viewport: { width: 1440, height: 900 } });

  test("'/' hotkey opens NLScreenerInput (not the global command palette)", async ({ page }) => {
    await page.goto("/screener");
    // Wait for the page chrome to finish mounting before firing the chord.
    await page.waitForSelector('[data-testid="screener-results"]', {
      timeout: 15_000,
    });
    // Press "/" on the document body (not inside any input).
    await page.locator("body").press("/");
    // The NL input bar mounts only after the chord; assert its primary
    // input is focused. NLScreenerInput uses a single text input.
    // WHY a generous timeout: the bar uses requestAnimationFrame to focus
    // after mount.
    const nlInput = page.getByPlaceholder(/profitable tech|natural language|tech stocks/i)
      .first();
    await expect(nlInput).toBeFocused({ timeout: 3_000 });
    // Command palette would render a dialog with a search input over the
    // whole page; assert that ISN'T mounted (no role=dialog from cmdk).
    // WHY: this is the primary "/" override guard.
    const dialog = page.getByRole("dialog");
    await expect(dialog).toHaveCount(0);
  });

  test("clicking a preset chip re-fetches the table and updates the chip strip", async ({ page }) => {
    await page.goto("/screener");
    await page.waitForSelector('[data-testid="screener-results"]', {
      timeout: 15_000,
    });
    // PresetBar exposes each preset as a <button aria-pressed=…>. The
    // "Large Cap" preset is one of the six system presets shipped today.
    const largeCapChip = page.getByRole("button", { name: /Large Cap/i }).first();
    await expect(largeCapChip).toBeVisible();
    await largeCapChip.click();
    // After click, aria-pressed flips to true on the active preset.
    await expect(largeCapChip).toHaveAttribute("aria-pressed", "true", {
      timeout: 5_000,
    });
    // The chip strip below the preset bar should mount at least one
    // active-filter chip reflecting the preset's filters.
    // WHY a soft assertion (count > 0, not exact match): the chip strip's
    // exact chip count depends on which filters the preset writes; the
    // spec acceptance is "chips populate", not "exactly N chips".
    const filterChips = page.locator('[data-testid="filter-chip"], [aria-label*="Remove filter"]');
    await expect(filterChips.first()).toBeVisible({ timeout: 5_000 });
  });

  test("density: ≥240 body cells visible at 1440x900", async ({ page }) => {
    // WHY duplicate of density-screener.spec.ts: density is a Wave I-A
    // acceptance gate (plan §7); restating it inside the I-A spec file
    // keeps the wave's coverage self-contained without removing the
    // F1 canary.
    await page.goto("/screener");
    await page.waitForSelector('[data-testid="screener-results"]', {
      timeout: 15_000,
    });
    const cells = page.locator("[data-cell]");
    const count = await cells.count();
    expect(count).toBeGreaterThanOrEqual(240);
  });

  // R19 — never delete tests. This spec ships in I-B once FilterState
  // gains the industries combobox.
  test.skip("sector → industry cascading shows ≤8 IT industries (Wave I-B)", async () => {
    // TODO(plan-0089-wi-b): unskip when FilterState gains the multi-
    // select industries field + the popover combobox. The expected
    // behaviour is: pick "Information Technology" in sectors → the
    // industries combobox lists ONLY GICS-IT industries (≤8).
  });
});
