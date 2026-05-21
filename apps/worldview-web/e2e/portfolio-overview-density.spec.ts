/**
 * e2e/portfolio-overview-density.spec.ts — Data cell density regression guard
 *
 * WHY THIS EXISTS: W2 sets rowHeight=20px (Bloomberg terminal density) and
 * uses `font-mono text-[11px]` for data cells. If a style regression raises
 * the row height or hides cells, users lose the compact view. These tests
 * assert that data cells render correctly when holdings are returned.
 *
 * WHY mock URL is "/api/v1/holdings/**" (not "/portfolios/{id}/holdings"):
 * The gateway's getHoldings() calls /v1/holdings/{portfolioId} (not the
 * portfolios sub-route). The raw S1 format is a flat array of RawHolding;
 * the gateway transforms this into the frontend Holding shape client-side.
 *
 * WHY mock portfolios body uses S1 envelope: getPortfolios() expects
 * { items: [...], total, limit, offset } — the raw S9/S1 paginated shape.
 *
 * V1 gate (C-36): ≥281 data cells at 1440×900 — verified by the fourth test.
 * Formula: 14 cols × ≥21 rows (with 25 holdings all fit in the visible height).
 *
 * DATA SOURCE: Route mocks — portfolio returns AAPL holding (raw S1 format).
 * DESIGN REFERENCE: PRD-0089 W2 §4.14 (rowHeight=20 density lock), C-36
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

/**
 * makeFakeHolding — generate a single S1 raw holding.
 *
 * WHY S1 raw format: getHoldings() receives RawHolding[] from the API and
 * transforms it client-side. The mock must mirror the wire format, not the
 * frontend Holding type (which has null computed fields like current_price).
 */
function makeFakeHolding(i: number) {
  const tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "BRK.B", "JNJ",
                   "V", "UNH", "HD", "PG", "MA", "AVGO", "LLY", "MRK", "CVX", "ABBV",
                   "PEP", "COST", "TMO", "MCD", "BAC"];
  const ticker = tickers[i % tickers.length];
  return {
    id: `h-${ticker.toLowerCase().replace(".", "-")}-${i}`,
    portfolio_id: "port-density",
    instrument_id: `ins-${ticker.toLowerCase().replace(".", "-")}`,
    entity_id: `ent-${ticker.toLowerCase().replace(".", "-")}`,
    ticker,
    name: `${ticker} Inc.`,
    quantity: `${(i + 1) * 5}.00000000`,
    average_cost: `${100 + i * 3}.00000000`,
    currency: "USD",
  };
}

async function setupHoldingsPage(page: Page, holdingCount = 1) {
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

  // WHY S1 envelope format: getPortfolios() expects { items: [...], total, limit, offset }
  // not a bare array. The gateway transforms items into Portfolio[] client-side.
  await page.route("**/api/v1/portfolios", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "port-density",
            tenant_id: "e2e-tenant",
            owner_id: "e2e-user",
            name: "Density Portfolio",
            currency: "USD",
            status: "active",
            kind: "manual",
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    });
  });

  // WHY **/api/v1/holdings/** (not /portfolios/**/holdings):
  // getHoldings(portfolioId) calls /v1/holdings/{portfolioId} — the S1 endpoint
  // lives under the holdings path, not nested under portfolios.
  // WHY raw array: getHoldings() maps RawHolding[] to Holding[] client-side.
  const holdings = Array.from({ length: holdingCount }, (_, i) => makeFakeHolding(i));
  await page.route("**/api/v1/holdings/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(holdings),
    }),
  );

  // Build quotes keyed by instrument_id from the holdings we generated
  const quotes = Object.fromEntries(
    holdings.map((h) => [
      h.instrument_id,
      {
        instrument_id: h.instrument_id,
        ticker: h.ticker,
        price: parseFloat(h.average_cost) * 1.09,
        change: 1.5,
        change_pct: 0.82,
        timestamp: "2026-05-01T15:00:00Z",
        volume: 1_000_000,
      },
    ]),
  );
  await page.route("**/api/v1/quotes/batch**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ quotes }),
    }),
  );

  // Catch-all — must be registered LAST so specific routes above take priority (FIFO)
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Portfolio W2 — holdings table density", () => {
  test("renders AAPL ticker when holdings are returned", async ({ page }) => {
    await setupHoldingsPage(page, 1);
    await page.goto("/portfolio");

    // WHY waitForSelector: AG Grid renders cells asynchronously after data resolves.
    // The 10s budget accounts for auth-refresh round-trip + TanStack Query hydration.
    await page.waitForSelector("text=AAPL", { timeout: 10000 });

    // Assert AAPL is visible — the table rendered at least one real data row.
    await expect(page.getByText("AAPL").first()).toBeVisible();
  });

  test("KPI strip 'Total Value' label is visible when holdings loaded", async ({ page }) => {
    await setupHoldingsPage(page, 1);
    await page.goto("/portfolio");

    // WHY 'Total Value': the KPI strip renders this label as the first tile once
    // holdingsResp is non-null. If this label is absent after 10s, either the
    // loading skeleton never resolved or PortfolioKPIStrip failed to mount.
    await expect(page.getByText("Total Value")).toBeVisible({ timeout: 10000 });
  });

  test("page has no horizontal scroll at 1440px viewport (W2 density layout)", async ({ page }) => {
    await setupHoldingsPage(page, 1);
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

  test("≥281 AG Grid data cells visible at 1440×900 viewport (C-36 V1 gate)", async ({ page }) => {
    // WHY 25 holdings: 14 cols × 25 rows = 350 potential cells. At 1440×900,
    // the table viewport is ≈550px tall → ~27 rows visible → all 25 rows render
    // simultaneously, giving 25 × 14 = 350 cells (well above the 281 gate).
    await setupHoldingsPage(page, 25);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/portfolio");

    // Wait for the first ticker to appear before counting cells
    await page.waitForSelector(".ag-cell", { timeout: 12000 });

    // WHY ag-cell: AG Grid renders each grid cell with this class. Data cells only
    // (not headers). Count all rendered cells at the 1440×900 density viewport.
    const cellCount = await page.locator(".ag-cell").count();

    // C-36 V1 gate: at least 281 data cells must be visible at 1440×900.
    // If this fails, a style regression increased rowHeight beyond 20px or
    // the AG Grid virtualisation is culling too many rows from the DOM.
    expect(cellCount).toBeGreaterThanOrEqual(281);
  });
});
