/**
 * e2e/alerts-history.spec.ts — PLAN-0051 T-D-4-04 history tab.
 *
 * WHY THIS EXISTS: smoke-test that the new History tab actually renders,
 * filter pills can be clicked, and Load-More fires another network call
 * with a larger limit. The tests mock the gateway so we don't need a live
 * S10 to validate the wiring.
 */

import { test, expect } from "@playwright/test";

/**
 * buildFakeToken — same JWT shape used in dashboard.spec.ts. We re-derive
 * here rather than import because Playwright specs avoid cross-imports
 * (each spec must be self-contained for parallel runs).
 */
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

function makeAlert(i: number, severity: string = "HIGH") {
  return {
    alert_id: `alert-${i}`,
    entity_id: `entity-${i}`,
    ticker: `TKR${i}`,
    alert_type: "PRICE_MOVE",
    severity,
    title: `Alert ${i}`,
    body: "",
    metadata: {},
    created_at: new Date(Date.now() - i * 60_000).toISOString(),
    acknowledged_at: null,
  };
}

test.describe("Alerts page — History tab", () => {
  test("renders history rows and supports filter + load-more", async ({ page }) => {
    const fakeToken = buildFakeToken();

    // Auth refresh
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

    // ws-token (AlertStreamContext requires this on mount).
    await page.route("**/api/v1/auth/ws-token", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "ws" }) }),
    );

    // Pending alerts (Active tab) — empty list keeps the tab quiet.
    await page.route("**/api/v1/alerts/pending**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ alerts: [], total: 0, offset: 0, limit: 50 }),
      }),
    );

    // History — first call returns 50 rows of total 100, second returns 100.
    let historyCallCount = 0;
    await page.route("**/api/v1/alerts/history**", (route) => {
      historyCallCount += 1;
      const url = new URL(route.request().url());
      const limit = Number(url.searchParams.get("limit") ?? 50);
      const rows = Array.from({ length: Math.min(limit, 100) }).map((_, i) => makeAlert(i + 1));
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ alerts: rows, total: 100, offset: 0, limit }),
      });
    });

    // Generic catch-all stub for everything else.
    await page.route("**/api/v1/**", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    await page.goto("/alerts");
    // Wait for the page header to mount.
    await expect(page.getByRole("heading", { name: /Alerts & News/i })).toBeVisible({ timeout: 10_000 });

    // Switch to the History sub-tab.
    await page.getByRole("tab", { name: /^History$/ }).click();

    // First page renders 50 rows — assert one ticker is visible.
    await expect(page.getByText(/TKR1/)).toBeVisible({ timeout: 10_000 });

    // Severity filter — clicking HIGH must trigger another history call.
    historyCallCount = 0;
    await page.getByRole("button", { name: /^HIGH$/ }).click();
    await page.waitForTimeout(500); // allow debounce / re-fetch
    expect(historyCallCount).toBeGreaterThan(0);

    // Load more — appends rows.
    const loadMore = page.getByRole("button", { name: /Load more/i });
    await expect(loadMore).toBeVisible();
    await loadMore.click();
    await page.waitForTimeout(500);
    // After load-more, total rows on the page should reach 100 (TKR100 visible).
    await expect(page.getByText(/TKR100/)).toBeVisible({ timeout: 10_000 });
  });
});
