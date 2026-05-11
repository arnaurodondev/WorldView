// QA Iter 2 capture: drives a headless Chromium across the main routes,
// captures full-page screenshots at 1280/1440/1920, dumps console errors,
// and probes specific iter-1 findings.
//
// CRITICAL: token is held in React state in this app. Once we click Dev Login
// and React redirects to /dashboard, we must navigate by clicking sidebar
// links — `page.goto()` does a hard navigation and loses the token.
import { chromium } from "@playwright/test";
import fs from "node:fs";

const OUT = "/tmp/qa-iter2";
fs.mkdirSync(OUT, { recursive: true });

const consoleErrors = [];
const networkErrors = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push({ url: page.url(), text: m.text() });
  });
  page.on("pageerror", (e) => consoleErrors.push({ url: page.url(), text: `PAGEERROR: ${e.message}` }));
  page.on("response", (r) => {
    if (r.status() >= 400) networkErrors.push({ url: r.url(), status: r.status(), page: page.url() });
  });

  // Dev login
  await page.goto("http://localhost:3001/login", { waitUntil: "networkidle" });
  const devButton = page.getByRole("button", { name: /dev login/i });
  await devButton.waitFor({ timeout: 10000 });
  await devButton.click();
  await page.waitForURL("**/dashboard", { timeout: 20000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(3500); // let widgets render

  // -------- Dashboard captures
  for (const w of [1280, 1440, 1920]) {
    await page.setViewportSize({ width: w, height: 1000 });
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/dashboard-${w}.png`, fullPage: true });
  }

  // Inspect TopBar and Recent Alerts deeplinks ON DASHBOARD
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForTimeout(500);
  const topbarHtml = await page.locator("header").first().innerHTML().catch(() => "");
  fs.writeFileSync(`${OUT}/topbar.html`, topbarHtml);
  const undefinedLinks = await page.$$eval("a[href*='alerts?selected=undefined']", (els) => els.length);
  fs.writeFileSync(`${OUT}/undefined-alert-links-count.txt`, String(undefinedLinks));

  // Snapshot the visible body text on dashboard for token / pattern checks
  const dashText = await page.locator("body").innerText().catch(() => "");
  fs.writeFileSync(`${OUT}/dashboard-body-text.txt`, dashText);

  // Capture the morning brief area (first row) and the alerts widget
  const briefBox = await page.locator("text=/Morning Briefing/i").first().boundingBox().catch(() => null);
  if (briefBox) {
    await page.screenshot({ path: `${OUT}/dash-brief.png`, clip: { x: briefBox.x, y: briefBox.y, width: 800, height: 280 } });
  }

  // -------- Navigate to Portfolio via sidebar
  // Sidebar uses <Link> with title attribute matching nav item label.
  await page.locator('aside a[title="Portfolio"]').first().click().catch(async () => {
    // alternative: text-based link
    await page.getByRole("link", { name: /portfolio/i }).first().click();
  });
  await page.waitForURL("**/portfolio", { timeout: 15000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(2500);

  for (const w of [1280, 1440, 1920]) {
    await page.setViewportSize({ width: w, height: 1000 });
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/portfolio-${w}.png`, fullPage: true });
  }

  // Holdings tab
  await page.setViewportSize({ width: 1440, height: 1000 });
  const holdingsTab = page.getByRole("tab", { name: /holdings/i });
  if (await holdingsTab.count()) {
    await holdingsTab.first().click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/portfolio-holdings-tab-1440.png`, fullPage: true });
    const tableHtml = await page.locator("table").first().innerHTML().catch(() => "");
    fs.writeFileSync(`${OUT}/holdings-table.html`, tableHtml);
    // capture the KPI strip text
    const kpiText = await page.locator("body").innerText().catch(() => "");
    fs.writeFileSync(`${OUT}/portfolio-body-text.txt`, kpiText);
  }

  // -------- Alerts via sidebar
  await page.locator('aside a[title="Alerts"]').first().click().catch(async () => {
    await page.getByRole("link", { name: /alerts/i }).first().click();
  });
  await page.waitForURL("**/alerts", { timeout: 15000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(2500);

  for (const w of [1280, 1440, 1920]) {
    await page.setViewportSize({ width: w, height: 1000 });
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${OUT}/alerts-${w}.png`, fullPage: true });
  }

  const alertsBody = await page.locator("body").innerText().catch(() => "");
  fs.writeFileSync(`${OUT}/alerts-body-text.txt`, alertsBody);

  // try clicking an alert row to test deep-link / detail sheet
  // Rows use onClick handler (not href). Find a row and click it.
  // Try various selectors that match a clickable alert row.
  const rowSel = await page.locator('[role="button"]:has-text("low alert"), button:has-text("low alert"), [data-alert-row], li:has-text("low alert")').first();
  if (await rowSel.count()) {
    await rowSel.click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/alerts-selected-1440.png`, fullPage: true });
    const sheetText = await page.locator("body").innerText().catch(() => "");
    fs.writeFileSync(`${OUT}/alerts-selected-body-text.txt`, sheetText);
    fs.writeFileSync(`${OUT}/first-alert-clicked.txt`, "yes");
  } else {
    // Fallback: click any element containing "low alert" text
    const fallback = page.locator('text=/low alert/i').first();
    if (await fallback.count()) {
      await fallback.click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${OUT}/alerts-selected-1440.png`, fullPage: true });
      const sheetText = await page.locator("body").innerText().catch(() => "");
      fs.writeFileSync(`${OUT}/alerts-selected-body-text.txt`, sheetText);
      fs.writeFileSync(`${OUT}/first-alert-clicked.txt`, "fallback");
    }
  }

  // -------- back to dashboard for instrument click
  await page.locator('aside a[title="Dashboard"]').first().click().catch(async () => {
    await page.getByRole("link", { name: /dashboard/i }).first().click();
  });
  await page.waitForURL("**/dashboard", { timeout: 15000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(2500);

  // Find any instrument link
  const instrumentLink = page.locator('a[href^="/instruments/"]').first();
  if (await instrumentLink.count()) {
    const href = await instrumentLink.getAttribute("href");
    await instrumentLink.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/instrument-1440.png`, fullPage: true });
    fs.writeFileSync(`${OUT}/instrument-href.txt`, href || "");
  }

  fs.writeFileSync(`${OUT}/console-errors.json`, JSON.stringify(consoleErrors, null, 2));
  fs.writeFileSync(`${OUT}/network-errors.json`, JSON.stringify(networkErrors, null, 2));

  await browser.close();
  console.log("DONE. Errors:", consoleErrors.length, "Network errs:", networkErrors.length);
})();
