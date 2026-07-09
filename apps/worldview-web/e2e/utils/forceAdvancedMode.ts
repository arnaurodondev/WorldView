/**
 * e2e/utils/forceAdvancedMode.ts — force the portfolio page into ADVANCED mode
 * for e2e specs that assert the full power-user layout (PLAN-0122 W-B, T-A-B-05).
 *
 * WHY THIS EXISTS: PRD-0122 W-B flips the public default to SIMPLE (4 KPI tiles,
 * no tab bar, no analytics strips). Every pre-existing portfolio spec that
 * asserts the full layout (tabs, exposure/HHI strips, 14-column table, scroll
 * FPS over the whole page) would otherwise break — not because the layout
 * regressed, but because the default now hides it. R19 forbids weakening those
 * assertions; instead we force the mode that renders the layout they check.
 *
 * HOW: `page.addInitScript` runs BEFORE any app JS on every subsequent
 * navigation, so we seed the persisted-mode localStorage key to "advanced".
 * usePortfolioMode reconciles from localStorage on first client render → the page
 * paints Advanced immediately (no Simple flash then re-render). Call this ONCE in
 * a `test.beforeEach`; the init script persists for all navigations in the test.
 *
 * The key MUST match hooks/usePortfolioMode.ts `PORTFOLIO_MODE_STORAGE_KEY`.
 */

import type { Page } from "@playwright/test";

/** Keep in sync with hooks/usePortfolioMode.ts PORTFOLIO_MODE_STORAGE_KEY. */
export const PORTFOLIO_MODE_STORAGE_KEY = "worldview:portfolioMode:v1";

/**
 * Seed localStorage so the portfolio page resolves to Advanced mode on load.
 * Registers an init script that runs before app JS on every navigation.
 */
export async function forceAdvancedMode(page: Page): Promise<void> {
  await page.addInitScript((key: string) => {
    try {
      window.localStorage.setItem(key, "advanced");
    } catch {
      // Private-mode / disabled storage — harmless; the ?mode fallback (if the
      // spec also navigates with it) still forces Advanced.
    }
  }, PORTFOLIO_MODE_STORAGE_KEY);
}
