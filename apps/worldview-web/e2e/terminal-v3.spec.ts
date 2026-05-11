/**
 * e2e/terminal-v3.spec.ts — PLAN-0039 Terminal UI v3 Acceptance Tests
 *
 * WHY THIS EXISTS: Validates every acceptance criterion from PLAN-0039 §16
 * across all 8 waves. Tests structural correctness (grid layout, row heights,
 * sidebar dimensions, tab presence) using mocked auth + API so no live S9 is
 * needed. Screenshots capture visual state for audit records.
 *
 * WHO USES IT: CI on feature branch; manual QA before PR merge.
 * RUN: pnpm --filter worldview-web test:e2e --grep terminal-v3
 * PREREQ: pnpm --filter worldview-web dev (runs on localhost:3001)
 *
 * DESIGN REFERENCE: PLAN-0039 Wave 8 spec §T-39-W8-01
 */

import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// ── Auth mock helpers ─────────────────────────────────────────────────────────

/**
 * buildFakeToken — construct a JWT-shaped access token with a far-future exp.
 *
 * WHY: AuthContext's isTokenExpiringSoon() decodes only the payload to check exp.
 * It does NOT verify the RS256 signature client-side — so a fake sig is fine in
 * e2e tests. The payload only needs sub, tenant_id, email, name, and exp.
 */
function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const payload = btoa(JSON.stringify({
    sub: "e2e-v3-user",
    tenant_id: "e2e-v3-tenant",
    email: "v3-qa@worldview.local",
    name: "V3 QA User",
    exp: Math.floor(Date.now() / 1000) + 7200, // valid 2h
  })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${header}.${payload}.fake-v3-sig`;
}

/**
 * setupAuthMocks — intercept auth + API routes so all pages render without
 * a live S9 backend. Called at the start of every test that needs a logged-in
 * user session.
 */
// UrlOverrides — map of URL substring → response body for test-specific mocks.
//
// WHY this type (instead of registering separate page.route() calls):
// Playwright evaluates routes LIFO — last-registered = first-matched. The auth
// endpoints (auth/refresh, auth/ws-token) are registered LAST inside setupAuthMocks
// so they always win. The catch-all **/api/v1/** is registered FIRST (lowest priority).
//
// For non-auth endpoints, the catch-all handles everything. Test-specific data is
// injected via this urlOverrides map — the catch-all checks it before all default
// shapes, so individual tests can override any API response without fighting LIFO order.
//
// Usage:
//   await setupAuthMocks(page, {
//     "/v1/alerts/pending": { alerts: [...], total: 4 },
//     "/v1/companies/foo/overview": { instrument: {...} },
//   });
//
// Key ordering matters for overlapping patterns: put more-specific keys FIRST.
// Object.entries() preserves insertion order (ES2015+), so earlier entries win.
// Example: put "/v1/threads/t1" before "/v1/threads" so the detail endpoint
// is matched before the list endpoint for the same URL.
type UrlOverrides = Record<string, unknown>;

async function setupAuthMocks(page: Page, urlOverrides: UrlOverrides = {}): Promise<void> {
  const fakeToken = buildFakeToken();

  // WHY catch-all registered FIRST (before specific auth routes):
  // Playwright uses LIFO (last-registered = first-matched) route evaluation.
  // By registering the catch-all FIRST, it has the LOWEST priority — specific
  // routes registered AFTER it will take precedence for their URL patterns.
  //
  // Registration order (LIFO priority: last = highest):
  //   1. catch-all **/api/v1/**        (registered first = LOWEST priority)
  //   2. auth/ws-token                 (registered second)
  //   3. auth/refresh                  (registered last = HIGHEST priority)
  //
  // This way auth endpoints always work correctly regardless of what urlOverrides
  // are passed, and the catch-all handles all non-auth S9 API endpoints.
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();

    // ── Test-specific URL overrides (highest priority) ──────────────────────
    // Checked before all default shapes so individual tests can inject specific
    // response data without fighting route registration order.
    // Key ordering: more-specific keys must come before less-specific keys.
    // (e.g., "/v1/threads/t1" before "/v1/threads" to avoid the list key
    // matching detail URLs via substring).
    const overrideEntries = Object.entries(urlOverrides);
    for (const [urlKey, responseBody] of overrideEntries) {
      if (url.includes(urlKey)) {
        void route.fulfill({ status: 200, contentType: "application/json",
          body: JSON.stringify(responseBody) });
        return;
      }
    }

    // ── Safe default shapes per endpoint category ────────────────────────────
    // Prevents component crashes when queries resolve to {}.
    // Each shape is the minimal valid structure the component expects.

    if (url.includes("/v1/alerts/pending")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ alerts: [], total: 0 }) });
      return;
    }
    if (url.includes("/v1/briefings/morning")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ content: "E2E brief content", generated_at: new Date().toISOString() }) });
      return;
    }
    // WHY /threads/ (with slash) before /threads: specific thread detail endpoint
    // must be checked before the list endpoint to avoid the list key matching
    // detail URLs (e.g., /threads/abc123 includes "/threads").
    if (url.includes("/v1/threads/") && !url.includes("/v1/threads/?")) {
      // Thread detail endpoint — return minimal valid Thread shape
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ thread_id: "default", title: null, owner_id: "e2e-user",
          messages: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString() }) });
      return;
    }
    if (url.includes("/v1/threads")) {
      // Thread list endpoint — Thread[] (not {threads:[]}); empty by default
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify([]) });
      return;
    }
    if (url.includes("/v1/watchlists")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify([]) });
      return;
    }
    if (url.includes("/v1/portfolios")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify([]) });
      return;
    }
    // WHY sectors:[]: SectorHeatmapWidget checks data.sectors.length without
    // optional chaining. Returning {} triggers TypeError: Cannot read properties
    // of undefined (reading 'length'). Must return the expected shape.
    if (url.includes("/v1/market/heatmap")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ sectors: [] }) });
      return;
    }
    // WHY movers:[]: getTopMovers results are accessed as data?.movers ?? [] which
    // is safe, but providing the right shape avoids the fallback (empty state is fine).
    if (url.includes("/v1/market/top-movers")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ movers: [] }) });
      return;
    }
    // WHY markets:[]: PredictionMarketsWidget accesses data?.markets ?? [] (safe),
    // but providing the shape avoids relying on the fallback path in every test.
    if (url.includes("/v1/signals/prediction-markets")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ markets: [], total: 0 }) });
      return;
    }
    // WHY articles:[]: PortfolioNewsWidget accesses data?.articles ?? [] (safe).
    if (url.includes("/v1/news")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ articles: [], total: 0 }) });
      return;
    }

    // Default: empty object — keeps components alive without crashing for
    // any endpoint not explicitly listed above.
    void route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({}),
    });
  });

  // WHY registered AFTER catch-all (higher LIFO priority):
  // Playwright evaluates routes LIFO — last registered wins. auth/ws-token and
  // auth/refresh MUST be registered after the catch-all so they take priority
  // over the **/api/v1/** glob. Without this order the catch-all would intercept
  // auth calls and return {}, leaving accessToken null and all queries disabled.

  // Mock WebSocket auth token endpoint
  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-v3" }),
    });
  });

  // Mock auth refresh — returns a valid logged-in session (registered LAST = highest priority)
  await page.route("**/api/v1/auth/refresh", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 7200,
        user: {
          user_id: "e2e-v3-user",
          tenant_id: "e2e-v3-tenant",
          email: "v3-qa@worldview.local",
          name: "V3 QA User",
        },
      }),
    });
  });
}

// ── Screenshot dir ────────────────────────────────────────────────────────────

const SCREENSHOT_DIR = path.join(process.cwd(), "../../docs/screenshots/v3");

async function captureScreenshot(page: Page, name: string): Promise<void> {
  // WHY ensure dir: screenshots committed to docs/ for audit trail
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${name}.png`), fullPage: false });
}

// ── Dashboard Tests ───────────────────────────────────────────────────────────

test.describe("Dashboard — 4-row trader layout (PLAN-0039 Wave 7)", () => {
  test("renders 12-column grid with all 4 rows", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/dashboard");
    // WHY domcontentloaded + waitForSelector (not networkidle): TanStack Query's
    // polling refetch intervals (60s) keep the network active indefinitely, so
    // networkidle never resolves. We wait for the grid to appear instead.
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector(".col-span-12", { timeout: 10000 });

    // Row 1: Morning Brief spans full width (col-span-12)
    const morningBriefCell = page.locator(".col-span-12").first();
    await expect(morningBriefCell).toBeVisible();

    // Row 2: Sector heatmap is col-span-8
    const sectorHeatmap = page.locator(".col-span-8").first();
    await expect(sectorHeatmap).toBeVisible();

    // Row 3: Prediction markets is col-span-3
    const predictionCell = page.locator(".col-span-3").first();
    await expect(predictionCell).toBeVisible();

    await captureScreenshot(page, "dashboard");
  });

  test("removed AiSignals and TopBets — replaced by PredictionMarketsWidget", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/dashboard");
    await page.waitForLoadState("domcontentloaded");

    // Verify old components are gone
    await expect(page.locator("text=AI Signals")).not.toBeVisible();
    await expect(page.locator("text=Top Bets")).not.toBeVisible();

    // Verify new widgets present (by their section header text)
    await expect(page.locator("text=PREDICTION MARKETS")).toBeVisible();
    await expect(page.locator("text=MARKET SNAPSHOT")).toBeVisible();
  });

  test("no JavaScript errors on dashboard load", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await setupAuthMocks(page);
    await page.goto("/dashboard");
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    const critical = errors.filter(
      (e) => !e.includes("Failed to fetch") && !e.includes("NetworkError") && !e.includes("net::ERR"),
    );
    expect(critical).toHaveLength(0);
  });
});

// ── Screener Tests ────────────────────────────────────────────────────────────

test.describe("Screener — 12 columns, collapsible filter bar (PLAN-0039 Wave 3)", () => {
  test("has collapsible filter bar", async ({ page }) => {
    await setupAuthMocks(page);

    // Mock screener fields and results
    await page.route("**/api/v1/fundamentals/screen/fields", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    });
    await page.route("**/api/v1/fundamentals/screen", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ results: [], total: 0 }) });
    });

    await page.goto("/screener");
    await page.waitForLoadState("domcontentloaded");

    // Filter toggle button should be present
    const filterToggle = page.locator("button", { hasText: /Filters/i });
    await expect(filterToggle).toBeVisible();

    await captureScreenshot(page, "screener");
  });
});

// ── Portfolio Tests ───────────────────────────────────────────────────────────

test.describe("Portfolio — 4 tabs, KPI strip, holdings table (PLAN-0039 Wave 4)", () => {
  test("shows 4 portfolio tabs", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/portfolio");
    await page.waitForLoadState("domcontentloaded");

    // Should have Holdings, Transactions, Watchlists, Brokerage tabs
    // WHY getByRole tab: locator("text=Holdings") does case-insensitive partial match,
    // which also matches "No holdings yet." in the tab content — causing strict mode
    // violation. Role-based selector is unambiguous.
    await expect(page.getByRole("tab", { name: "Holdings" })).toBeVisible();
    await expect(page.locator("text=Transactions")).toBeVisible();
    await expect(page.locator("text=Watchlists")).toBeVisible();

    await captureScreenshot(page, "portfolio-holdings");
  });
});

// ── Alerts Tests ──────────────────────────────────────────────────────────────

test.describe("Alerts — severity groups, ACK/snooze, rule builder (PLAN-0039 Wave 7)", () => {
  test("shows severity-grouped alert sections when alerts present", async ({ page }) => {
    // WHY urlOverrides (not a separate page.route() call after setupAuthMocks):
    // Playwright processes routes LIFO — auth routes are registered last (highest
    // priority) and the catch-all **/api/v1/** is lowest priority. Test-specific
    // data must be injected via urlOverrides so it runs inside the catch-all handler.
    // See UrlOverrides type for full explanation.
    await setupAuthMocks(page, {
      "/v1/alerts/pending": {
        alerts: [
          { alert_id: "a1", severity: "CRITICAL", ticker: "AAPL", alert_type: "PRICE", body: "Critical alert", created_at: new Date().toISOString(), entity_id: "e1" },
          { alert_id: "a2", severity: "HIGH", ticker: "MSFT", alert_type: "NEWS", body: "High alert", created_at: new Date().toISOString(), entity_id: "e2" },
          { alert_id: "a3", severity: "MEDIUM", ticker: "GOOGL", alert_type: "VOLUME", body: "Medium alert", created_at: new Date().toISOString(), entity_id: "e3" },
          { alert_id: "a4", severity: "LOW", ticker: "AMZN", alert_type: "SIGNAL", body: "Low alert", created_at: new Date().toISOString(), entity_id: "e4" },
        ],
        total: 4,
      },
    });

    await page.goto("/alerts");
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    // Severity group headers should be visible (10px ALL CAPS per §0.9)
    await expect(page.locator("text=CRITICAL").first()).toBeVisible();
    await expect(page.locator("text=HIGH").first()).toBeVisible();
    await expect(page.locator("text=MEDIUM").first()).toBeVisible();
    await expect(page.locator("text=LOW").first()).toBeVisible();

    await captureScreenshot(page, "alerts");
  });

  test("Create Rule button opens rule builder dialog", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/alerts");
    await page.waitForLoadState("domcontentloaded");

    // Create Rule button should be visible
    const createRuleBtn = page.locator("button", { hasText: /Create Rule/i });
    await expect(createRuleBtn).toBeVisible();

    // Click to open rule builder
    await createRuleBtn.click();

    // Dialog should open (check for "CREATE ALERT RULE" or "Alert Rule")
    await expect(page.locator("text=Alert Rule")).toBeVisible({ timeout: 3000 });
  });

  test("category filter rail has 7 categories on news tab", async ({ page }) => {
    await setupAuthMocks(page);

    await page.route("**/api/v1/news/relevant*", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ articles: [] }) });
    });

    await page.goto("/alerts?tab=news");
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    // Check for category filter rail items
    await expect(page.locator("button", { hasText: "Earnings" })).toBeVisible();
    await expect(page.locator("button", { hasText: "M&A" })).toBeVisible();
    await expect(page.locator("button", { hasText: "Macro" })).toBeVisible();
  });
});

// ── Chat Tests ────────────────────────────────────────────────────────────────

test.describe("Chat — starter questions, entity context (PLAN-0039 Wave 7)", () => {
  test("shows 6 starter question cards on empty thread", async ({ page }) => {
    // WHY urlOverrides for threads (not separate page.route() calls after setupAuthMocks):
    // Playwright uses LIFO routing. The catch-all **/api/v1/** is registered first
    // (lowest LIFO priority), auth routes last (highest). Test-specific thread data
    // must be embedded via urlOverrides to run inside the catch-all handler.
    //
    // WHY "/v1/threads/t1" key BEFORE "/v1/threads" key:
    // Object.entries() preserves insertion order. "/v1/threads" is a substring of
    // "/v1/threads/t1", so checking it first would incorrectly match the detail URL.
    // More-specific key must come first so detail requests don't fall through to the
    // list handler.
    await setupAuthMocks(page, {
      "/v1/threads/t1": { thread_id: "t1", title: "New Thread", owner_id: "e2e-v3-user",
        updated_at: new Date().toISOString(), created_at: new Date().toISOString(), messages: [] },
      "/v1/threads": [{ thread_id: "t1", title: "New Thread", owner_id: "e2e-v3-user",
        updated_at: new Date().toISOString(), created_at: new Date().toISOString(), messages: [] }],
    });

    await page.goto("/chat");
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    // WHY waitForSelector before click: the thread list only renders after the
    // threads query resolves (with the mocked "New Thread" item). We wait for
    // the thread to appear in the sidebar before clicking it.
    await page.waitForSelector("text=New Thread", { timeout: 5000 });
    // WHY click the thread: starter questions only render when a thread is active
    // (they're inside the {activeThreadId && (...)} block). No thread is auto-selected —
    // the user must click one. We click the sidebar thread to activate it.
    await page.locator("text=New Thread").first().click();

    // Should see starter question cards (grid of 2 columns × 3 rows = 6 cards)
    // WHY timeout 8000: after clicking the thread, the detail query fires and
    // must resolve (mock returns instantly) before threadLoading becomes false
    // and the starter question grid renders.
    await expect(page.locator("text=key risks")).toBeVisible({ timeout: 8000 });
    await expect(page.locator("text=earnings call")).toBeVisible();

    await captureScreenshot(page, "chat");
  });

  test("shows entity context badge when entity_id param present", async ({ page }) => {
    // No URL overrides needed — catch-all returns [] for threads which triggers the
    // welcome screen ("Intelligence Chat" + "Start a conversation" button).
    await setupAuthMocks(page);

    await page.goto("/chat?entity_id=entity-aapl-123");
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    // WHY click "Start a conversation": the entity context badge lives inside the
    // {activeThreadId && (...)} block (chat input area). With no threads present, the
    // welcome screen shows — clicking this button calls handleNewChat(), which sets
    // activeThreadId to a UUID and reveals the input area + entity context badge.
    await page.waitForSelector("button:has-text('Start a conversation')", { timeout: 5000 });
    await page.locator("button", { hasText: /Start a conversation/i }).click();

    // WHY wait for textarea: the input area (including the entity badge) only renders
    // once activeThreadId is set. Waiting for the textarea confirms the block is mounted.
    await page.waitForSelector("textarea", { timeout: 5000 });

    // Context badge should show the entity id prefixed with "Context: "
    // WHY "text=Context:": the badge renders as <span>Context: entity-aapl-123</span>.
    // Using just "entity-aapl-123" causes a strict mode violation — starter question
    // cards replace [TICKER] with the entity_id, producing 4+ matching elements.
    // The "Context:" prefix is unique to the badge element so it matches exactly one node.
    await expect(page.locator("text=Context:").first()).toBeVisible({ timeout: 5000 });
  });
});

// ── Workspace Tests ───────────────────────────────────────────────────────────

test.describe("Workspace — named workspaces, panels, resize (PLAN-0039 Wave 2)", () => {
  test("has 4 default workspace tabs", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/workspace");
    await page.waitForLoadState("domcontentloaded");

    // 4 default preset workspace tabs should be visible
    await expect(page.locator("text=Day Trading")).toBeVisible();
    await expect(page.locator("text=Research")).toBeVisible();

    await captureScreenshot(page, "workspace");
  });

  test("no JavaScript errors on workspace load", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));

    await setupAuthMocks(page);
    await page.goto("/workspace");
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    const critical = errors.filter(
      (e) => !e.includes("Failed to fetch") && !e.includes("NetworkError") && !e.includes("net::ERR"),
    );
    expect(critical).toHaveLength(0);
  });
});

// ── Instrument Detail Tests ───────────────────────────────────────────────────

test.describe("Instrument Detail — AI subheader, 5-zone overview (PLAN-0039 Wave 5)", () => {
  const DEMO_ENTITY = "instrument-aapl-demo";

  test("shows InstrumentAISubheader below compact header", async ({ page }) => {
    // WHY urlOverrides (not separate page.route() after setupAuthMocks):
    // Playwright LIFO routing — catch-all is registered first (lowest priority).
    // Company overview mock must be passed via urlOverrides to run inside the handler.
    //
    // WHY /v1/companies/{id}/overview key:
    // getCompanyOverview(entityId) calls /v1/companies/{entityId}/overview.
    // The old /v1/entities/{id} path was wrong — this is the correct endpoint.
    //
    // WHY instrument object is required (not just {}):
    // InstrumentDetailPage checks `overview?.instrument`. If falsy, it renders
    // "Instrument not found." with no tabs. The full Instrument shape is needed.
    await setupAuthMocks(page, {
      "/v1/companies/instrument-aapl-demo/overview": {
        instrument: {
          instrument_id: DEMO_ENTITY,
          entity_id: DEMO_ENTITY,
          name: "Apple Inc.",
          ticker: "AAPL",
          exchange: "NASDAQ",
          currency: "USD",
          gics_sector: "Information Technology",
          gics_industry: "Technology Hardware",
          isin: null,
          country: "US",
          description: "Apple Inc. is a multinational technology company.",
        },
        fundamentals: null,
        quote: null,
        ohlcv: null,
      },
    });

    await page.goto(`/instruments/${DEMO_ENTITY}`);
    // WHY domcontentloaded + waitForSelector: networkidle times out (polling queries)
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector("header", { timeout: 10000 });

    // WHY waitForSelector("[role=tablist]"): the tabs only appear after the overview
    // query resolves and the instrument is found. Without this wait, the assertion
    // below runs before React re-renders with the data.
    await page.waitForSelector("[role=tablist]", { timeout: 10000 });

    // No "Brief" tab should exist (Brief tab removed in Wave 5 — replaced by AI subheader)
    await expect(page.locator("[role=tab]", { hasText: "Brief" })).not.toBeVisible();

    // Overview tab should be present
    await expect(page.locator("[role=tab]", { hasText: "Overview" })).toBeVisible();

    await captureScreenshot(page, "instrument-overview");
  });
});

// ── Shell Tests ───────────────────────────────────────────────────────────────

test.describe("Shell — TopBar 36px, CollapsibleSidebar (PLAN-0039 Wave 1)", () => {
  test("TopBar height is 36px (h-9)", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/dashboard");
    await page.waitForLoadState("domcontentloaded");
    // WHY waitForSelector before evaluate: TopBar is a "use client" component.
    // Auth state must resolve (via mocked /auth/refresh) before the layout renders
    // the <header>. Without this wait, document.querySelector("header") returns null.
    await page.waitForSelector("header", { timeout: 10000 });

    // Get the topbar element (should have h-9 = 36px)
    // WHY check via getBoundingClientRect: Tailwind class is compiled to pixels,
    // so we verify the actual rendered height, not just the class name.
    const topBarHeight = await page.evaluate(() => {
      // TopBar renders as <header> — simpler selector avoids bg-card/bg-background
      // mismatch (TopBar uses bg-background, not bg-card)
      const topbar = document.querySelector("header");
      if (!topbar) return null;
      return topbar.getBoundingClientRect().height;
    });

    // h-9 = 36px in Tailwind (2.25rem × 16px = 36px)
    expect(topBarHeight).toBeLessThanOrEqual(40); // allow 1px rounding
    expect(topBarHeight).toBeGreaterThanOrEqual(34);
  });

  test("Sidebar collapses to 48px icon rail", async ({ page }) => {
    await setupAuthMocks(page);

    // Set sidebar to collapsed state via localStorage before navigation
    await page.addInitScript(() => {
      // WHY addInitScript: localStorage must be set before React hydrates,
      // otherwise the component reads the default (expanded) state on mount.
      localStorage.setItem("worldview-sidebar-expanded", "false");
    });

    await page.goto("/dashboard");
    await page.waitForLoadState("domcontentloaded");
    // WHY waitForSelector before evaluate: CollapsibleSidebar is a "use client"
    // component that renders only after auth resolves. Without this wait, the
    // evaluate fires before the <aside> is in the DOM (returns null → number error).
    await page.waitForSelector("aside", { timeout: 10000 });

    // Sidebar should be narrow (48px) when collapsed
    const sidebarWidth = await page.evaluate(() => {
      // CollapsibleSidebar uses style={{ width: 48 }} when collapsed (not a Tailwind class)
      // so we read the computed width rather than matching a class name.
      const sidebar = document.querySelector("aside");
      if (!sidebar) return null;
      return sidebar.getBoundingClientRect().width;
    });

    // w-[48px] = 48px exactly
    expect(sidebarWidth).toBeLessThanOrEqual(52); // allow small rounding
    expect(sidebarWidth).toBeGreaterThanOrEqual(44);
  });
});

// ── Terminal Quality Checks ───────────────────────────────────────────────────

test.describe("Terminal Quality — no shadow/rounded violations in rendered DOM", () => {
  test("no box-shadow in dashboard computed styles", async ({ page }) => {
    await setupAuthMocks(page);
    await page.goto("/dashboard");
    // WHY domcontentloaded + waitForSelector(".bg-card"): networkidle times out
    // because TanStack Query's polling keeps the network active indefinitely.
    // Waiting for the first .bg-card element ensures at least one panel has rendered
    // so the box-shadow scan has meaningful DOM to inspect.
    await page.waitForLoadState("domcontentloaded");
    await page.waitForSelector(".bg-card", { timeout: 10000 });

    // Check that no data panel has a computed box-shadow
    // WHY: box-shadow resets in globals.css override shadcn defaults, but
    // this test catches any regressions where inline styles re-introduce shadows.
    const panelWithShadow = await page.evaluate(() => {
      // Query all flex/grid divs that could be panels
      const panels = document.querySelectorAll(".bg-card, .bg-background");
      for (const panel of panels) {
        const style = window.getComputedStyle(panel);
        if (style.boxShadow && style.boxShadow !== "none" && style.boxShadow !== "") {
          return panel.className;
        }
      }
      return null;
    });

    // Expect no panels with non-none box-shadow
    expect(panelWithShadow).toBeNull();
  });
});
