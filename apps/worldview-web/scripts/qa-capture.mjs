/**
 * scripts/qa-capture.mjs — Deep functional QA capture for the deployed frontend.
 *
 * Authenticates via the Dev Login button (real S9 backend, no mocks), then
 * screenshots every key route + the enhanced screener states. Collects console
 * errors/warnings and failed (4xx/5xx) network requests per page.
 *
 * Usage: node scripts/qa-capture.mjs
 */
import { chromium, request as pwRequest } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FRONTEND = "http://localhost:3001";

// dev-login returns a JWT in the body but sets NO refresh cookie, so AuthContext
// loses the session on every full page reload (it then POSTs /auth/refresh which
// 401s). To keep a stable authenticated session across page.goto() reloads we
// intercept /api/v1/auth/refresh and fulfill it with a fresh dev-login token.
async function freshAuth() {
  const api = await pwRequest.newContext();
  const resp = await api.post(`${FRONTEND}/api/v1/auth/dev-login`, { data: {} });
  const json = await resp.json();
  await api.dispose();
  return json; // { access_token, expires_in, user }
}

async function installAuthRefresh(context) {
  await context.route("**/api/v1/auth/refresh", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    const auth = await freshAuth();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: auth.access_token,
        expires_in: auth.expires_in,
        user: auth.user,
      }),
    });
  });
}
const OUT = "/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability/docs/audits/2026-06-16-frontend-qa/screenshots";
fs.mkdirSync(OUT, { recursive: true });

const report = []; // { page, viewport, consoleErrors[], consoleWarnings[], failedRequests[], notes[] }

function attachListeners(page, bucket) {
  page.on("console", (msg) => {
    const t = msg.type();
    const text = msg.text();
    if (t === "error") bucket.consoleErrors.push(text);
    else if (t === "warning") bucket.consoleWarnings.push(text);
  });
  page.on("pageerror", (err) => bucket.consoleErrors.push("PAGEERROR: " + err.message));
  page.on("response", (resp) => {
    const s = resp.status();
    if (s >= 400) {
      bucket.failedRequests.push(`${s} ${resp.request().method()} ${resp.url()}`);
    }
  });
}

function newBucket(name, viewport) {
  const b = { page: name, viewport, consoleErrors: [], consoleWarnings: [], failedRequests: [], notes: [] };
  report.push(b);
  return b;
}

async function shot(page, name) {
  const file = path.join(OUT, name + ".png");
  await page.screenshot({ path: file, fullPage: true });
  return name + ".png";
}

async function settle(page, ms = 2500) {
  try { await page.waitForLoadState("networkidle", { timeout: ms }); } catch { /* ignore */ }
  await page.waitForTimeout(800);
}

// ── Dev login: drives the real Login page button so the httpOnly refresh
//    cookie is set on the browser context. Returns true on success.
async function devLogin(page, bucket) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000); // login page probes the gateway before showing the button
  const btn = page.getByRole("button", { name: /dev login/i });
  if ((await btn.count()) === 0) {
    bucket.notes.push("Dev Login button NOT found on /login");
    await shot(page, "00-login-no-devbutton");
    return false;
  }
  await shot(page, "00-login-page");
  await btn.first().click();
  // handleDevLogin calls setTokens then router.replace(redirectTo)
  try {
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 10000 });
  } catch {
    bucket.notes.push("Did not navigate away from /login after Dev Login click");
  }
  await settle(page);
  bucket.notes.push("post-login URL: " + page.url());
  return !page.url().includes("/login");
}

async function runViewport(browser, vp, label) {
  const context = await browser.newContext({ viewport: vp });
  await installAuthRefresh(context); // keep session alive across reloads
  const page = await context.newPage();

  const loginBucket = newBucket("login/dev-login", label);
  attachListeners(page, loginBucket);
  const ok = await devLogin(page, loginBucket);
  if (!ok) {
    loginBucket.notes.push("AUTH note — relying on intercepted /auth/refresh for session");
  }

  // Generic route visits
  const routes = [
    ["dashboard", "/dashboard"],
    ["portfolio", "/portfolio"],
    ["chat", "/chat"],
    ["watchlists", "/watchlists"],
    ["alerts", "/alerts"],
    ["news", "/news"],
    ["search", "/search"],
    ["prediction-markets", "/prediction-markets"],
    ["indices", "/indices"],
  ];

  for (const [name, route] of routes) {
    const b = newBucket(name, label);
    attachListeners(page, b);
    try {
      await page.goto(`${FRONTEND}${route}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await settle(page);
      b.notes.push("final URL: " + page.url());
      b.shot = await shot(page, `${label}-${name}`);
    } catch (e) {
      b.notes.push("NAV ERROR: " + e.message);
    }
  }

  // ── Instrument detail page + tabs ──────────────────────────────────────
  // Tabs are internal useState (NOT URL-driven), so we navigate once then
  // click each Radix TabsTrigger (role="tab").
  await page.goto(`${FRONTEND}/instruments/AAPL`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 5000);
  for (const tab of ["quote", "financials", "intelligence"]) {
    const b = newBucket(`instrument-AAPL-${tab}`, label);
    attachListeners(page, b);
    try {
      // InstrumentTabs render role="button" + aria-current (NOT role="tab").
      const tabBtn = page.getByRole("button", { name: new RegExp(`^${tab}$`, "i") });
      if ((await tabBtn.count()) > 0) {
        await tabBtn.first().click({ timeout: 4000 });
        await settle(page, 4000);
        b.notes.push(`tab clicked: ${tab}, current=${await tabBtn.first().getAttribute("aria-current")}`);
      } else {
        b.notes.push(`tab button NOT found: ${tab}`);
      }
      b.shot = await shot(page, `${label}-instrument-AAPL-${tab}`);
    } catch (e) {
      b.notes.push("TAB ERROR: " + e.message);
    }
  }

  // ── SCREENER deep dive ─────────────────────────────────────────────────
  await screenerDeepDive(page, label);

  await context.close();
}

async function screenerDeepDive(page, label) {
  // 1. default view
  let b = newBucket("screener-default", label);
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 5000);
  b.notes.push("final URL: " + page.url());
  // Count visible rows (AG grid)
  const rowCount = async () => {
    try { return await page.locator(".ag-center-cols-container .ag-row").count(); } catch { return -1; }
  };
  b.notes.push("ag rows (default): " + (await rowCount()));
  b.shot = await shot(page, `${label}-screener-01-default`);

  // 2. Column Settings popover OPEN + toggle L3/L4/L5 columns
  b = newBucket("screener-column-settings", label);
  attachListeners(page, b);
  const gear = page.getByRole("button", { name: /configure columns/i });
  if ((await gear.count()) > 0) {
    await gear.first().click();
    await page.waitForTimeout(800);
    await shot(page, `${label}-screener-02a-columns-popover-open`);
    // Toggle several IB-L3 (returns) / IB-L4 (analyst+ownership) / IB-L5 (intel)
    // columns ON. Each is a Radix Checkbox with aria-label "Toggle <Label> column
    // visibility". These columns were previously unreachable.
    const wantedLabels = ["1M RTN", "3M RTN", "Analyst Tgt", "Analyst Upside", "Inst Own%", "Brief Score"];
    let toggled = 0;
    for (const lbl of wantedLabels) {
      const cb = page.getByRole("checkbox", { name: `Toggle ${lbl} column visibility` });
      try {
        if ((await cb.count()) > 0) {
          const checked = await cb.first().getAttribute("aria-checked");
          if (checked !== "true") { await cb.first().click({ timeout: 1500 }); toggled++; await page.waitForTimeout(150); }
        } else {
          b.notes.push(`column checkbox NOT found: ${lbl}`);
        }
      } catch (e) { b.notes.push(`toggle err ${lbl}: ${e.message}`); }
    }
    b.notes.push("column toggles turned ON: " + toggled);
    await shot(page, `${label}-screener-02b-columns-toggled`);
    // Close popover (Escape) and screenshot grid with new columns
    await page.keyboard.press("Escape");
    await settle(page, 2500);
    b.notes.push("ag rows (after columns): " + (await rowCount()));
    b.shot = await shot(page, `${label}-screener-02c-grid-with-new-columns`);
  } else {
    b.notes.push("Configure columns gear NOT found");
  }

  // 3. Intelligence filter group / filter bar OPEN — must click the FILTERS
  //    toggle in the header to slide the ScreenerFilterBar (incl.
  //    IntelligenceFilterGroup) open.
  b = newBucket("screener-intelligence-filters", label);
  attachListeners(page, b);
  // Reload to a clean state and open the filter panel.
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 4000);
  const filtersToggle = page.getByRole("button", { name: /toggle screener filters/i }).first();
  if ((await filtersToggle.count()) > 0) {
    await filtersToggle.click();
    await page.waitForTimeout(1200);
    b.notes.push("clicked FILTERS toggle");
  } else {
    b.notes.push("FILTERS toggle NOT found");
  }
  // Scroll the intelligence section into view if present.
  try {
    const intelText = page.getByText(/News 7d|AI Brief|Contradiction|Earnings|Dividend/i).first();
    if (await intelText.count() > 0) { await intelText.scrollIntoViewIfNeeded(); await page.waitForTimeout(400); }
  } catch { /* */ }
  // Detect any "Backend Pending" badges (should be NONE now)
  const pendingBadges = await page.getByText(/backend pending|coming soon/i).count();
  b.notes.push("Backend Pending badges visible: " + pendingBadges);
  // Detect the two calendar rows (Upcoming Earnings / Dividend).
  const earningsRow = await page.getByText(/upcoming earnings|earnings within|next earnings/i).count();
  const dividendRow = await page.getByText(/upcoming dividend|dividend within|next dividend/i).count();
  b.notes.push(`calendar rows — earnings:${earningsRow} dividend:${dividendRow}`);
  b.shot = await shot(page, `${label}-screener-03-intelligence-filters`);

  // 4. Live Catalysts preset — reload screener first to clear prior popover/scroll state.
  b = newBucket("screener-live-catalysts-preset", label);
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 4000);
  await page.keyboard.press("Escape").catch(() => {});
  const preset = page.getByRole("button", { name: "Live Catalysts" });
  b.notes.push("Live Catalysts button count: " + (await preset.count()));
  if ((await preset.count()) > 0) {
    const before = await rowCount();
    await preset.first().scrollIntoViewIfNeeded().catch(() => {});
    await preset.first().click();
    await settle(page, 6000);
    const after = await rowCount();
    b.notes.push(`Live Catalysts applied. rows before=${before} after=${after}`);
    b.notes.push("preset aria-current: " + (await preset.first().getAttribute("aria-current")));
    b.shot = await shot(page, `${label}-screener-04-live-catalysts`);
  } else {
    b.notes.push("Live Catalysts preset NOT found");
    b.shot = await shot(page, `${label}-screener-04-live-catalysts-NOTFOUND`);
  }

  // 5. NL search box
  b = newBucket("screener-nl-search", label);
  attachListeners(page, b);
  // Reset to default first by reloading
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 4000);
  const nl = page.getByRole("textbox", { name: /describe your screen in plain english/i })
    .or(page.getByPlaceholder(/Describe a screen/i));
  if ((await nl.count()) > 0) {
    const before = await rowCount();
    await nl.first().fill("large cap tech with PE under 30");
    await shot(page, `${label}-screener-05a-nl-typed`);
    await nl.first().press("Enter");
    await settle(page, 6000);
    const after = await rowCount();
    b.notes.push(`NL translate submitted. rows before=${before} after=${after}`);
    // capture any error message
    const errTxt = await page.getByText(/Couldn.t translate/i).count();
    b.notes.push("NL error visible: " + errTxt);
    b.shot = await shot(page, `${label}-screener-05b-nl-result`);
  } else {
    b.notes.push("NL search box NOT found");
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  await runViewport(browser, { width: 1920, height: 1080 }, "1920");
  await runViewport(browser, { width: 1440, height: 900 }, "1440");
  await browser.close();

  fs.writeFileSync(path.join(OUT, "..", "qa-data.json"), JSON.stringify(report, null, 2));
  // Console summary
  console.log("\n==== QA CAPTURE SUMMARY ====");
  for (const b of report) {
    const ce = b.consoleErrors.length, fr = b.failedRequests.length;
    console.log(`\n[${b.viewport}] ${b.page}  ${b.shot ? "("+b.shot+")" : ""}`);
    if (b.notes.length) b.notes.forEach((n) => console.log("   note: " + n));
    if (ce) { console.log("   consoleErrors: " + ce); b.consoleErrors.slice(0, 6).forEach((e) => console.log("     ! " + e.slice(0, 200))); }
    if (fr) { console.log("   failedRequests: " + fr); [...new Set(b.failedRequests)].slice(0, 10).forEach((e) => console.log("     x " + e.slice(0, 200))); }
  }
  console.log("\nDONE. Screenshots in: " + OUT);
})();
