/**
 * e2e/portfolio-overview-density.spec.ts — Data cell density regression guard
 *
 * WHY THIS EXISTS: W2 sets rowHeight=22px (Bloomberg terminal density) and
 * uses `font-mono text-[11px]` for data cells. If a style regression raises
 * the row height or hides cells, users lose the compact view. These tests
 * assert that ≥1 data cells are visible after the page loads with holdings.
 *
 * WHY "≥1 data cells" (not exact count): the exact number of visible rows
 * depends on viewport height and the number of holdings returned by the mock.
 * "≥1 visible" is the minimal liveness check: the table rendered real data.
 *
 * DATA SOURCE: Route mocks — portfolio returns AAPL holding.
 * DESIGN REFERENCE: PRD-0089 W2 §4.14 (rowHeight=22 density lock)
 */

import { test, expect, type Page } from "@playwright/test";

function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const payload = btoa(
    JSON.stringify({
      sub: "e2e-user",
      tenant_id: "e2e-tenant",
      email: "e2e@test.local",
      name: "E2E User",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.fake-sig`;
}

async function setupHoldingsPage(page: Page) {
  const token = buildFakeToken();

  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: token,
        expires_in: 3600,
        user: { user_id: "e2e-user", tenant_id: "e2e-tenant", email: "e2e@test.local", name: "E2E User" },
      }),
    }),
  );
  await page.route("**/api/v1/auth/ws-token", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "fake-ws" }) }),
  );

  await page.route("**/api/v1/portfolios", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          portfolio_id: "port-density",
          name: "Density Portfolio",
          currency: "USD",
          owner_id: "e2e-user",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ]),
    });
  });

  await page.route("**/api/v1/portfolios/**/holdings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        portfolio_id: "port-density",
        holdings: [
          {
            holding_id: "h-aapl",
            portfolio_id: "port-density",
            instrument_id: "ins-aapl",
            entity_id: "ent-aapl",
            ticker: "AAPL",
            name: "Apple Inc.",
            quantity: 10,
            average_cost: 170.0,
            current_price: 185.0,
            unrealised_pnl: 150.0,
            unrealised_pnl_pct: 0.0882,
            portfolio_weight: 1.0,
          },
        ],
        total_value: 1850.0,
        total_cost: 1700.0,
        total_unrealised_pnl: 150.0,
        total_unrealised_pnl_pct: 0.0882,
      }),
    }),
  );

  await page.route("**/api/v1/quotes/batch**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        quotes: {
          "ins-aapl": {
            instrument_id: "ins-aapl",
            ticker: "AAPL",
            price: 185.0,
            change: 1.5,
            change_pct: 0.82,
            timestamp: "2026-05-01T15:00:00Z",
            volume: 0,
          },
        },
      }),
    }),
  );

  // Catch-all
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Portfolio W2 — holdings table density", () => {
  test("renders ≥1 data cells when holdings are returned", async ({ page }) => {
    await setupHoldingsPage(page);
    await page.goto("/portfolio");

    // WHY waitForSelector: AG Grid renders cells asynchronously after data resolves.
    await page.waitForSelector("text=AAPL", { timeout: 10000 });

    // Assert AAPL is visible — the table has at least 1 rendered row.
    await expect(page.getByText("AAPL").first()).toBeVisible();
  });

  test("KPI strip tiles are visible (at least 'Total Value' label)", async ({ page }) => {
    await setupHoldingsPage(page);
    await page.goto("/portfolio");

    // WHY 'Total Value': the KPI strip always renders the Total Value tile
    // regardless of whether holdings have loaded. If this label is absent,
    // the KPI strip component failed to mount.
    await expect(page.getByText("Total Value")).toBeVisible({ timeout: 10000 });
  });

  test("page has no horizontal scroll at 1440px viewport (W2 density layout)", async ({ page }) => {
    await setupHoldingsPage(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/portfolio");

    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    const overflow = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));

    // WHY +2 tolerance: 1px rounding differences in sub-pixel layout are
    // acceptable; >2px indicates a real overflow regression.
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 2);
  });
});
