/**
 * e2e/transactions-filters.spec.ts — Playwright e2e for the Transactions
 * tab on the portfolio page (PLAN-0051 T-A-1-07).
 *
 * WHY THIS EXISTS: Vitest covers the component in isolation, but the
 * filter bar is wired into a tab that requires the full data-loading
 * waterfall (auth → portfolios → holdings → transactions) to render.
 * These browser tests confirm that the filters survive the round-trip
 * through TanStack Query and the route mocks, that the Realized P&L
 * tile actually appears on the page, and that the CSV export triggers
 * a real `downloads` event in the browser.
 *
 * WHY route-mock all API calls: the e2e environment is headless and
 * `pnpm dev` spins up only the frontend; S9 is not running. Mocking the
 * gateway with deterministic JSON gives us a stable component tree
 * without depending on real backend availability.
 */

import { test, expect, type Page } from "@playwright/test";

// ── Shared helpers ───────────────────────────────────────────────────────────

/**
 * Build a JWT-shaped fake token whose payload carries a future exp claim.
 * AuthContext only decodes the payload (no signature verification client-side),
 * so any well-formed base64 payload is accepted.
 */
function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const payload = btoa(
    JSON.stringify({
      sub: "e2e-test-user",
      tenant_id: "e2e-test-tenant",
      email: "e2e@test.local",
      name: "E2E Test User",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.fake-e2e-sig`;
}

/**
 * Register the mocks the portfolio page needs to render with content.
 *
 * WHY in a helper (not a fixture): each test needs slightly different
 * portfolio / transaction / realized-pnl payloads, but the auth + ws +
 * empty-default mocks are identical across every test. Sharing here
 * keeps the per-test code focused on what's unique to the test.
 */
async function setupPortfolioRoutes(
  page: Page,
  opts: {
    /** Whether the realized-pnl endpoint should respond OK (true) or 503 (false). */
    realizedPnlOk?: boolean;
  } = {},
) {
  const { realizedPnlOk = true } = opts;
  const fakeToken = buildFakeToken();

  await page.route("**/api/v1/auth/refresh", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 3600,
        user: {
          user_id: "e2e-test-user",
          tenant_id: "e2e-test-tenant",
          email: "e2e@test.local",
          name: "E2E Test User",
        },
      }),
    });
  });

  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-token" }),
    });
  });

  // GET /v1/portfolios → S1 PortfolioResponse[] shape (ID is `id`, not `portfolio_id`)
  await page.route("**/api/v1/portfolios", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "port-e2e",
          tenant_id: "e2e-test-tenant",
          owner_id: "e2e-test-user",
          name: "E2E Portfolio",
          currency: "USD",
          status: "active",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]),
    });
  });

  // GET /v1/portfolios/{id}/holdings
  await page.route("**/api/v1/portfolios/**/holdings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        portfolio_id: "port-e2e",
        holdings: [],
        total_value: 0,
        total_cost: 0,
        total_unrealised_pnl: 0,
        total_unrealised_pnl_pct: 0,
      }),
    }),
  );

  // GET /v1/portfolios/{id}/realized-pnl — optionally degrade to 503 to test fallback.
  await page.route("**/api/v1/portfolios/**/realized-pnl**", (route) => {
    if (!realizedPnlOk) {
      return route.fulfill({ status: 503, contentType: "application/json", body: "{}" });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        portfolio_id: "port-e2e",
        from: "2026-01-01",
        to: "2026-04-29",
        total_realized: 1234.56,
        realized_long_term: 800,
        realized_short_term: 434.56,
        count: 3,
        breakdown_by_instrument: [],
        currency: "USD",
      }),
    });
  });

  // GET /v1/transactions — list shape, S1 TransactionListItem
  await page.route("**/api/v1/transactions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            id: "tx-aapl-1",
            portfolio_id: "port-e2e",
            instrument_id: "ins-aapl",
            transaction_type: "BUY",
            direction: "INFLOW",
            quantity: "10",
            price: "150.00",
            fees: "1.00",
            amount: null,
            currency: "USD",
            ticker: "AAPL",
            name: "Apple Inc",
            executed_at: "2026-02-01T15:30:00Z",
            external_ref: null,
            created_at: "2026-02-01T15:30:00Z",
          },
          {
            id: "tx-msft-1",
            portfolio_id: "port-e2e",
            instrument_id: "ins-msft",
            transaction_type: "SELL",
            direction: "OUTFLOW",
            quantity: "5",
            price: "400.00",
            fees: "1.00",
            amount: null,
            currency: "USD",
            ticker: "MSFT",
            name: "Microsoft",
            executed_at: "2026-03-15T15:30:00Z",
            external_ref: null,
            created_at: "2026-03-15T15:30:00Z",
          },
        ],
        total: 2,
        limit: 100,
        offset: 0,
      }),
    }),
  );

  // Default stub for everything else (watchlists, brokerage, etc.) so the
  // queries resolve and don't keep the page in a perpetual loading state.
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
}

// ─────────────────────────────────────────────────────────────────────────────

test.describe("Portfolio /transactions filter bar", () => {
  test("ticker filter narrows the list and Clear filters restores it", async ({
    page,
  }) => {
    await setupPortfolioRoutes(page);
    await page.goto("/portfolio");

    // Wait for the page shell + tabs to render
    await page.getByRole("tab", { name: "Transactions" }).waitFor();
    await page.getByRole("tab", { name: "Transactions" }).click();

    // Both rows visible initially
    await expect(page.getByText("AAPL")).toBeVisible();
    await expect(page.getByText("MSFT")).toBeVisible();

    // Apply ticker filter "MSFT" → AAPL row drops out
    await page.getByLabel("Filter by ticker").fill("MSFT");
    await expect(page.getByText("AAPL")).not.toBeVisible();
    await expect(page.getByText("MSFT")).toBeVisible();

    // Clear filters → AAPL is back
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByText("AAPL")).toBeVisible();
  });

  test("CSV export button triggers a download", async ({ page }) => {
    await setupPortfolioRoutes(page);
    await page.goto("/portfolio");

    await page.getByRole("tab", { name: "Transactions" }).waitFor();
    await page.getByRole("tab", { name: "Transactions" }).click();

    // Listen for the download event Playwright emits when the synthetic
    // anchor click triggers a real save.
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export transactions as CSV" }).click(),
    ]);

    // Filename matches the transactions-YYYY-MM-DD.csv pattern.
    expect(download.suggestedFilename()).toMatch(/^transactions-\d{4}-\d{2}-\d{2}\.csv$/);
  });

  test("Realized P&L tile renders on the portfolio page", async ({ page }) => {
    await setupPortfolioRoutes(page, { realizedPnlOk: true });
    await page.goto("/portfolio");

    // The tile lives in the KPI strip, always visible above the tabs.
    const tile = page.getByTestId("kpi-realized-pnl");
    await expect(tile).toBeVisible();
    // Server payload total_realized = 1234.56 → formatted with thousand sep
    await expect(tile).toContainText("1,234");
    // FIFO endpoint succeeded → no (approx) badge
    await expect(tile).not.toContainText("(approx)");
  });

  test("Realized P&L falls back to (approx) badge when backend is 503", async ({
    page,
  }) => {
    await setupPortfolioRoutes(page, { realizedPnlOk: false });
    await page.goto("/portfolio");

    const tile = page.getByTestId("kpi-realized-pnl");
    await expect(tile).toBeVisible();
    await expect(tile).toContainText("(approx)");
  });
});
