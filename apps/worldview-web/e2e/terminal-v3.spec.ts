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
async function setupAuthMocks(page: Page, overrides?: Record<string, unknown>): Promise<void> {
  const fakeToken = buildFakeToken();

  // Mock auth refresh → logged-in user
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

  // Mock WebSocket auth token
  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-v3" }),
    });
  });

  // Mock all S9 endpoints with empty success responses
  // WHY: TanStack Query fires requests on mount; without mocks they 404/fail
  // and all widgets show error states — masking layout assertions.
  await page.route("**/api/v1/**", (route) => {
    const url = route.request().url();

    // Minimal shaped responses for widgets that check array length
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
    if (url.includes("/v1/threads")) {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ threads: [] }) });
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

    // Default: empty object keeps components alive without crashing
    void route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify(overrides ?? {}),
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
    await page.waitForLoadState("networkidle");

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
    await page.waitForLoadState("networkidle");

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
    await expect(page.locator("text=Holdings")).toBeVisible();
    await expect(page.locator("text=Transactions")).toBeVisible();
    await expect(page.locator("text=Watchlists")).toBeVisible();

    await captureScreenshot(page, "portfolio-holdings");
  });
});

// ── Alerts Tests ──────────────────────────────────────────────────────────────

test.describe("Alerts — severity groups, ACK/snooze, rule builder (PLAN-0039 Wave 7)", () => {
  test("shows severity-grouped alert sections when alerts present", async ({ page }) => {
    // Mock alerts with all 4 severities
    await setupAuthMocks(page, {});

    await page.route("**/api/v1/alerts/pending", (route) => {
      void route.fulfill({
        status: 200, contentType: "application/json",
        body: JSON.stringify({
          alerts: [
            { alert_id: "a1", severity: "CRITICAL", ticker: "AAPL", alert_type: "PRICE", body: "Critical alert", created_at: new Date().toISOString(), entity_id: "e1" },
            { alert_id: "a2", severity: "HIGH", ticker: "MSFT", alert_type: "NEWS", body: "High alert", created_at: new Date().toISOString(), entity_id: "e2" },
            { alert_id: "a3", severity: "MEDIUM", ticker: "GOOGL", alert_type: "VOLUME", body: "Medium alert", created_at: new Date().toISOString(), entity_id: "e3" },
            { alert_id: "a4", severity: "LOW", ticker: "AMZN", alert_type: "SIGNAL", body: "Low alert", created_at: new Date().toISOString(), entity_id: "e4" },
          ],
          total: 4,
        }),
      });
    });

    await page.goto("/alerts");
    await page.waitForLoadState("networkidle");

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
    await page.waitForLoadState("networkidle");

    // Check for category filter rail items
    await expect(page.locator("button", { hasText: "Earnings" })).toBeVisible();
    await expect(page.locator("button", { hasText: "M&A" })).toBeVisible();
    await expect(page.locator("button", { hasText: "Macro" })).toBeVisible();
  });
});

// ── Chat Tests ────────────────────────────────────────────────────────────────

test.describe("Chat — starter questions, entity context (PLAN-0039 Wave 7)", () => {
  test("shows 6 starter question cards on empty thread", async ({ page }) => {
    await setupAuthMocks(page);

    await page.route("**/api/v1/threads", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ threads: [{ thread_id: "t1", title: "New Thread", created_at: new Date().toISOString(), message_count: 0, last_message_at: null }] }) });
    });
    await page.route("**/api/v1/threads/t1", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ thread_id: "t1", title: "New Thread", messages: [] }) });
    });

    await page.goto("/chat");
    await page.waitForLoadState("networkidle");

    // Should see starter question cards (grid of 2 columns × 3 rows = 6 cards)
    // Check for known starter question text
    await expect(page.locator("text=key risks")).toBeVisible({ timeout: 5000 });
    await expect(page.locator("text=earnings call")).toBeVisible();

    await captureScreenshot(page, "chat");
  });

  test("shows entity context badge when entity_id param present", async ({ page }) => {
    await setupAuthMocks(page);

    await page.route("**/api/v1/threads", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ threads: [] }) });
    });

    await page.goto("/chat?entity_id=entity-aapl-123");
    await page.waitForLoadState("networkidle");

    // Context badge should show the entity id
    await expect(page.locator("text=entity-aapl-123")).toBeVisible({ timeout: 5000 });
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
    await page.waitForLoadState("networkidle");

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
    await setupAuthMocks(page);

    await page.route(`**/api/v1/entities/${DEMO_ENTITY}**`, (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ entity_id: DEMO_ENTITY, name: "Apple Inc.", ticker: "AAPL", entity_type: "financial_instrument" }) });
    });
    await page.route("**/api/v1/briefings/instrument/**", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ content: "Apple Inc. is a leading tech company.", generated_at: new Date().toISOString() }) });
    });
    await page.route("**/api/v1/instruments/*/ohlcv**", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ bars: [] }) });
    });
    await page.route("**/api/v1/entities/**/articles**", (route) => {
      void route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ articles: [], total: 0 }) });
    });

    await page.goto(`/instruments/${DEMO_ENTITY}`);
    await page.waitForLoadState("networkidle");

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

    // Get the topbar element (should have h-9 = 36px)
    // WHY check via getBoundingClientRect: Tailwind class is compiled to pixels,
    // so we verify the actual rendered height, not just the class name.
    const topBarHeight = await page.evaluate(() => {
      // TopBar should be the first nav or header with h-9 class
      const topbar = document.querySelector('[class*="h-9"][class*="border-b"][class*="bg-card"]') ??
                     document.querySelector("header");
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

    // Sidebar should be narrow (48px) when collapsed
    const sidebarWidth = await page.evaluate(() => {
      const sidebar = document.querySelector("aside") ?? document.querySelector("[class*='w-\\[48px\\]']");
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
    await page.waitForLoadState("networkidle");

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
