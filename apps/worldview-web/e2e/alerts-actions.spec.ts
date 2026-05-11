/**
 * e2e/alerts-actions.spec.ts — PLAN-0051 T-D-4-05 SuggestedActions.
 *
 * Smoke-tests the AlertDetailSheet's Suggested Actions: opening the sheet
 * via ?selected= and clicking "View instrument" should navigate to the
 * /instruments/{entity_id} route.
 */

import { test, expect } from "@playwright/test";

function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const payload = btoa(JSON.stringify({
    sub: "e2e-user",
    tenant_id: "e2e-tenant",
    email: "e2e@test.local",
    name: "E2E",
    exp: Math.floor(Date.now() / 1000) + 3600,
  })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${header}.${payload}.fake-sig`;
}

test.describe("Alerts page — SuggestedActions", () => {
  test("View instrument navigates to /instruments/{entity_id}", async ({ page }) => {
    const fakeToken = buildFakeToken();

    await page.route("**/api/v1/auth/refresh", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: fakeToken,
          expires_in: 3600,
          user: { user_id: "e2e-user", tenant_id: "e2e-tenant", email: "e2e@test.local", name: "E2E" },
        }),
      }),
    );
    await page.route("**/api/v1/auth/ws-token", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "ws" }) }),
    );

    // Seed the pending list with one alert that has a ticker (instrument).
    await page.route("**/api/v1/alerts/pending**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          alerts: [
            {
              alert_id: "alert-aapl-1",
              entity_id: "entity-aapl",
              ticker: "AAPL",
              alert_type: "PRICE_MOVE",
              severity: "HIGH",
              title: "AAPL +5%",
              body: "Apple +5%",
              metadata: {},
              created_at: new Date().toISOString(),
              acknowledged_at: null,
            },
          ],
          total: 1,
          offset: 0,
          limit: 50,
        }),
      }),
    );

    // Watchlists for the AddToWatchlistDialog (renders on mount but doesn't open).
    await page.route("**/api/v1/watchlists**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );

    // Generic catch-all stub.
    await page.route("**/api/v1/**", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    // Open /alerts with a selected query param so the detail sheet opens
    // immediately. Avoids fragile click-on-row coordination.
    await page.goto("/alerts?selected=alert-aapl-1");

    // Sheet should appear with the AAPL header.
    await expect(page.getByText(/AAPL/).first()).toBeVisible({ timeout: 10_000 });

    // Click View instrument — wait for navigation to fire.
    await Promise.all([
      page.waitForURL(/\/instruments\/entity-aapl/, { timeout: 10_000 }),
      page.getByRole("button", { name: /View instrument/i }).click(),
    ]);

    expect(page.url()).toContain("/instruments/entity-aapl");
  });
});
