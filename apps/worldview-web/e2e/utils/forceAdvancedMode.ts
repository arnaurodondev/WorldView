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
 * TWO WAYS TO FORCE, and which is actually flash-free:
 *   • forceAdvancedMode(page) — seeds the persisted-mode localStorage key via
 *     `page.addInitScript`. usePortfolioMode reads localStorage in a `useEffect`
 *     (SSR-safety, never during render), so the FIRST client render resolves to
 *     the flag default (Simple) and only reconciles to Advanced after that effect
 *     runs. That means this path has a brief Simple → Advanced flash on the first
 *     paint. It is still useful as a belt (survives in-test navigations) and is
 *     enough for specs that only assert final state, not the first frame.
 *   • gotoAdvanced(page, path) — navigates with `?mode=advanced` in the URL. nuqs
 *     reads the URL SYNCHRONOUSLY during render and URL is the highest-precedence
 *     source in usePortfolioMode, so the very first paint is already Advanced —
 *     genuinely flash-free. PREFER THIS for specs sensitive to the first frame
 *     (perf/FPS traces, no-flash assertions).
 *
 * Call forceAdvancedMode ONCE in a `test.beforeEach`; the init script persists
 * for all navigations in the test. Use gotoAdvanced for the navigation itself
 * when a flash-free first paint matters.
 *
 * The key MUST match hooks/usePortfolioMode.ts `PORTFOLIO_MODE_STORAGE_KEY`.
 */

import type { Page } from "@playwright/test";

/** Keep in sync with hooks/usePortfolioMode.ts PORTFOLIO_MODE_STORAGE_KEY. */
export const PORTFOLIO_MODE_STORAGE_KEY = "worldview:portfolioMode:v1";

/**
 * Seed localStorage so the portfolio page resolves to Advanced mode after its
 * reconcile effect runs. Registers an init script that runs before app JS on
 * every navigation. NOTE: this is NOT flash-free (localStorage is read in an
 * effect, not during render) — use gotoAdvanced for a flash-free first paint.
 */
export async function forceAdvancedMode(page: Page): Promise<void> {
  await page.addInitScript((key: string) => {
    try {
      window.localStorage.setItem(key, "advanced");
    } catch {
      // Private-mode / disabled storage — harmless; the ?mode fallback (if the
      // spec also navigates with it, e.g. via gotoAdvanced) still forces Advanced.
    }
  }, PORTFOLIO_MODE_STORAGE_KEY);
}

/**
 * Navigate to `path` with `?mode=advanced` appended so the FIRST paint is already
 * Advanced (nuqs reads the URL synchronously; URL beats localStorage + the flag
 * default in usePortfolioMode). This is the genuinely flash-free force — prefer
 * it over relying on the localStorage seed alone when the first frame matters.
 *
 * @param page  the Playwright page
 * @param path  the target path, with or without an existing query string
 *              (e.g. "/portfolio" or "/portfolio?tab=holdings")
 */
export async function gotoAdvanced(page: Page, path: string): Promise<void> {
  const sep = path.includes("?") ? "&" : "?";
  await page.goto(`${path}${sep}mode=advanced`);
}
