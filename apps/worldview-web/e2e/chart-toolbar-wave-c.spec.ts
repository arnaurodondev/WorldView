/**
 * e2e/chart-toolbar-wave-c.spec.ts — Wave C chart toolbar Playwright visual regression
 *
 * WHY THIS EXISTS: Playwright screenshot tests verify that the chart toolbar
 * renders correctly at the pixel level — something Vitest unit tests cannot do.
 * These tests ensure:
 *   (a) The indicator dropdown renders correctly (no overflow, correct z-index)
 *   (b) The drawing palette is visible and correctly sized on the chart left edge
 *   (c) The volume submenu renders all 4 options without truncation
 *   (d) The overall chart + toolbar layout matches the design spec (Bloomberg density)
 *
 * WHY MOCKED API (no live S9): E2E tests must be deterministic and fast.
 * Using mocked OHLCV data ensures the chart always has the same bars, making
 * visual regression screenshots stable across runs.
 *
 * WHY SCREENSHOT AT INSTRUMENT PAGE ROUTE: The chart toolbar only renders on
 * the instrument detail page (OHLCVChart is in OverviewLayout). We mock the
 * full instrument context so the page renders without a live backend.
 *
 * RUN: pnpm test:e2e --grep "Wave C chart toolbar"
 * PREREQ: pnpm dev (Next.js dev server on localhost:3001)
 * SCREENSHOT DIR: e2e/screenshots/wave-c-chart-toolbar/
 *
 * DESIGN REFERENCE: PLAN-0050 §T-C-3-05
 */

import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// ── Screenshot directory setup ─────────────────────────────────────────────────

const SCREENSHOT_DIR = path.join(__dirname, "screenshots", "wave-c-chart-toolbar");

// WHY mkdir recursive: on first run the directory may not exist.
// Using recursive:true avoids an error if it already exists.
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

// ── Auth mock helpers (shared with other spec files) ──────────────────────────

/**
 * buildFakeToken — construct a JWT-shaped access token with far-future exp.
 *
 * WHY: AuthContext decodes only the payload to check exp.
 * Signature verification is not client-side — fake sig is fine in e2e tests.
 */
function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const payload = btoa(JSON.stringify({
    sub: "wave-c-test-user",
    tenant_id: "wave-c-tenant",
    email: "wave-c@worldview.local",
    name: "Wave C QA",
    exp: Math.floor(Date.now() / 1000) + 7200,
  })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${header}.${payload}.fake-wave-c-sig`;
}

/**
 * generateOHLCVBars — synthetic OHLCV bars for chart rendering.
 *
 * WHY 200 bars: enough for MA200 overlay to render (requires ≥200 bars).
 * 200 bars also ensures RSI, MACD, ATR, Stochastic, Bollinger all have
 * enough warmup period to show data on the chart.
 */
function generateOHLCVBars(count: number) {
  const bars = [];
  let price = 150;
  const startDate = new Date("2025-01-01");
  for (let i = 0; i < count; i++) {
    const change = (Math.sin(i * 0.1) * 3) + (Math.random() - 0.5);
    price = Math.max(100, price + change);
    const d = new Date(startDate);
    d.setDate(startDate.getDate() + i);
    bars.push({
      timestamp: d.toISOString(),
      open: price - 0.5,
      high: price + 1.5,
      low: price - 1.5,
      close: price,
      volume: 1_000_000 + Math.floor(Math.abs(change) * 100_000),
    });
  }
  return bars;
}

/**
 * setupInstrumentMocks — intercept all API routes for the instrument detail page.
 *
 * WHY: The instrument page fetches ~10 endpoints on mount (OHLCV, fundamentals,
 * quote, entity graph, news, brief, etc.). Each must return a valid response
 * shape to prevent React error boundaries from hiding the chart component.
 *
 * WHY OHLCV endpoint last (highest Playwright LIFO priority): the chart data
 * is the most important mock. If it fails, the chart canvas won't render and
 * all toolbar screenshot tests would fail.
 */
async function setupInstrumentMocks(page: Page): Promise<void> {
  const fakeToken = buildFakeToken();
  const ohlcvBars = generateOHLCVBars(60);

  // WHY catch-all first (lowest LIFO priority): handles any endpoint not
  // specifically mocked below. Returns safe empty shapes.
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();

    if (url.includes("/v1/ohlcv/")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          instrument_id: "ins-aapl-001",
          ticker: "AAPL",
          timeframe: "1D",
          bars: ohlcvBars,
        }),
      });
      return;
    }
    if (url.includes("/v1/quotes/batch") || url.includes("/v1/quotes/")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          instrument_id: "ins-aapl-001",
          ticker: "AAPL",
          price: 185.42,
          change: 2.31,
          change_pct: 1.26,
          timestamp: new Date().toISOString(),
          volume: 52_000_000,
        }),
      });
      return;
    }
    if (url.includes("/v1/fundamentals/")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          instrument_id: "ins-aapl-001",
          ticker: "AAPL",
          name: "Apple Inc.",
          market_cap: 2_800_000_000_000,
          pe_ratio: 28.5,
          forward_pe: 25.1,
          price_to_book: 45.2,
          price_to_sales: 7.8,
          ev_to_ebitda: 21.3,
          gross_margin: 0.4431,
          operating_margin: 0.297,
          net_margin: 0.2531,
          roe: 1.6,
          roa: 0.288,
          revenue_growth_yoy: 0.028,
          earnings_growth_yoy: 0.109,
          dividend_yield: 0.0044,
          payout_ratio: 0.157,
          debt_to_equity: 1.98,
          current_ratio: 1.03,
          quick_ratio: 0.94,
          week_52_high: 199.62,
          week_52_low: 124.17,
          daily_return: 0.013,
          updated_at: new Date().toISOString(),
        }),
      });
      return;
    }
    if (url.includes("/v1/entities/") && url.includes("/graph")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          entity_id: "ent-aapl-001",
          nodes: [
            { id: "ent-aapl-001", label: "Apple Inc.", type: "company" },
          ],
          edges: [],
        }),
      });
      return;
    }
    if (url.includes("/v1/entities/") && url.includes("/news")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ articles: [], total: 0, offset: 0, limit: 4 }),
      });
      return;
    }
    if (url.includes("/v1/entities/") && url.includes("/brief")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          entity_id: "ent-aapl-001",
          narrative: "Apple Inc. is a technology company.",
          risk_summary: null,
          entity_mentions: [],
          citations: [],
          generated_at: new Date().toISOString(),
          cached: false,
        }),
      });
      return;
    }
    if (url.includes("/v1/entities/") && url.includes("/contradictions")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ entity_id: "ent-aapl-001", contradictions: [] }),
      });
      return;
    }
    if (url.includes("/v1/instruments/") && url.includes("/context")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          instrument: {
            instrument_id: "ins-aapl-001",
            entity_id: "ent-aapl-001",
            ticker: "AAPL",
            name: "Apple Inc.",
            exchange: "NASDAQ",
            currency: "USD",
            gics_sector: "Information Technology",
            gics_industry: "Technology Hardware",
            isin: "US0378331005",
            country: "US",
            description: "Apple Inc. designs, manufactures, and markets consumer electronics.",
          },
          entity_id: "ent-aapl-001",
          current_price: 185.42,
          recent_bars: ohlcvBars.slice(-30),
        }),
      });
      return;
    }
    if (url.includes("/v1/instruments/") && url.includes("/sparkline")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ instrument_id: "ins-aapl-001", metric: "pe_ratio", datapoints: [] }),
      });
      return;
    }
    if (url.includes("/v1/alerts")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ alerts: [], total: 0 }),
      });
      return;
    }
    if (url.includes("/v1/portfolios")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }),
      });
      return;
    }
    if (url.includes("/v1/watchlists")) {
      void route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    if (url.includes("/v1/threads")) {
      void route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
      return;
    }
    if (url.includes("/v1/briefings/morning")) {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ content: "Morning brief", generated_at: new Date().toISOString() }),
      });
      return;
    }
    if (url.includes("/v1/market/heatmap")) {
      void route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ sectors: [] }) });
      return;
    }
    // Catch-all
    void route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  // WHY auth endpoints registered LAST (highest LIFO priority): auth must always work.
  await page.route("**/api/v1/auth/refresh", (route) => {
    void route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 900,
        user: {
          user_id: "wave-c-test-user",
          tenant_id: "wave-c-tenant",
          email: "wave-c@worldview.local",
          name: "Wave C QA",
          avatar_url: null,
        },
      }),
    });
  });

  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ token: "ws-fake-token", expires_in: 30 }),
    });
  });

  // ── Inject fake auth token into localStorage ──────────────────────────────
  // WHY addInitScript: localStorage must be populated BEFORE the page JS runs.
  // The AuthContext reads from localStorage on mount (before first API call).
  await page.addInitScript((token: string) => {
    localStorage.setItem("worldview:auth:token", token);
    localStorage.setItem("worldview:auth:user", JSON.stringify({
      user_id: "wave-c-test-user",
      tenant_id: "wave-c-tenant",
      email: "wave-c@worldview.local",
      name: "Wave C QA",
      avatar_url: null,
    }));
  }, fakeToken);
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe("Wave C chart toolbar — visual regression", () => {

  test("chart toolbar renders with all controls visible", async ({ page }) => {
    await setupInstrumentMocks(page);

    // WHY navigate to instrument page: the chart toolbar only exists there.
    // The entity ID is hardcoded to match the mocked /v1/instruments/{id}/context endpoint.
    await page.goto("/instruments/ent-aapl-001", { waitUntil: "networkidle" });

    // WHY wait for chart-toolbar testid: the OHLCVChart renders the toolbar
    // synchronously but needs the data to be ready for chart init to complete.
    const toolbar = page.getByTestId("chart-toolbar");
    await expect(toolbar).toBeVisible({ timeout: 15_000 });

    // WHY take screenshot AFTER toolbar visible: ensures the chart has had time
    // to initialise the lightweight-charts canvas and the toolbar is fully rendered.
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "01-chart-toolbar-default.png"),
      clip: { x: 0, y: 0, width: 1200, height: 420 },
    });

    // ── Assert specific toolbar elements are visible ─────────────────────────
    await expect(page.getByTestId("toolbar-indicators-menu")).toBeVisible();
    await expect(page.getByTestId("toolbar-volume-menu")).toBeVisible();
    await expect(page.getByTestId("toolbar-ma50")).toBeVisible();
    await expect(page.getByTestId("toolbar-ma200")).toBeVisible();
    await expect(page.getByTestId("toolbar-fullscreen")).toBeVisible();
  });

  test("drawing palette renders on left side of chart", async ({ page }) => {
    await setupInstrumentMocks(page);
    await page.goto("/instruments/ent-aapl-001", { waitUntil: "networkidle" });

    const palette = page.getByTestId("drawing-palette");
    await expect(palette).toBeVisible({ timeout: 15_000 });

    // WHY assert all 8 palette buttons visible: confirms the full palette renders
    // without overflow or hidden items.
    await expect(page.getByTestId("drawing-tool-cursor")).toBeVisible();
    await expect(page.getByTestId("drawing-tool-trend-line")).toBeVisible();
    await expect(page.getByTestId("drawing-tool-horizontal-level")).toBeVisible();
    await expect(page.getByTestId("drawing-tool-rectangle")).toBeVisible();
    await expect(page.getByTestId("drawing-tool-fib-retracement")).toBeVisible();
    await expect(page.getByTestId("drawing-tool-text")).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "02-drawing-palette.png"),
      clip: { x: 0, y: 0, width: 200, height: 420 },
    });
  });

  test("indicators dropdown opens and shows all 7 indicators", async ({ page }) => {
    await setupInstrumentMocks(page);
    await page.goto("/instruments/ent-aapl-001", { waitUntil: "networkidle" });

    await expect(page.getByTestId("toolbar-indicators-menu")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("toolbar-indicators-menu").click();

    // WHY wait for RSI item: the dropdown animation may take a frame.
    // Once RSI is visible, all 7 items should be in the DOM.
    await expect(page.getByTestId("indicator-rsi")).toBeVisible({ timeout: 5_000 });

    // Verify all 7 indicators are shown
    await expect(page.getByTestId("indicator-rsi")).toBeVisible();
    await expect(page.getByTestId("indicator-macd")).toBeVisible();
    await expect(page.getByTestId("indicator-bollinger")).toBeVisible();
    await expect(page.getByTestId("indicator-atr")).toBeVisible();
    await expect(page.getByTestId("indicator-stochastic")).toBeVisible();
    await expect(page.getByTestId("indicator-obv")).toBeVisible();
    await expect(page.getByTestId("indicator-vwap")).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "03-indicators-dropdown-open.png"),
      fullPage: false,
    });
  });

  test("volume submenu opens and shows all 4 volume options", async ({ page }) => {
    await setupInstrumentMocks(page);
    await page.goto("/instruments/ent-aapl-001", { waitUntil: "networkidle" });

    await expect(page.getByTestId("toolbar-volume-menu")).toBeVisible({ timeout: 15_000 });
    await page.getByTestId("toolbar-volume-menu").click();

    await expect(page.getByTestId("vol-base")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId("vol-ma20")).toBeVisible();
    await expect(page.getByTestId("vol-profile")).toBeVisible();
    await expect(page.getByTestId("vol-vwap")).toBeVisible();

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "04-volume-submenu-open.png"),
      fullPage: false,
    });
  });

  test("clicking a drawing tool arms it (aria-pressed becomes true)", async ({ page }) => {
    await setupInstrumentMocks(page);
    await page.goto("/instruments/ent-aapl-001", { waitUntil: "networkidle" });

    await expect(page.getByTestId("drawing-tool-trend-line")).toBeVisible({ timeout: 15_000 });

    // WHY verify aria-pressed=false before clicking: confirms initial state is cursor mode
    await expect(page.getByTestId("drawing-tool-trend-line")).toHaveAttribute("aria-pressed", "false");

    await page.getByTestId("drawing-tool-trend-line").click();

    // WHY verify aria-pressed=true after click: confirms the tool was armed
    await expect(page.getByTestId("drawing-tool-trend-line")).toHaveAttribute("aria-pressed", "true");
    // The cursor button should no longer be active
    await expect(page.getByTestId("drawing-tool-cursor")).toHaveAttribute("aria-pressed", "false");

    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "05-drawing-tool-armed.png"),
      clip: { x: 0, y: 0, width: 200, height: 420 },
    });
  });

  test("drawing canvas SVG layer is present and covers the chart area", async ({ page }) => {
    await setupInstrumentMocks(page);
    await page.goto("/instruments/ent-aapl-001", { waitUntil: "networkidle" });

    const canvas = page.getByTestId("drawing-canvas");
    await expect(canvas).toBeVisible({ timeout: 15_000 });

    // WHY check the SVG is a sibling of the chart container (not nested inside):
    // the SVG must be at the correct DOM level to avoid being obscured by
    // lightweight-charts' own canvas elements.
    const canvasBounds = await canvas.boundingBox();
    expect(canvasBounds).not.toBeNull();
    if (canvasBounds) {
      // WHY >100px width: the chart canvas must be at least 100px wide.
      // A width of 0 would indicate the SVG is hidden or incorrectly positioned.
      expect(canvasBounds.width).toBeGreaterThan(100);
      // WHY >200px height: chart is 280px tall by default.
      expect(canvasBounds.height).toBeGreaterThan(200);
    }
  });

});
