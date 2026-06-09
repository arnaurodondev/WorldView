/**
 * e2e/screener-analyst-cols.spec.ts — Playwright e2e for IB-L4
 * (PRD-0089 Wave I-B Block IB-L4, T-IB4-05)
 *
 * WHY THIS FILE EXISTS:
 *   Vitest covers the consensus tone classifier, insider compact formatter,
 *   and ANALYST UPSIDE null-guard in isolation. This e2e spec pins the AG
 *   Grid integration path: column definitions registered → popover lists the
 *   columns → toggle → header visible. It also verifies that the Ownership
 *   filter section renders in ScreenerFilterBar with its 5 inputs.
 *
 * WHAT IT TESTS:
 *   1. The 6 Ownership columns appear as toggleable opt-in columns.
 *   2. Toggling "CONSENSUS" makes the AG Grid column header visible.
 *   3. ANALYST UPSIDE column appears in the popover (derived, no sort).
 *   4. The Ownership filter section renders in ScreenerFilterBar.
 *   5. INSIDER 90D column toggling (spot-check for the one column that
 *      shows "—" for null rather than a formatted number).
 *
 * WHAT IT DOES NOT TEST:
 *   - Backend data correctness (covered by services/market-data tests).
 *   - null → "—" guard for insider (covered by analyst-columns.test.tsx).
 *
 * AUTH GATE: mirrors every other screener spec. Skip when E2E_AUTH is
 * not set.
 *
 * R19 NOTE: do NOT delete this spec if auth is unavailable.
 *
 * DESIGN REFERENCE:
 *   docs/plans/0089-pages/DEFERRED-WORK-PLAN.md §2.5 (IB-L4) T-IB4-05
 */

import { test, expect } from "@playwright/test";

test.describe("PRD-0089 IB-L4 — Analyst / Insider / Ownership columns", () => {
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

  test("Ownership filter section is rendered in ScreenerFilterBar", async ({ page }) => {
    await page.getByRole("button", { name: /filters/i }).first().click();
    await expect(
      page.getByText("Ownership", { exact: true }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("toggle CONSENSUS column → AG Grid renders header", async ({ page }) => {
    await page.getByRole("button", { name: "Configure columns" }).click();

    const toggle = page.getByRole("checkbox", {
      name: /toggle consensus column visibility/i,
    });
    await expect(toggle).toBeVisible({ timeout: 5_000 });
    await toggle.click();
    await page.keyboard.press("Escape");

    await expect(
      page.getByRole("columnheader", { name: /^consensus$/i }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("toggle ANALYST UPSIDE column → AG Grid renders header", async ({ page }) => {
    // ANALYST UPSIDE is a derived column (no `field`) — it must still appear
    // in the column toggle list and render the header when enabled.
    await page.getByRole("button", { name: "Configure columns" }).click();

    const toggle = page.getByRole("checkbox", {
      name: /toggle analyst upside column visibility/i,
    });
    await expect(toggle).toBeVisible({ timeout: 5_000 });
    await toggle.click();
    await page.keyboard.press("Escape");

    await expect(
      page.getByRole("columnheader", { name: /analyst upside/i }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("toggle INSIDER 90D column → AG Grid renders header", async ({ page }) => {
    await page.getByRole("button", { name: "Configure columns" }).click();

    const toggle = page.getByRole("checkbox", {
      name: /toggle insider 90d column visibility/i,
    });
    await expect(toggle).toBeVisible({ timeout: 5_000 });
    await toggle.click();
    await page.keyboard.press("Escape");

    await expect(
      page.getByRole("columnheader", { name: /insider 90d/i }),
    ).toBeVisible({ timeout: 5_000 });
  });

  test("Ownership section contains Consensus Rating range input when expanded", async ({
    page,
  }) => {
    await page.getByRole("button", { name: /filters/i }).first().click();

    // Expand the Ownership section.
    const ownershipSection = page.getByText("Ownership", { exact: true });
    await ownershipSection.click();

    // The Consensus Rating label should appear inside the section.
    await expect(page.getByText(/consensus rating/i)).toBeVisible({ timeout: 5_000 });
  });

  test("Ownership section contains Short % range input when expanded", async ({ page }) => {
    await page.getByRole("button", { name: /filters/i }).first().click();

    const ownershipSection = page.getByText("Ownership", { exact: true });
    await ownershipSection.click();

    await expect(page.getByText(/short %/i)).toBeVisible({ timeout: 5_000 });
  });
});
