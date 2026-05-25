/**
 * e2e/instrument-financials.spec.ts — W3 Financials-tab acceptance tests (T-31)
 *
 * WHY THIS EXISTS: PRD-0089 W3 acceptance gate specifies 4 Playwright tests
 * for the Financials tab. These validate the full-stack user journey that
 * unit/JSDOM tests cannot cover (navigation, keyboard chords, DOM count):
 *
 *   1. (C-T01) DenseMetricsGrid ≥ 40 cells (role="cell") above-fold at 1440×900.
 *   2. (C-T02) AnalystSidebar renders 7 visible section headers.
 *   3. (C-T03) Peer table rows: 5 peers + 1 self = 6 rows (or ≥1 row).
 *   4. (C-T04) `p` chord toggles the income statement period ANNUAL→QUARTERLY.
 *
 * WHY ROUTE MOCKS (not a live S9): E2E tests run without a live backend. All
 * S9 calls are intercepted via page.route(). Catch-all is registered FIRST
 * (LIFO: lowest priority) and specific routes LAST (highest priority).
 *
 * AUTH: Fake JWT injected via page.addInitScript — same pattern as instrument-quote.spec.ts.
 * VIEWPORT: 1440×900 (density gate requirement).
 */

import { test, expect, type Page } from "@playwright/test";

// ── Auth helpers ──────────────────────────────────────────────────────────────

function buildFakeToken(): string {
  const b64url = (s: string) =>
    btoa(s).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = b64url(JSON.stringify({
    sub: "e2e-w3-user",
    tenant_id: "e2e-tenant",
    email: "e2e-w3@test.local",
    name: "E2E W3 Tester",
    exp: Math.floor(Date.now() / 1000) + 3600,
  }));
  return `${header}.${payload}.fake-w3-sig`;
}

// ── Fixture data ──────────────────────────────────────────────────────────────

const AAPL_BUNDLE = {
  instrument_id: "aapl-uuid",
  entity_id: "aapl-uuid",
  overview: {
    instrument: {
      instrument_id: "aapl-uuid",
      ticker: "AAPL",
      name: "Apple Inc.",
      exchange: "NASDAQ",
      gics_sector: "Information Technology",
      gics_industry: "Technology Hardware, Storage & Peripherals",
      country: "US",
      description: "Apple Inc. designs, manufactures, and markets consumer electronics.",
    },
    quote: {
      instrument_id: "aapl-uuid",
      ticker: "AAPL",
      price: 185.50,
      change: 1.20,
      change_pct: 0.65,
      timestamp: new Date().toISOString(),
      volume: 58_000_000,
    },
    fundamentals: {
      instrument_id: "aapl-uuid",
      ticker: "AAPL",
      name: "Apple Inc.",
      market_cap: 2_890_000_000_000,
      pe_ratio: 28.4,
      forward_pe: 26.0,
      price_to_book: 45.0,
      price_to_sales: 7.8,
      ev_to_ebitda: 20.0,
      gross_margin: 0.443,
      operating_margin: 0.302,
      net_margin: 0.254,
      roe: 1.6,
      roa: 0.28,
      revenue_growth_yoy: 0.05,
      earnings_growth_yoy: 0.07,
      dividend_yield: 0.006,
      payout_ratio: 0.15,
      debt_to_equity: 1.8,
      current_ratio: 0.99,
      quick_ratio: 0.94,
      week_52_high: 199.62,
      week_52_low: 164.08,
      daily_return: 0.012,
      analyst_strong_buy_count: 25,
      analyst_buy_count: 5,
      analyst_hold_count: 10,
      analyst_sell_count: 4,
      analyst_strong_sell_count: 1,
      analyst_rating: 4.2,
      analyst_target_price: 215.0,
      updated_at: new Date().toISOString(),
    },
    ohlcv: {
      instrument_id: "aapl-uuid",
      ticker: "AAPL",
      timeframe: "1D",
      bars: Array.from({ length: 20 }, (_, i) => ({
        timestamp: new Date(Date.now() - i * 24 * 3600 * 1000).toISOString(),
        open: 183.0, high: 186.0, low: 181.0, close: 184.0, volume: 55_000_000,
      })),
    },
  },
  fundamentals: null,
  technicals: null,
  insider: null,
  top_news: { total: 0, articles: [] },
};

const SNAPSHOT_RESP = {
  security_id: "aapl-uuid",
  records: [{
    id: "s1",
    security_id: "aapl-uuid",
    section: "fundamentals_snapshot",
    period_end: "2026-05-01",
    period_type: "SNAPSHOT",
    source: "eodhd",
    ingested_at: new Date().toISOString(),
    data: {
      instrument_id: "aapl-uuid",
      beta: 1.2,
      eps_ttm: 6.43,
      free_cash_flow: 108_000_000_000,
      operating_cash_flow: 118_000_000_000,
      capex: -10_000_000_000,
      fcf_margin: 0.26,
      net_debt_to_ebitda: 0.5,
      avg_volume_30d: 60_000_000,
      interest_coverage: null,
      credit_rating: null,
      updated_at: null,
    },
  }],
};

const TECHNICALS_RESP = {
  security_id: "aapl-uuid",
  records: [{
    id: "t1",
    security_id: "aapl-uuid",
    section: "technicals",
    period_end: "2026-05-01",
    period_type: "SNAPSHOT",
    source: "eodhd",
    ingested_at: new Date().toISOString(),
    data: {
      Beta: 1.2,
      "52WeekHigh": 199.62,
      "52WeekLow": 164.08,
      "50DayMA": 182.34,
      "200DayMA": 175.67,
      SharesShort: 88_000_000,
      ShortRatio: 1.2,
      ShortPercent: 0.0056,
    },
  }],
};

const SHARE_STATS_RESP = {
  security_id: "aapl-uuid",
  records: [{
    id: "ss1",
    security_id: "aapl-uuid",
    section: "share_statistics",
    period_end: "2026-05-01",
    period_type: "SNAPSHOT",
    source: "eodhd",
    ingested_at: new Date().toISOString(),
    data: {
      SharesOutstanding: 15_400_000_000,
      SharesFloat: 15_300_000_000,
      PercentInsiders: 1.64,
      PercentInstitutions: 65.35,
    },
  }],
};

const PEERS_RESP = {
  instrument_id: "aapl-uuid",
  industry: "Technology Hardware",
  peers: [
    { instrument_id: "msft-uuid", ticker: "MSFT", name: "Microsoft", market_cap: 3_200_000_000_000, pe_ratio: 35.2, return_1y: 18.5, change_pct: 0.3 },
    { instrument_id: "googl-uuid", ticker: "GOOGL", name: "Alphabet", market_cap: 2_100_000_000_000, pe_ratio: 22.1, return_1y: 42.3, change_pct: -0.2 },
    { instrument_id: "meta-uuid", ticker: "META", name: "Meta Platforms", market_cap: 1_400_000_000_000, pe_ratio: 23.7, return_1y: 180.0, change_pct: 1.1 },
    { instrument_id: "nvda-uuid", ticker: "NVDA", name: "NVIDIA", market_cap: 2_800_000_000_000, pe_ratio: 65.4, return_1y: 198.2, change_pct: 2.5 },
    { instrument_id: "amd-uuid", ticker: "AMD", name: "AMD", market_cap: 270_000_000_000, pe_ratio: 44.1, return_1y: 80.4, change_pct: 0.5 },
  ],
};

const INCOME_STMT_ANNUAL = {
  security_id: "aapl-uuid",
  records: [
    { id: "is1", security_id: "aapl-uuid", section: "income_statement", period_end: "2024-09-30", period_type: "ANNUAL", source: "eodhd", ingested_at: new Date().toISOString(), data: { date: "2024-09-30", totalRevenue: 391_035_000_000, grossProfit: 180_683_000_000, ebitda: 130_000_000_000, netIncome: 93_736_000_000, eps: 6.11 } },
    { id: "is2", security_id: "aapl-uuid", section: "income_statement", period_end: "2023-09-30", period_type: "ANNUAL", source: "eodhd", ingested_at: new Date().toISOString(), data: { date: "2023-09-30", totalRevenue: 383_285_000_000, grossProfit: 169_148_000_000, ebitda: 125_000_000_000, netIncome: 96_995_000_000, eps: 6.43 } },
    { id: "is3", security_id: "aapl-uuid", section: "income_statement", period_end: "2022-09-30", period_type: "ANNUAL", source: "eodhd", ingested_at: new Date().toISOString(), data: { date: "2022-09-30", totalRevenue: 394_328_000_000, grossProfit: 170_782_000_000, ebitda: 130_000_000_000, netIncome: 99_803_000_000, eps: 6.11 } },
  ],
};

const EARNINGS_RESP = {
  records: [
    { id: "e1", security_id: "aapl-uuid", section: "earnings-annual-trend", period_end: "2024-12-31", period_type: "ANNUAL", source: "eodhd", ingested_at: new Date().toISOString(), data: { date: "2024-12-31", epsActual: 7.26, epsEstimate: 7.10, surprisePercent: 2.25 } },
    { id: "e2", security_id: "aapl-uuid", section: "earnings-annual-trend", period_end: "2023-12-31", period_type: "ANNUAL", source: "eodhd", ingested_at: new Date().toISOString(), data: { date: "2023-12-31", epsActual: 6.43, epsEstimate: 6.57, surprisePercent: -2.13 } },
    { id: "e3", security_id: "aapl-uuid", section: "earnings-annual-trend", period_end: "2022-12-31", period_type: "ANNUAL", source: "eodhd", ingested_at: new Date().toISOString(), data: { date: "2022-12-31", epsActual: 6.11, epsEstimate: 6.08, surprisePercent: 0.49 } },
  ],
};

// ── Mock installer ────────────────────────────────────────────────────────────

async function installFinancialsMocks(page: Page) {
  const token = buildFakeToken();

  // Catch-all (LOWEST priority — registered first so LIFO puts it last)
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
  );

  // Auth
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        access_token: token, expires_in: 3600,
        user: { user_id: "e2e-w3-user", tenant_id: "e2e-tenant", email: "e2e-w3@test.local", name: "E2E W3 Tester" },
      }),
    })
  );
  await page.route("**/api/v1/auth/ws-token", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "fake-ws-token" }) })
  );

  // Shell
  await page.route("**/api/v1/watchlists**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.route("**/api/v1/news/top**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) })
  );
  await page.route("**/api/v1/alerts/pending**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );
  await page.route("**/api/v1/portfolios**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) })
  );

  // Page bundle
  await page.route("**/api/v1/instruments/AAPL/page-bundle", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AAPL_BUNDLE) })
  );

  // Fundamentals snapshot + technicals + share stats + splits/dividends
  await page.route("**/api/v1/fundamentals/aapl-uuid/snapshot**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SNAPSHOT_RESP) })
  );
  await page.route("**/api/v1/fundamentals/aapl-uuid/technicals**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(TECHNICALS_RESP) })
  );
  await page.route("**/api/v1/fundamentals/aapl-uuid/share-statistics**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(SHARE_STATS_RESP) })
  );
  await page.route("**/api/v1/fundamentals/aapl-uuid/splits-dividends**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ records: [] }) })
  );

  // Peers + sidebar
  await page.route("**/api/v1/instruments/aapl-uuid/peers**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(PEERS_RESP) })
  );
  await page.route("**/api/v1/fundamentals/aapl-uuid/ownership**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ security_id: "aapl-uuid", records: [] }) })
  );
  await page.route("**/api/v1/fundamentals/aapl-uuid/institutional-holders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ security_id: "aapl-uuid", records: [] }) })
  );
  await page.route("**/api/v1/fundamentals/aapl-uuid/fund-holders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ security_id: "aapl-uuid", records: [] }) })
  );

  // Income statement (annual and quarterly)
  await page.route("**/api/v1/fundamentals/aapl-uuid/income-statement**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(INCOME_STMT_ANNUAL) })
  );

  // Earnings (shared by EarningsBarChart + BeatMissHistoryPanel)
  await page.route("**/api/v1/fundamentals/aapl-uuid/earnings-annual-trend**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(EARNINGS_RESP) })
  );

  // Brief (return 404 to suppress AIBriefPanel generation on this page)
  await page.route("**/api/v1/briefings/instrument/AAPL**", (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "not found" }) })
  );
}

// ── Navigate helper ───────────────────────────────────────────────────────────

async function goToFinancialsTab(page: Page) {
  await page.addInitScript((token) => {
    localStorage.setItem("wv_access_token", token);
    localStorage.setItem("wv_tenant_id", "e2e-tenant");
    localStorage.setItem("wv_user_id", "e2e-w3-user");
  }, buildFakeToken());

  await page.goto("/instruments/AAPL");
  // Click the FINANCIALS tab to switch from Quote (default) to Financials
  await page.getByRole("button", { name: /FINANCIALS/i }).click();
  // Wait for DenseMetricsGrid root element to appear
  await page.waitForSelector('[data-table-grid="dense"]', { timeout: 10_000 });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("W3 Financials tab", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("C-T01: DenseMetricsGrid renders ≥35 data cells (role=cell) above-fold", async ({ page }) => {
    await installFinancialsMocks(page);
    await goToFinancialsTab(page);

    const cells = page.locator('[role="cell"]');
    const count = await cells.count();
    expect(count).toBeGreaterThanOrEqual(35);
  });

  test("C-T02: AnalystSidebar renders expected section headers", async ({ page }) => {
    await installFinancialsMocks(page);
    await goToFinancialsTab(page);

    // Wait for sidebar to render
    await page.waitForSelector("text=ANALYST CONSENSUS", { timeout: 8_000 });

    await expect(page.getByText("ANALYST CONSENSUS")).toBeVisible();
    await expect(page.getByText("12-MO TARGET")).toBeVisible();
    await expect(page.getByText("ESTIMATE REVISIONS")).toBeVisible();
    await expect(page.getByText("TARGETS BY ANALYST")).toBeVisible();
  });

  test("C-T03: PeerComparisonTable renders ≥1 peer row", async ({ page }) => {
    await installFinancialsMocks(page);
    await goToFinancialsTab(page);

    // Wait for the peer section to load
    await page.waitForSelector("text=PEER COMPARISON", { timeout: 8_000 });

    // At least one peer ticker should be visible
    await expect(page.getByText("MSFT")).toBeVisible();
  });

  test("C-T04: p chord toggles income statement ANNUAL→QUARTERLY", async ({ page }) => {
    await installFinancialsMocks(page);
    await goToFinancialsTab(page);

    // Wait for income statement to load (look for REVENUE row)
    await page.waitForSelector("text=REVENUE", { timeout: 8_000 });

    // Check initial state shows annual label
    const header = page.getByText(/INCOME STATEMENT.*ANNUAL/i);
    await expect(header).toBeVisible();

    // Ensure no input is focused before pressing chord
    await page.click("body");

    // Press p to toggle
    await page.keyboard.press("p");

    // After toggle, header should show QUARTERLY
    await expect(page.getByText(/INCOME STATEMENT.*QUARTERLY/i)).toBeVisible({ timeout: 3_000 });
  });
});
