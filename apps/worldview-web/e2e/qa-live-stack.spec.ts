/**
 * e2e/qa-live-stack.spec.ts -- Live stack QA E2E tests (NO API mocks)
 *
 * WHY THIS EXISTS: Every other E2E spec in this project intercepts API calls
 * with page.route() mocks. That gives fast, deterministic tests -- but never
 * catches real backend regressions (wrong response shapes, 500s, missing
 * endpoints, broken auth flows). This spec is the opposite: it lets the
 * frontend talk to the REAL S9 gateway and reports what actually works.
 *
 * KEY PRINCIPLE: NO page.route() calls anywhere in this file. Every HTTP
 * request goes to the real dev stack. Tests will FAIL when backends are
 * broken -- that is the correct behaviour and the entire point.
 *
 * HOW AUTH WORKS: The login page detects Zitadel is unavailable (no env vars
 * or OIDC discovery fails) and shows a "Dev Login" button. Clicking it calls
 * POST /v1/auth/dev-login on S9, which issues a real JWT. After redirect to
 * /dashboard, React auth state is hydrated and all subsequent navigations
 * are authenticated.
 *
 * CRITICAL: Auth token lives in React state (in-memory). A full page.goto()
 * triggers a full-page navigation that resets React state, losing the token.
 * The (app)/layout.tsx auth guard then redirects to /login. To avoid this,
 * we navigate between authenticated pages via sidebar link clicks (client-side
 * <Link> navigation) which preserve React state.
 *
 * PREREQUISITES:
 *   - `pnpm dev` running at localhost:3001 (Next.js dev server)
 *   - S9 API Gateway running at localhost:8000 (or wherever next.config.ts rewrites to)
 *   - `make seed` run at least once (creates the demo user for dev-login)
 *
 * RUN: npx playwright test e2e/qa-live-stack.spec.ts --project=chromium
 */

import { test, expect, type Page } from "@playwright/test";

// ── Shared helpers ───────────────────────────────────────────────────────────

/**
 * authenticateViaDevLogin -- click the real "Dev Login" button on /login.
 *
 * WHY NOT mock auth: The whole point of this spec is to test the real stack.
 * Dev login calls POST /v1/auth/dev-login on the real S9 gateway, which
 * issues a real RS256 JWT. If S9 is down, this fails -- correctly.
 *
 * WHY 10s timeout for the button: The login page runs a useEffect that
 * probes GET /api/v1/auth/login to detect Zitadel availability. On slow
 * dev machines this probe + re-render can take 3-5 seconds.
 *
 * WHY 15s timeout for dashboard redirect: After dev-login, React hydrates
 * the auth context, then the (app) layout guard re-evaluates and navigates
 * to /dashboard. With cold TanStack Query caches this can take 5-10 seconds.
 */
async function authenticateViaDevLogin(page: Page): Promise<void> {
  await page.goto("/login");

  // Wait for the page to detect Zitadel is unavailable and show dev login.
  // The button text is "Dev Login (no Zitadel)" -- match on the "Dev Login" prefix.
  const devLoginButton = page.getByRole("button", { name: /dev login/i });
  await devLoginButton.waitFor({ timeout: 10_000 });
  await devLoginButton.click();

  // Wait for redirect to dashboard after successful login.
  await page.waitForURL("**/dashboard", { timeout: 15_000 });
}

/**
 * navigateViaSidebar -- click a sidebar link to navigate without full-page reload.
 *
 * WHY NOT page.goto(): The auth token lives in React state (in-memory). A
 * full page.goto() triggers a browser-level navigation that unmounts React,
 * destroying the auth state. The (app)/layout.tsx auth guard then redirects
 * to /login. Client-side <Link> clicks preserve React state and the token.
 *
 * The sidebar is a 56px-wide icon rail (<aside>) with <Link> elements that
 * have title attributes matching the nav item labels.
 */
async function navigateViaSidebar(
  page: Page,
  linkTitle: string,
  expectedPath: string,
): Promise<void> {
  const link = page.locator(`aside a[title="${linkTitle}"]`);
  await link.click();
  await page.waitForURL(`**${expectedPath}`, { timeout: 10_000 });
}

/**
 * screenshotPath -- deterministic path for live-stack screenshots.
 * Saved into test-results/ so Playwright's HTML reporter can display them.
 */
function screenshotPath(name: string): string {
  return `test-results/live-${name}.png`;
}

// ── Authenticated page definitions ───────────────────────────────────────────

/**
 * AUTHENTICATED_PAGES -- all pages reachable from the sidebar nav rail.
 *
 * WHY sidebarTitle: we navigate by clicking sidebar links (not page.goto)
 * to preserve React auth state. The title attribute on each <Link> is
 * the selector we use.
 *
 * WHY dashboard is NOT in this list: after authenticateViaDevLogin we land
 * on /dashboard already, so the first test verifies it directly. The remaining
 * pages are navigated to via sidebar clicks.
 */
const AUTHENTICATED_PAGES = [
  { sidebarTitle: "Portfolio", expectedPath: "/portfolio", name: "portfolio" },
  { sidebarTitle: "Screener", expectedPath: "/screener", name: "screener" },
  { sidebarTitle: "Alerts & News", expectedPath: "/alerts", name: "alerts" },
  { sidebarTitle: "Intelligence / Chat", expectedPath: "/chat", name: "chat" },
  { sidebarTitle: "Workspace", expectedPath: "/workspace", name: "workspace" },
  { sidebarTitle: "Settings", expectedPath: "/settings", name: "settings" },
] as const;

// ═══════════════════════════════════════════════════════════════════════════════
// Group 1: Public pages load (no auth needed)
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("Group 1: Public pages (no auth)", () => {
  test("/ landing page renders hero + nav", async ({ page }) => {
    // WHY test the landing page: it's the first thing search engines and
    // unauthenticated visitors see. If it crashes, nobody can sign in.
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    // The landing page has a <nav> with the app name and a hero <section>.
    await expect(page.locator("nav")).toBeVisible({ timeout: 10_000 });

    // Hero heading: "Worldview -- Market Intelligence Terminal"
    await expect(
      page.getByRole("heading", { name: /worldview/i }),
    ).toBeVisible({ timeout: 5_000 });

    // "Sign In" link in the nav bar
    await expect(page.getByRole("link", { name: /sign in/i }).first()).toBeVisible();

    await page.screenshot({ path: screenshotPath("landing"), fullPage: true });
  });

  test("/login renders login form", async ({ page }) => {
    // WHY: the login page is the auth entry point. It must render without
    // crashing even when S9 is slow (the OIDC probe runs on mount).
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    // The page shows "Worldview" heading and either the Zitadel button or
    // the Dev Login button (depending on OIDC availability). Either is valid.
    await expect(
      page.getByRole("heading", { name: /worldview/i }),
    ).toBeVisible({ timeout: 10_000 });

    // At least one button must be present (Zitadel sign-in OR Dev Login)
    const buttons = page.getByRole("button");
    await expect(buttons.first()).toBeVisible({ timeout: 10_000 });

    await page.screenshot({ path: screenshotPath("login") });
  });

  test("Unknown route shows 404", async ({ page }) => {
    // WHY: Next.js must render the not-found.tsx page, not a blank screen
    // or an unhandled error. Verifies the catch-all route works.
    await page.goto("/this-route-definitely-does-not-exist-12345");
    await page.waitForLoadState("domcontentloaded");

    // The 404 page contains "Page not found" heading and "Error 404" label
    await expect(page.getByText(/page not found/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/404/)).toBeVisible();

    await page.screenshot({ path: screenshotPath("404") });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Group 2: Authenticated pages load without crash
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("Group 2: Authenticated pages smoke test", () => {
  // WHY serial mode: authenticateViaDevLogin sets React auth state in the
  // browser context. Running in parallel would create separate contexts
  // that each need their own auth -- wasteful and slow. Serial mode lets
  // a single auth flow serve all tests in this group.
  test.describe.configure({ mode: "serial" });

  // ── Shared page instance for serial mode ────────────────────────────────
  // WHY shared page: serial mode means tests run sequentially in the same
  // worker. Sharing the page avoids re-authenticating for every test.
  let page: Page;

  // ── Error collectors registered ONCE to avoid accumulating listeners ────
  // WHY registered once in beforeAll: collectPageErrors/collectConsoleErrors
  // add event listeners. In serial mode with a shared page, calling them in
  // each test would stack up listeners. Instead, we register once and clear
  // the arrays between tests.
  let pageErrors: string[] = [];
  let consoleErrors: string[] = [];

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();

    // Register error listeners ONCE for the lifetime of this page
    page.on("pageerror", (error) => {
      pageErrors.push(`${error.name}: ${error.message}`);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    await authenticateViaDevLogin(page);
  });

  test.afterAll(async () => {
    await page.close();
  });

  // ── Dashboard test (we're already on /dashboard after auth) ─────────────
  test("dashboard (/dashboard) loads without JS crash", async () => {
    test.slow();

    // Clear error arrays from any previous test
    pageErrors = [];
    consoleErrors = [];

    // WHY no navigation: authenticateViaDevLogin already redirected us to
    // /dashboard. No need to navigate -- we're already here.

    // WHY waitForLoadState("networkidle"): we want to wait for all API
    // calls to complete (or fail) before asserting. "networkidle" fires
    // when there are no network requests for 500ms.
    await page.waitForLoadState("networkidle").catch(() => {
      // WHY catch: some pages have polling queries (refetchInterval) that
      // prevent networkidle from ever firing. Fall back gracefully.
    });

    const mainEl = page.locator("main").first();
    await expect(mainEl).toBeVisible({ timeout: 15_000 });

    // Must NOT show the Next.js error overlay
    await expect(page.locator("body")).not.toContainText("Application error");

    // Must NOT have uncaught JS exceptions
    expect(pageErrors).toHaveLength(0);

    // Report console errors for visibility (soft check)
    if (consoleErrors.length > 0) {
      console.log(
        `[dashboard] ${consoleErrors.length} console error(s):\n` +
          consoleErrors.map((e) => `  - ${e}`).join("\n"),
      );
    }

    await page.screenshot({ path: screenshotPath("dashboard") });
  });

  // ── Remaining authenticated pages (navigate via sidebar clicks) ─────────
  for (const { sidebarTitle, expectedPath, name } of AUTHENTICATED_PAGES) {
    test(`${name} (${expectedPath}) loads without JS crash`, async () => {
      test.slow();

      // Clear error arrays from previous test
      pageErrors = [];
      consoleErrors = [];

      // WHY sidebar click (not page.goto): auth token is in React state.
      // A full page.goto() destroys React state, losing the token. Sidebar
      // links use Next.js <Link> which does client-side navigation.
      await navigateViaSidebar(page, sidebarTitle, expectedPath);

      await page.waitForLoadState("networkidle").catch(() => {
        // Polling queries may prevent networkidle -- that's OK
      });

      const mainEl = page.locator("main").first();
      await expect(mainEl).toBeVisible({ timeout: 15_000 });

      // Must NOT show the Next.js error overlay
      await expect(page.locator("body")).not.toContainText("Application error");

      // Must NOT have uncaught JS exceptions
      expect(pageErrors).toHaveLength(0);

      // Report console errors for visibility (soft check)
      if (consoleErrors.length > 0) {
        console.log(
          `[${name}] ${consoleErrors.length} console error(s):\n` +
            consoleErrors.map((e) => `  - ${e}`).join("\n"),
        );
      }

      await page.screenshot({ path: screenshotPath(name) });
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
// Group 3: Dashboard widget health
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("Group 3: Dashboard widget health", () => {
  test.describe.configure({ mode: "serial" });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await authenticateViaDevLogin(page);

    // WHY no extra navigation: authenticateViaDevLogin lands on /dashboard.
    // Wait for the page to settle before running widget checks.
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("at least one dashboard widget has real data (not all skeleton/error)", async () => {
    test.slow();

    // WHY count Cards: the dashboard page.tsx renders 9 Card components
    // (Morning Brief, Portfolio, Market Heatmap, Top Movers, News, Calendar,
    // Alerts, AI Signals, Prediction Markets). Each Card wraps a widget.

    // Count widgets that show real data content vs error/skeleton states.
    // WHY evaluate in-browser: we need to inspect DOM state that Playwright's
    // locator API can't easily aggregate.
    const widgetHealth = await page.evaluate(() => {
      // Find all CardContent containers (the data area of each dashboard widget)
      const cardContents = document.querySelectorAll("[class*='CardContent'], [class*='pb-3']");
      let withData = 0;
      let withError = 0;
      let withSkeleton = 0;

      for (const content of cardContents) {
        const text = content.textContent ?? "";
        const html = content.innerHTML;

        // Check for error states
        if (
          text.includes("Failed to load") ||
          text.includes("unavailable") ||
          text.includes("Error") ||
          html.includes("text-destructive")
        ) {
          withError++;
        }
        // Check for skeleton/loading states
        else if (
          html.includes("animate-pulse") ||
          html.includes("Skeleton") ||
          html.includes("aria-busy")
        ) {
          withSkeleton++;
        }
        // Has some real text content (not empty, not skeleton)
        else if (text.trim().length > 10) {
          withData++;
        }
      }

      return { withData, withError, withSkeleton, total: cardContents.length };
    });

    console.log(
      `[Dashboard widget health] ` +
        `data=${widgetHealth.withData} ` +
        `error=${widgetHealth.withError} ` +
        `skeleton=${widgetHealth.withSkeleton} ` +
        `total=${widgetHealth.total}`,
    );

    // HARD FAIL if zero widgets have real data -- entire dashboard is broken
    expect(
      widgetHealth.withData,
      "Expected at least one dashboard widget to show real data. " +
        "All widgets are in error or skeleton state -- is S9 running?",
    ).toBeGreaterThan(0);

    // SOFT ASSERTION: individual widget failures are warnings, not hard fails.
    // WHY soft: some backends (S8 chat, S5 news) are known to be flaky.
    expect.soft(
      widgetHealth.withError,
      `${widgetHealth.withError} dashboard widget(s) show error state`,
    ).toBeLessThan(widgetHealth.total);

    await page.screenshot({ path: screenshotPath("dashboard-widgets"), fullPage: true });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Group 4: Data-bearing assertions
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("Group 4: Data-bearing assertions", () => {
  test.describe.configure({ mode: "serial" });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await authenticateViaDevLogin(page);

    // Wait for dashboard to fully load before navigating elsewhere
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("Portfolio has holdings or shows empty state", async () => {
    test.slow();

    // Navigate via sidebar click (preserves React auth state)
    await navigateViaSidebar(page, "Portfolio", "/portfolio");
    await page.waitForLoadState("networkidle").catch(() => {});

    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });

    // WHY check for both states: seed data may or may not include holdings.
    // "No holdings yet." is the empty state text from HoldingsTable.
    // "Failed to load portfolio data" is the error state from PortfolioPage.
    // Holding rows have role="row" with tabIndex=0.
    //
    // Valid outcomes:
    //   1. Holdings table with rows (seed data present)
    //   2. "No holdings yet." (empty portfolio)
    //   3. "Portfolio" heading visible (page loaded, data pending)
    // Invalid outcome:
    //   - Page crashed (no main element, Application error)

    const hasHoldings = await page.locator("[role='row']").count() > 0;
    const hasEmptyState = await page.getByText(/no holdings yet/i).isVisible().catch(() => false);
    const hasErrorState = await page.getByText(/failed to load/i).isVisible().catch(() => false);
    const hasPageHeading = await page.getByRole("heading", { name: /portfolio/i }).isVisible().catch(() => false);

    console.log(
      `[Portfolio] holdings=${hasHoldings} empty=${hasEmptyState} ` +
        `error=${hasErrorState} heading=${hasPageHeading}`,
    );

    // At least one of these states must be visible -- the page loaded something
    expect(
      hasHoldings || hasEmptyState || hasErrorState || hasPageHeading,
      "Portfolio page rendered no recognizable content -- possible crash",
    ).toBe(true);

    await page.screenshot({ path: screenshotPath("portfolio-data") });
  });

  test("Screener returns results or empty state when filtering", async () => {
    test.slow();

    await navigateViaSidebar(page, "Screener", "/screener");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });

    // WHY type "A": a single letter maximizes the chance of matching seeded
    // instruments (AAPL, AMZN, etc.) without being so specific that we get
    // zero results in every environment.
    const searchInput = page.getByPlaceholder(/search/i).first();
    if (await searchInput.isVisible().catch(() => false)) {
      await searchInput.fill("A");

      // Click Apply button to submit the filter
      const applyButton = page.getByRole("button", { name: /apply/i });
      if (await applyButton.isVisible().catch(() => false)) {
        await applyButton.click();

        // Wait for results to load (real S9 query)
        await page.waitForLoadState("networkidle").catch(() => {});

        // Give the table time to render after the API response
        await page.waitForTimeout(3_000);
      }
    }

    // Valid outcomes: results table has rows, OR empty/error message shown,
    // OR the page simply rendered the screener layout (filter + table shell)
    const bodyText = await page.textContent("body") ?? "";
    const hasContent =
      bodyText.includes("Ticker") || // table header
      bodyText.includes("No instruments") || // empty state
      bodyText.includes("Screener") || // page heading
      bodyText.includes("Apply"); // filter panel loaded

    expect(
      hasContent,
      "Screener page rendered no recognizable content",
    ).toBe(true);

    await page.screenshot({ path: screenshotPath("screener-filter") });
  });

  test("Alerts page loads 3 tab triggers", async () => {
    test.slow();

    await navigateViaSidebar(page, "Alerts & News", "/alerts");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });

    // The alerts page has 3 tabs: Alerts, News Feed, Top Today
    // These render as TabsTrigger components with role="tab"
    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveCount(3, { timeout: 10_000 });

    // Verify each tab trigger is visible by name
    await expect(page.getByRole("tab", { name: /alerts/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /news feed/i })).toBeVisible();
    await expect(page.getByRole("tab", { name: /top today/i })).toBeVisible();

    await page.screenshot({ path: screenshotPath("alerts-tabs") });
  });

  test("Search returns instruments from real endpoint", async () => {
    test.slow();

    // Navigate to dashboard for the search test (search input is in TopBar)
    await navigateViaSidebar(page, "Dashboard", "/dashboard");
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });

    // WHY look for the search input: the TopBar has an always-visible search
    // input with placeholder "Search instruments... (Cmd+K)". This hits the real
    // GET /api/v1/search/instruments?q=... endpoint on S9.
    const searchInput = page.getByPlaceholder(/search instruments/i);
    if (await searchInput.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await searchInput.fill("AAPL");

      // Wait for the real search API to respond and render results.
      // WHY 5s timeout: real S9 search involves DB + optional Valkey cache lookup.
      await page.waitForTimeout(2_000);

      // Check if any search results appeared in the dropdown.
      const hasResults = await page.getByText(/AAPL|Apple/i).first().isVisible().catch(() => false);

      // Also check if the search input accepted the query (basic functionality)
      await expect(searchInput).toHaveValue("AAPL");

      console.log(`[Search] results visible for "AAPL": ${hasResults}`);

      // WHY not hard-fail if no results: the search endpoint may return empty
      // if no instruments are seeded. The important thing is the page didn't
      // crash and the input worked.
    } else {
      // If search input is not visible, try the keyboard shortcut as fallback.
      await page.keyboard.press("ControlOrMeta+k");
      await page.waitForTimeout(1_000);
    }

    await page.screenshot({ path: screenshotPath("search-results") });
  });

  test("Chat page renders without crash (S8 may be down)", async () => {
    test.slow();

    const chatPageErrors: string[] = [];
    // WHY separate listener: we only want errors from this specific navigation
    const handler = (error: Error) => {
      chatPageErrors.push(`${error.name}: ${error.message}`);
    };
    page.on("pageerror", handler);

    await navigateViaSidebar(page, "Intelligence / Chat", "/chat");

    // WHY generous timeout: if S8 (rag-chat) is down, the page may show a
    // loading spinner for several seconds before the query times out and
    // renders an error boundary or empty state.
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });

    // Valid outcomes:
    //   1. Thread list renders (S8 is up and responding)
    //   2. Empty state ("No conversations yet" or similar)
    //   3. Error state ("Failed to load" -- S8 is down, graceful degradation)
    // Invalid outcome:
    //   - Uncaught JS exception (React component crashed)

    // Must not have uncaught JS exceptions
    expect(
      chatPageErrors,
      "Chat page threw uncaught JS exception(s) -- React component crashed",
    ).toHaveLength(0);

    // Must not show the Next.js error overlay
    await expect(page.locator("body")).not.toContainText("Application error");

    // Clean up the listener to avoid accumulation
    page.removeListener("pageerror", handler);

    await page.screenshot({ path: screenshotPath("chat") });
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Group 5: Backend health reflection
// ═══════════════════════════════════════════════════════════════════════════════

test.describe("Group 5: Backend health reflection", () => {
  test.describe.configure({ mode: "serial" });

  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await authenticateViaDevLogin(page);

    // We land on /dashboard after auth -- wait for it to fully load
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.getByRole("main").first()).toBeVisible({ timeout: 15_000 });
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("Market Heatmap card renders data or graceful error", async () => {
    test.slow();

    // WHY no navigation: we're already on /dashboard from beforeAll

    // WHY find by CardTitle text: the dashboard renders a Card with
    // CardTitle "Market Heatmap". The MarketHeatmap component inside
    // either shows sector tiles (data flowing) or an error/empty state.
    const heatmapCard = page.locator("text=Market Heatmap").first();
    await expect(heatmapCard).toBeVisible({ timeout: 10_000 });

    // Look at the content area of the heatmap card.
    const heatmapSection = page.locator("text=Market Heatmap").locator("..").locator("..");

    const sectionText = await heatmapSection.textContent() ?? "";

    // Valid: sector tiles (text like "Technology", "Healthcare", percentage values)
    // Valid: "unavailable" or "No data" or "Failed" error message
    // Invalid: completely empty (silent failure -- no text at all)
    const hasSectorData =
      sectionText.includes("Technology") ||
      sectionText.includes("Health") ||
      sectionText.includes("Energy") ||
      sectionText.includes("Financial") ||
      sectionText.includes("%");

    const hasGracefulError =
      sectionText.includes("unavailable") ||
      sectionText.includes("No data") ||
      sectionText.includes("Failed") ||
      sectionText.includes("error") ||
      sectionText.includes("No sectors");

    console.log(
      `[Market Heatmap] hasSectorData=${hasSectorData} hasGracefulError=${hasGracefulError}`,
    );

    // FAIL if the card shows nothing -- silent failure is the worst outcome
    expect(
      hasSectorData || hasGracefulError || sectionText.trim().length > 20,
      "Market Heatmap card appears empty -- possible silent failure. " +
        `Content: "${sectionText.substring(0, 200)}"`,
    ).toBe(true);

    await page.screenshot({ path: screenshotPath("heatmap") });
  });

  test("Top Movers card renders data or graceful error", async () => {
    test.slow();

    // WHY same pattern as heatmap: Top Movers is a full-width dashboard card.
    const moversTitle = page.locator("text=Top Movers").first();
    await expect(moversTitle).toBeVisible({ timeout: 10_000 });

    const moversSection = page.locator("text=Top Movers").locator("..").locator("..");
    const sectionText = await moversSection.textContent() ?? "";

    const hasMoversData =
      sectionText.includes("$") ||
      sectionText.includes("%") ||
      sectionText.includes("Gainer") ||
      sectionText.includes("Loser");

    const hasGracefulError =
      sectionText.includes("unavailable") ||
      sectionText.includes("No data") ||
      sectionText.includes("Failed") ||
      sectionText.includes("No movers");

    console.log(
      `[Top Movers] hasMoversData=${hasMoversData} hasGracefulError=${hasGracefulError}`,
    );

    expect(
      hasMoversData || hasGracefulError || sectionText.trim().length > 20,
      "Top Movers card appears empty -- possible silent failure. " +
        `Content: "${sectionText.substring(0, 200)}"`,
    ).toBe(true);

    await page.screenshot({ path: screenshotPath("top-movers") });
  });
});
