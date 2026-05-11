// Iter-3 network/console sweep: just walk dashboard -> portfolio -> alerts and
// dump errors. We don't need screenshots here; the main runner already has them.
import { chromium } from "@playwright/test";
import fs from "node:fs";

const OUT = "/tmp/qa-iter3";
fs.mkdirSync(OUT, { recursive: true });

const consoleErrors = [];
const networkErrors = [];
const allReqs = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push({ url: page.url(), text: m.text() });
  });
  page.on("pageerror", (e) => consoleErrors.push({ url: page.url(), text: `PAGEERROR: ${e.message}` }));
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/v1/")) allReqs.push({ url: u, status: r.status() });
    if (r.status() >= 400) networkErrors.push({ url: u, status: r.status(), page: page.url() });
  });

  await page.goto("http://localhost:3001/login", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /dev login/i }).first().click();
  await page.waitForURL("**/dashboard", { timeout: 20000 });
  await page.waitForTimeout(6000);

  // Portfolio
  const portfolioLink = page.locator('aside a[title="Portfolio"], aside a:has-text("Portfolio")').first();
  await portfolioLink.waitFor({ timeout: 15000 });
  await portfolioLink.click();
  await page.waitForURL("**/portfolio", { timeout: 15000 });
  await page.waitForTimeout(3000);

  // Holdings tab
  const holdingsTab = page.getByRole("tab", { name: /holdings/i });
  if (await holdingsTab.count()) {
    await holdingsTab.first().click();
    await page.waitForTimeout(1500);
  }

  // Alerts
  const alertsLink = page.locator('aside a[title="Alerts"], aside a:has-text("Alerts")').first();
  await alertsLink.waitFor({ timeout: 15000 });
  await alertsLink.click();
  await page.waitForURL("**/alerts", { timeout: 15000 });
  await page.waitForTimeout(2500);

  // Click first alert row
  const row = page.locator('button:has-text("low alert"), li:has-text("low alert")').first();
  if (await row.count()) {
    await row.click();
    await page.waitForTimeout(1500);
  }

  fs.writeFileSync(`${OUT}/console-errors.json`, JSON.stringify(consoleErrors, null, 2));
  fs.writeFileSync(`${OUT}/network-errors.json`, JSON.stringify(networkErrors, null, 2));
  const limit50 = allReqs.filter((r) => r.url.includes("limit=50"));
  const topMovers = allReqs.filter((r) => r.url.includes("top-movers"));
  fs.writeFileSync(`${OUT}/topmovers-network.json`, JSON.stringify(topMovers, null, 2));
  fs.writeFileSync(`${OUT}/limit50-count.txt`, String(limit50.length));
  fs.writeFileSync(`${OUT}/limit50-list.json`, JSON.stringify(limit50, null, 2));
  fs.writeFileSync(`${OUT}/all-reqs.json`, JSON.stringify(allReqs, null, 2));

  await browser.close();
  console.log("DONE. Console errs:", consoleErrors.length, "Network 4xx/5xx:", networkErrors.length, "limit=50 hits:", limit50.length, "top-movers calls:", topMovers.length);
})();
