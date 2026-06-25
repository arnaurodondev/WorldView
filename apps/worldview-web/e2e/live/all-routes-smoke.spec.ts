/**
 * e2e/live/all-routes-smoke.spec.ts — P0-2: live-auth harness + all-route smoke.
 *
 * WHY THIS EXISTS (2026-06-22 E2E-gaps audit, P0-2):
 * The only previously-"live" spec (`qa-live-stack.spec.ts`) authenticates by
 * clicking a "Dev Login" button that does NOT exist on this (Zitadel) deployment,
 * so it fails at auth and guards nothing. This spec replaces it with the
 * deployment-robust live-auth seam (live-helpers.ts) and walks every key
 * authenticated route against the REAL backend, asserting each one:
 *   - did NOT bounce to /login (proves the live-auth harness works),
 *   - rendered without an uncaught page error,
 *   - made no 4xx/5xx product API call (429 rate-limits are tolerated per BUG-3).
 *
 * This converts the audit's "real end-to-end journeys are effectively unguarded
 * in CI" finding into a permanent, runnable guard.
 *
 * RUN: pnpm exec playwright test --project=live e2e/live/all-routes-smoke.spec.ts
 */

import { test, expect } from "@playwright/test";
import {
  installLiveAuth,
  gotoLive,
  assertAuthenticated,
  attachHealthListeners,
  APP_ROUTES,
} from "../live-helpers";

// Serial: one navigation at a time keeps request bursts under the gateway's
// rate limiter (the `live` project already pins workers:1, this is belt+braces).
test.describe.configure({ mode: "serial" });

test.describe("@live all-route smoke", () => {
  // WHY a long per-test timeout: against a `next dev` server the FIRST visit to a
  // route compiles on demand (20-40s for chat / instrument tabs). 90s covers the
  // cold compile + data fan-out + assertions without flaking. (A production build
  // is far faster; this ceiling only matters for the local dev-server run.)
  test.setTimeout(90_000);

  // Mint a real JWT + wire the refresh seam before every navigation. We re-auth
  // per test because the minted token is short-lived (~5 min) and the suite can
  // run longer than a single token's lifetime.
  test.beforeEach(async ({ page }) => {
    await installLiveAuth(page);
  });

  // One test per route so a single broken route is pinpointed in the report
  // instead of aborting the whole sweep on the first failure.
  for (const route of APP_ROUTES) {
    test(`route loads with live data: ${route.label}`, async ({ page }) => {
      const { health, detach } = attachHealthListeners(page);

      await gotoLive(page, route.path);

      // 1. The live-auth seam must have kept us authenticated.
      await assertAuthenticated(page);

      // 2. The route's main content must be visible (the shell <main id="main">
      //    always mounts for an authed (app) route; a redirect to /login would
      //    not). 30s tolerates the dev-server cold-compile tail after navigation.
      await expect(page.locator("main#main")).toBeVisible({ timeout: 30_000 });

      // 3. Give late fan-out responses a beat to surface before we inspect health.
      await page.waitForTimeout(500);
      detach();

      // 4. No uncaught JS exceptions on the route.
      expect(
        health.pageErrors,
        `${route.label}: uncaught page error(s)`,
      ).toEqual([]);

      // 5. No 4xx/5xx product API calls (429s already filtered as tolerated).
      expect(
        health.badResponses,
        `${route.label}: non-2xx gateway response(s): ${JSON.stringify(health.badResponses)}`,
      ).toEqual([]);
    });
  }
});
