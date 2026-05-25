/**
 * e2e/instrument-intelligence.spec.ts — W7 T-24 Intelligence-tab acceptance tests
 *
 * WHY THIS EXISTS: PRD-0089 W7 acceptance gate — 4 Playwright tests that validate
 * the full-stack user journey for the Intelligence tab redesign:
 *
 *   1. (I-T01) DenseArticleRow density: ≥30 news rows rendered at 1440×900.
 *   2. (I-T02) Grid layout: news col is col-span-4 (wider than old col-span-3).
 *   3. (I-T03) Entity overview 5-block stack renders in the right rail.
 *   4. (I-T04) j/k keyboard navigation highlights successive news rows.
 *
 * WHY ROUTE MOCKS (not a live S9): E2E tests run without a live backend.
 * All S9 calls are intercepted via page.route(). Catch-all registered FIRST.
 *
 * AUTH: Fake JWT injected via page.addInitScript — same pattern as
 * instrument-financials.spec.ts and instrument-quote.spec.ts.
 *
 * VIEWPORT: 1440×900 (density gate requirement for I-T01).
 */

import { test, expect, type Page } from "@playwright/test";

// ── Auth helpers ──────────────────────────────────────────────────────────────

function buildFakeToken(): string {
  const b64url = (s: string) =>
    btoa(s).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = b64url(JSON.stringify({
    sub: "e2e-w7-user",
    tenant_id: "e2e-tenant",
    email: "e2e-w7@test.local",
    name: "E2E W7 Tester",
    exp: Math.floor(Date.now() / 1000) + 3600,
  }));
  return `${header}.${payload}.fake-w7-sig`;
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
      gics_industry: "Technology Hardware",
      country: "US",
      description: "Apple Inc. designs consumer electronics.",
    },
    quote: { instrument_id: "aapl-uuid", ticker: "AAPL", price: 185.5, change: 1.2, change_pct: 0.65, volume: 1000000, market_cap: 2900000000000 },
    company_snapshot: { instrument_id: "aapl-uuid", full_time_employees: 161000, fiscal_year_end: "September" },
    last_updated: "2026-05-22T08:00:00Z",
  },
};

// 35 articles so the density gate (≥30) has a margin
const AAPL_NEWS = Array.from({ length: 35 }, (_, i) => ({
  article_id: `art-${i}`,
  title: `Apple news headline ${i}`,
  url: `https://example.com/news/${i}`,
  source_name: "Reuters",
  source_type: "eodhd_news",
  published_at: new Date(Date.now() - i * 60_000).toISOString(),
  sentiment: i % 2 === 0 ? "positive" : "negative",
  impact_score: 0.5 + (i % 5) * 0.1,
  relevance_score: 0.9,
}));

const AAPL_ENTITY = {
  entity_id: "aapl-uuid",
  canonical_name: "Apple Inc.",
  entity_type: "financial_instrument",
  description: "Apple designs and sells consumer electronics.",
  data_completeness: 0.85,
  metadata: { employee_count: 161000, founded_year: 1976, headquarters_country: "US" },
};

const AAPL_GRAPH = {
  entity_id: "aapl-uuid",
  nodes: [
    { id: "aapl-uuid", label: "Apple Inc.", type: "financial_instrument", size: 10 },
    { id: "tsmc-uuid", label: "TSMC", type: "financial_instrument", size: 5 },
  ],
  edges: [{ id: "e1", source: "aapl-uuid", target: "tsmc-uuid", label: "SUPPLIER_OF", weight: 0.8 }],
};

// ── Route setup ───────────────────────────────────────────────────────────────

async function setupRoutes(page: Page): Promise<void> {
  // Catch-all: 200 empty for anything unmatched (lowest priority — registered first)
  await page.route("**/v1/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  // Instrument bundle
  await page.route("**/v1/instruments/aapl-uuid/bundle*", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AAPL_BUNDLE) });
  });

  // Entity news (paginated)
  await page.route("**/v1/entities/aapl-uuid/news*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ articles: AAPL_NEWS, next_cursor: null, total: AAPL_NEWS.length }),
    });
  });

  // Entity detail
  await page.route("**/v1/entities/aapl-uuid**", async (route) => {
    const url = route.request().url();
    if (url.includes("/intelligence")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ health_score: 0.8, confidence_breakdown: {} }) });
    } else if (url.includes("/graph")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AAPL_GRAPH) });
    } else if (url.includes("/paths")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ paths: [] }) });
    } else if (url.includes("/contradictions")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ contradictions: [] }) });
    } else if (url.includes("/narratives")) {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ versions: [] }) });
    } else {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(AAPL_ENTITY) });
    }
  });
}

async function navigateToIntelligenceTab(page: Page): Promise<void> {
  await page.addInitScript((token) => {
    window.localStorage.setItem("wv_access_token", token);
    window.localStorage.setItem("wv_refresh_token", "fake-w7-refresh");
  }, buildFakeToken());

  await page.goto("/instruments/aapl-uuid?tab=intelligence");
  await page.waitForLoadState("networkidle");
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe("Intelligence tab — W7 acceptance", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupRoutes(page);
    await navigateToIntelligenceTab(page);
  });

  test("(I-T01) DenseArticleRow density: ≥30 news rows visible", async ({ page }) => {
    // DenseArticleRow renders [role="link"] divs (with article.url) or plain divs
    const newsRows = page.locator("[role='link']");
    await expect(newsRows).toHaveCount(35, { timeout: 10_000 });
    // Spot-check: first row has the 18px height class
    const firstRow = newsRows.first();
    await expect(firstRow).toHaveClass(/h-\[18px\]/);
  });

  test("(I-T02) Layout uses grid-cols-14 (4+7+3 column split)", async ({ page }) => {
    // The Intelligence tab root div should carry grid-cols-14
    const gridEl = page.locator(".grid-cols-14").first();
    await expect(gridEl).toBeVisible({ timeout: 5_000 });

    // News rail should be col-span-4 (wider than the legacy col-span-3)
    const newsRail = gridEl.locator(".col-span-4").first();
    await expect(newsRail).toBeVisible();
  });

  test("(I-T03) Entity overview right rail renders 5-block labels", async ({ page }) => {
    // The right rail shows the entity name when EntityOverviewBlock loads
    await expect(page.getByText("Apple Inc.")).toBeVisible({ timeout: 8_000 });
    // TOP RELATIONS section label
    await expect(page.getByText(/TOP RELATIONS/i)).toBeVisible();
    // PATH INSIGHTS section label
    await expect(page.getByText(/PATH INSIGHTS/i)).toBeVisible();
    // CONTRADICTIONS section label
    await expect(page.getByText(/CONTRADICTIONS/i)).toBeVisible();
    // NARRATIVE HISTORY accordion trigger
    await expect(page.getByText(/NARRATIVE HISTORY/i)).toBeVisible();
  });

  test("(I-T04) j/k keyboard navigation highlights successive news rows", async ({ page }) => {
    // Wait for news rows to load
    await page.waitForSelector("[role='link']");

    // Press 'j' to move selection to first row (index 0)
    await page.keyboard.press("j");
    // The highlighted row carries ring-1 class
    const firstHighlighted = page.locator(".ring-1").first();
    await expect(firstHighlighted).toBeVisible({ timeout: 3_000 });

    // Press 'j' again — second row is now highlighted
    await page.keyboard.press("j");
    // Two ring-1 elements would indicate a bug; exactly one should be highlighted
    const highlighted = page.locator(".ring-1");
    await expect(highlighted).toHaveCount(1);
  });
});
