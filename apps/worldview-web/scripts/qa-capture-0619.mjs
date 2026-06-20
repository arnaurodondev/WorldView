/**
 * scripts/qa-capture-0619.mjs — Current-state UI capture for the 2026-06-19
 * competitive roadmap audit. Adapted from qa-capture.mjs.
 *
 * Authenticates via the Dev Login button (real S9 backend), then screenshots
 * every key surface AFTER the 2026-06-18 design fixes, at 1920×1080 only.
 *
 * Usage: node scripts/qa-capture-0619.mjs
 */
import { chromium, request as pwRequest } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FRONTEND = "http://localhost:3001";
const OUT =
  "/Users/arnaurodon/Projects/University/final_thesis/worldview-wt-md-reliability/docs/audits/2026-06-19-ui-screenshots";
fs.mkdirSync(OUT, { recursive: true });

const report = [];

async function freshAuth() {
  const api = await pwRequest.newContext();
  const resp = await api.post(`${FRONTEND}/api/v1/auth/dev-login`, { data: {} });
  const json = await resp.json();
  await api.dispose();
  return json;
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

function attachListeners(page, bucket) {
  page.on("console", (msg) => {
    const t = msg.type();
    if (t === "error") bucket.consoleErrors.push(msg.text());
    else if (t === "warning") bucket.consoleWarnings.push(msg.text());
  });
  page.on("pageerror", (err) => bucket.consoleErrors.push("PAGEERROR: " + err.message));
  page.on("response", (resp) => {
    const s = resp.status();
    if (s >= 400) bucket.failedRequests.push(`${s} ${resp.request().method()} ${resp.url()}`);
  });
}

function newBucket(name) {
  const b = { page: name, consoleErrors: [], consoleWarnings: [], failedRequests: [], notes: [] };
  report.push(b);
  return b;
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(OUT, name + ".png"), fullPage: true });
  return name + ".png";
}

async function settle(page, ms = 3500) {
  try {
    await page.waitForLoadState("networkidle", { timeout: ms });
  } catch {
    /* ignore */
  }
  await page.waitForTimeout(1000);
}

async function devLogin(page, bucket) {
  await page.goto(`${FRONTEND}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  const btn = page.getByRole("button", { name: /dev login/i });
  if ((await btn.count()) === 0) {
    bucket.notes.push("Dev Login button NOT found on /login");
    await shot(page, "00-login-no-devbutton");
    return false;
  }
  await shot(page, "00-login-page");
  await btn.first().click();
  try {
    await page.waitForURL((u) => !u.pathname.includes("/login"), { timeout: 10000 });
  } catch {
    bucket.notes.push("Did not navigate away from /login");
  }
  await settle(page);
  bucket.notes.push("post-login URL: " + page.url());
  return !page.url().includes("/login");
}

async function run(browser) {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  await installAuthRefresh(context);
  const page = await context.newPage();

  const loginBucket = newBucket("login");
  attachListeners(page, loginBucket);
  await devLogin(page, loginBucket);

  const routes = [
    ["dashboard", "/dashboard"],
    ["portfolio", "/portfolio"],
    ["chat", "/chat"],
    ["watchlists", "/watchlists"],
    ["alerts", "/alerts"],
    ["news", "/news"],
    ["prediction-markets", "/prediction-markets"],
  ];

  for (const [name, route] of routes) {
    const b = newBucket(name);
    attachListeners(page, b);
    try {
      await page.goto(`${FRONTEND}${route}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await settle(page);
      b.notes.push("final URL: " + page.url());
      b.shot = await shot(page, name);
    } catch (e) {
      b.notes.push("NAV ERROR: " + e.message);
    }
  }

  // Instrument tabs
  await page.goto(`${FRONTEND}/instruments/AAPL`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 6000);
  for (const tab of ["quote", "financials", "intelligence"]) {
    const b = newBucket(`instrument-AAPL-${tab}`);
    attachListeners(page, b);
    try {
      const tabBtn = page.getByRole("button", { name: new RegExp(`^${tab}$`, "i") });
      if ((await tabBtn.count()) > 0) {
        await tabBtn.first().click({ timeout: 4000 });
        await settle(page, 6000); // graph at depth=1 needs time to render
        b.notes.push(`tab=${tab} current=${await tabBtn.first().getAttribute("aria-current")}`);
      } else {
        b.notes.push(`tab button NOT found: ${tab}`);
      }
      b.shot = await shot(page, `instrument-AAPL-${tab}`);
    } catch (e) {
      b.notes.push("TAB ERROR: " + e.message);
    }
  }

  await screenerDeepDive(page);
  await context.close();
}

async function screenerDeepDive(page) {
  const rowCount = async () => {
    try {
      return await page.locator(".ag-center-cols-container .ag-row").count();
    } catch {
      return -1;
    }
  };

  let b = newBucket("screener-default");
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 6000);
  b.notes.push("ag rows (default): " + (await rowCount()));
  b.shot = await shot(page, "screener-01-default");

  // Column settings + toggle intelligence/perf columns
  b = newBucket("screener-columns");
  attachListeners(page, b);
  const gear = page.getByRole("button", { name: /configure columns/i });
  if ((await gear.count()) > 0) {
    await gear.first().click();
    await page.waitForTimeout(800);
    await shot(page, "screener-02a-columns-popover");
    const wanted = ["1M RTN", "3M RTN", "Analyst Tgt", "Analyst Upside", "Inst Own%", "Brief Score"];
    let toggled = 0;
    for (const lbl of wanted) {
      const cb = page.getByRole("checkbox", { name: `Toggle ${lbl} column visibility` });
      try {
        if ((await cb.count()) > 0) {
          if ((await cb.first().getAttribute("aria-checked")) !== "true") {
            await cb.first().click({ timeout: 1500 });
            toggled++;
            await page.waitForTimeout(150);
          }
        } else b.notes.push(`col checkbox NOT found: ${lbl}`);
      } catch (e) {
        b.notes.push(`toggle err ${lbl}: ${e.message}`);
      }
    }
    b.notes.push("toggled ON: " + toggled);
    await page.keyboard.press("Escape");
    await settle(page, 4000);
    b.shot = await shot(page, "screener-02c-with-columns");
  } else {
    b.notes.push("gear NOT found");
  }

  // Intelligence filters
  b = newBucket("screener-intel-filters");
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 4000);
  const filtersToggle = page.getByRole("button", { name: /toggle screener filters/i }).first();
  if ((await filtersToggle.count()) > 0) {
    await filtersToggle.click();
    await page.waitForTimeout(1500);
  } else b.notes.push("FILTERS toggle NOT found");
  b.shot = await shot(page, "screener-03-intel-filters");

  // Live Catalysts
  b = newBucket("screener-live-catalysts");
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 4000);
  await page.keyboard.press("Escape").catch(() => {});
  const preset = page.getByRole("button", { name: "Live Catalysts" });
  if ((await preset.count()) > 0) {
    await preset.first().scrollIntoViewIfNeeded().catch(() => {});
    await preset.first().click();
    await settle(page, 6000);
    b.notes.push("rows after catalysts: " + (await rowCount()));
    b.shot = await shot(page, "screener-04-live-catalysts");
  } else {
    b.notes.push("Live Catalysts NOT found");
    b.shot = await shot(page, "screener-04-live-catalysts-NOTFOUND");
  }

  // NL search
  b = newBucket("screener-nl-search");
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/screener`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 4000);
  const nl = page
    .getByRole("textbox", { name: /describe your screen in plain english/i })
    .or(page.getByPlaceholder(/Describe a screen/i));
  if ((await nl.count()) > 0) {
    await nl.first().fill("large cap tech with PE under 30");
    await shot(page, "screener-05a-nl-typed");
    await nl.first().press("Enter");
    await settle(page, 8000);
    b.notes.push("rows after NL: " + (await rowCount()));
    b.notes.push("NL error visible: " + (await page.getByText(/Couldn.t translate/i).count()));
    b.shot = await shot(page, "screener-05b-nl-result");
  } else b.notes.push("NL search box NOT found");

  // Command palette (Cmd+K) — check the differentiator surface
  b = newBucket("command-palette");
  attachListeners(page, b);
  await page.goto(`${FRONTEND}/dashboard`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page, 3000);
  await page.keyboard.press("Meta+k").catch(() => {});
  await page.waitForTimeout(700);
  await page.keyboard.press("Control+k").catch(() => {});
  await page.waitForTimeout(900);
  b.shot = await shot(page, "command-palette");
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  await run(browser);
  await browser.close();
  fs.writeFileSync(path.join(OUT, "..", "qa-data-0619.json"), JSON.stringify(report, null, 2));
  console.log("\n==== CAPTURE SUMMARY ====");
  for (const b of report) {
    console.log(`\n${b.page}  ${b.shot ? "(" + b.shot + ")" : ""}`);
    b.notes.forEach((n) => console.log("   note: " + n));
    if (b.consoleErrors.length) {
      console.log("   consoleErrors: " + b.consoleErrors.length);
      b.consoleErrors.slice(0, 4).forEach((e) => console.log("     ! " + e.slice(0, 160)));
    }
    if (b.failedRequests.length) {
      console.log("   failedRequests: " + b.failedRequests.length);
      [...new Set(b.failedRequests)].slice(0, 8).forEach((e) => console.log("     x " + e.slice(0, 160)));
    }
  }
  console.log("\nDONE. -> " + OUT);
})();
