/**
 * e2e/portfolio-overview-perf.spec.ts — Portfolio page load correctness + FPS canary
 *
 * WHY THIS EXISTS: The W2 portfolio page fires 9+ parallel TanStack Query
 * requests on mount (portfolios, holdings, quotes, transactions, watchlists,
 * brokerage, exposure, performance, ohlcv). Any one of these failing should
 * NOT crash the page — only that widget should show an error state.
 *
 * Tests:
 * 1. Page loads and renders the shell (no JS errors, no Application error overlay)
 * 2. Page handles all-500 gracefully (each widget degrades independently)
 * 3. Page handles auth token correctly (no 401 flash on load)
 * 4. (C-37) Scroll FPS ≥ 60 with 100-row fixture at 1440×900 viewport
 *
 * WHY "perf" in the filename: this spec was named after the "performance"
 * requirement in PRD-0089 W2 §4.21 (page must load without errors). Tests
 * 1-3 are correctness tests; test 4 is the C-37 FPS canary.
 *
 * DATA SOURCE: installStrictApiMocks() from e2e/fixtures/api-mocks.ts
 * DESIGN REFERENCE: PRD-0089 W2 §4.21 (no-error load), C-37 (scroll FPS ≥ 60)
 */

import { test, expect } from "@playwright/test";
import { forceAdvancedMode } from "./utils/forceAdvancedMode";
import {
  installStrictApiMocks,
  collectCriticalErrors,
  filterCriticalErrors,
} from "./fixtures/api-mocks";

// PLAN-0122 W-B (T-A-B-05): the portfolio page now defaults to SIMPLE. Every
// spec below asserts the full Advanced layout, so force Advanced before each
// navigation (R19 — no assertion weakened, only the mode that shows the layout).
test.beforeEach(async ({ page }) => {
  await forceAdvancedMode(page);
});

test.describe("Portfolio W2 — page load correctness", () => {
  test("page loads without JS errors when all APIs return 200", async ({ page }) => {
    const errors = collectCriticalErrors(page);
    await installStrictApiMocks(page);

    // WHY extra mocks: W2 page fires brokerage + exposure queries not in
    // installStrictApiMocks. Without them, the requests would fail with
    // net::ERR_CONNECTION_REFUSED (dev server only, no S9 running).
    await page.route("**/api/v1/brokerage/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
    await page.route("**/api/v1/portfolios/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 10000 });

    // WHY "Application error": that's the Next.js global error overlay text.
    // If a React component throws an uncaught error during render, Next.js
    // shows this string. It must not appear.
    await expect(page.locator("body")).not.toContainText("Application error");

    // WHY filterCriticalErrors: net::ERR and WebSocket errors are expected in
    // the test environment (no S9, no S10 running). Only real JS errors matter.
    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("page does not crash when all data APIs return 500", async ({ page }) => {
    const errors = collectCriticalErrors(page);

    // WHY 500 for data endpoints (not auth): broken auth prevents page load
    // entirely, masking the error resilience behaviour we want to test.
    await installStrictApiMocks(page, 500);

    await page.goto("/portfolio");
    await page.waitForLoadState("domcontentloaded");

    // Must not show Next.js global error overlay
    const body = await page.textContent("body");
    expect(body).not.toContain("Application error");

    // WHY not assert shell visible: 500 on portfolios may redirect to login
    // or show an error banner. The spec only asserts no crash, not specific
    // content — error UI is acceptable, crash UI is not.
    expect(filterCriticalErrors(errors)).toHaveLength(0);
  });

  test("unauthenticated user is redirected to /login", async ({ page }) => {
    // WHY: Portfolio page is behind auth middleware (middleware.ts).
    // Without a valid token, the user must be redirected to /login.
    // This is a regression guard — if the middleware breaks, sensitive data
    // would be visible to unauthenticated users.
    await page.goto("/portfolio");
    await expect(page).toHaveURL(/\/login/, { timeout: 8000 });
  });
});

// ── C-37: scroll FPS canary ────────────────────────────────────────────────────

test.describe("Portfolio W2 — C-37 scroll FPS canary", () => {
  /**
   * Generate 100 raw S1 holdings for the FPS fixture.
   *
   * WHY raw S1 format: getHoldings() at /v1/holdings/{portfolioId} receives
   * RawHolding[] and transforms them client-side. The mock must match the wire
   * format (flat array with Decimal-as-string quantities), not the frontend type.
   */
  function make100Holdings(): object[] {
    const tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "V", "UNH"];
    return Array.from({ length: 100 }, (_, i) => ({
      id: `h-${i}`,
      portfolio_id: "port-perf",
      instrument_id: `ins-${i}`,
      entity_id: `ent-${i}`,
      ticker: tickers[i % tickers.length],
      name: `Stock ${i} Inc.`,
      quantity: `${(i + 1) * 2}.00000000`,
      average_cost: `${50 + i}.00000000`,
      currency: "USD",
    }));
  }

  test("C-37 — grid scrolls at ≥ 60 FPS with 100-row fixture", async ({ page }, testInfo) => {
    // WHY skip on webkit: Playwright's WebKit runner throttles requestAnimationFrame to
    // ~30 fps even in headless mode (no vsync, but internal timer cap). Chromium lifts
    // the vsync cap in headless so rAF runs at CPU speed, easily exceeding 60 fps when
    // there is no layout thrashing. The FPS canary is therefore Chromium-only.
    // See: https://github.com/microsoft/playwright/issues/17450 (WebKit rAF throttle)
    if (testInfo.project.name === "webkit") {
      test.skip(true, "WebKit throttles rAF to ~30 fps in headless mode — Chromium only for C-37");
    }

    // WHY 1440×900: the density requirement (§4.14) specifies this viewport;
    // FPS test must validate at the same dimensions.
    await page.setViewportSize({ width: 1440, height: 900 });

    const fakeToken = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_") +
      "." +
      btoa(JSON.stringify({ sub: "e2e-fps", tenant_id: "e2e-tenant", email: "e2e@test.local", name: "FPS Tester", exp: Math.floor(Date.now() / 1000) + 3600 })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_") +
      ".fake-fps-sig";

    // WHY catch-all FIRST: Playwright 1.36+ uses LIFO route matching (last registered
    // wins). The catch-all must be registered FIRST so it gets the LOWEST priority;
    // specific routes registered after it take precedence.
    // WHY URL-aware: ExposureCurrencyStrip calls exposure.leverage.toFixed(2) without
    // a null guard; returning {} causes a runtime crash before the grid renders.
    await page.route("**/api/v1/**", (route) => {
      const url = route.request().url();
      if (url.includes("/exposure")) {
        return route.fulfill({ status: 200, contentType: "application/json",
          body: JSON.stringify({ invested: 0, cash: 0, gross_exposure_pct: 0, net_exposure_pct: 0, leverage: 1.0, prices_stale: false }) });
      }
      if (url.includes("/concentration")) {
        return route.fulfill({ status: 200, contentType: "application/json",
          body: JSON.stringify({ portfolio_id: "port-perf", hhi: 0, label: "empty", top_3_share_pct: 0, positions_count: 0, top_positions: [], prices_stale: false }) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    await page.route("**/api/v1/auth/refresh", (route) =>
      route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({ access_token: fakeToken, expires_in: 3600, user: { user_id: "e2e-fps", tenant_id: "e2e-tenant", email: "e2e@test.local", name: "FPS Tester" } }),
      }),
    );
    await page.route("**/api/v1/auth/ws-token", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ token: "fake-ws" }) }),
    );

    // S1 envelope for portfolios
    await page.route("**/api/v1/portfolios", (route) => {
      if (route.request().method() !== "GET") return route.fallback();
      return route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          items: [{ id: "port-perf", tenant_id: "e2e-tenant", owner_id: "e2e-fps", name: "Perf Portfolio", currency: "USD", status: "active", kind: "manual", created_at: "2026-01-01T00:00:00Z" }],
          total: 1, limit: 100, offset: 0,
        }),
      });
    });

    // 100 holdings in S1 raw format
    const holdings = make100Holdings();
    await page.route("**/api/v1/holdings/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(holdings) }),
    );

    // Flat quotes for all 100 holdings
    const quotes = Object.fromEntries(
      holdings.map((h) => {
        const holding = h as { instrument_id: string; ticker: string; average_cost: string };
        return [
          holding.instrument_id,
          { instrument_id: holding.instrument_id, ticker: holding.ticker, price: parseFloat(holding.average_cost) * 1.1, change: 1.0, change_pct: 0.5, timestamp: "2026-05-01T15:00:00Z", volume: 100_000 },
        ];
      }),
    );
    await page.route("**/api/v1/quotes/batch**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ quotes }) }),
    );

    // WHY concentration mock: ConcentrationSectorTeaseStrip fetches /v1/portfolios/{id}/concentration
    // independently. Without this mock the catch-all returns {} → getConcentration maps it to
    // { hhi: undefined, ... } → truthy → component calls undefined.toFixed(0) → TypeError crashes
    // the error boundary before the AG Grid ever renders (same bug as density.spec.ts).
    await page.route("**/api/v1/portfolios/**/concentration", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          portfolio_id: "port-perf",
          hhi: 950,
          label: "diversified",
          top_3_share_pct: "30.00",
          positions_count: 100,
          top_positions: [],
          prices_stale: false,
        }),
      }),
    );

    await page.goto("/portfolio");

    // Wait for the AG Grid to render (at least one cell visible)
    await page.waitForSelector(".ag-cell", { timeout: 15000 });

    // WHY no toBeVisible() on ag-body-viewport: AG Grid internally toggles
    // visibility: hidden on this element during its initialization lifecycle.
    // waitForSelector(".ag-cell") above already proves the grid has rendered;
    // we reference the viewport only to pass it into the rAF scroll loop.
    const gridViewport = page.locator(".ag-body-viewport");

    // Measure FPS during a programmatic scroll of the AG Grid.
    // WHY rAF timing: the FPS gate is ≥60 average across 60 consecutive frames.
    // A single dropped frame doesn't fail this — sustained jank would.
    const fps = await page.evaluate(async () => {
      const maybeContainer = document.querySelector(".ag-body-viewport");
      if (!maybeContainer) return 0;
      // Narrowed to non-null so the closure below can use it without `!`.
      const container: Element = maybeContainer;

      return new Promise<number>((resolve) => {
        const FRAMES = 60;
        const timestamps: number[] = [];
        let scrollDir = 1;
        let scrollPos = 0;
        let frame = 0;

        function tick(ts: number) {
          timestamps.push(ts);
          // Scroll down then up to exercise both directions
          scrollPos += scrollDir * 20;
          if (scrollPos > 1000) scrollDir = -1;
          if (scrollPos < 0) { scrollPos = 0; scrollDir = 1; }
          (container as HTMLElement).scrollTop = scrollPos;

          frame++;
          if (frame < FRAMES) {
            requestAnimationFrame(tick);
          } else {
            // Compute average FPS from consecutive frame deltas
            let totalMs = 0;
            for (let i = 1; i < timestamps.length; i++) {
              totalMs += timestamps[i] - timestamps[i - 1];
            }
            const avgFrameMs = totalMs / (timestamps.length - 1);
            resolve(avgFrameMs > 0 ? 1000 / avgFrameMs : 0);
          }
        }

        requestAnimationFrame(tick);
      });
    });

    // C-37: scroll FPS must be ≥ 60 to satisfy the W2 performance requirement.
    // In a headless browser, vsync is disabled so rAF runs as fast as possible
    // — the 60 FPS floor is easily met when the grid has no layout thrashing.
    // A value below 60 indicates forced synchronous layout or excessive DOM work.
    expect(fps).toBeGreaterThanOrEqual(60);
  });
});
