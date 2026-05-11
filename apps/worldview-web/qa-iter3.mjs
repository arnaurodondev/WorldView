// QA Iter 3 capture: re-verify F-501/F-502/F-503 against the rebuilt frontend
// (commit 1fe29ef baked at 19:32:30Z). Reuse the iter-2 walkthrough but write
// to /tmp/qa-iter3 and surface the holdings TOTAL / WEIGHT cells explicitly,
// plus a count of `limit=50` 422s on dashboard load.
import { chromium } from "@playwright/test";
import fs from "node:fs";

const OUT = "/tmp/qa-iter3";
fs.mkdirSync(OUT, { recursive: true });

const consoleErrors = [];
const networkErrors = [];
const networkAll = [];

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
    const u = r.url();
    if (u.includes("top-movers") || u.includes("/v1/")) {
      networkAll.push({ url: u, status: r.status() });
    }
    if (r.status() >= 400) networkErrors.push({ url: u, status: r.status(), page: page.url() });
  });

  // -------- Dev login
  await page.goto("http://localhost:3001/login", { waitUntil: "networkidle" });
  const devButton = page.getByRole("button", { name: /dev login/i });
  await devButton.waitFor({ timeout: 10000 });
  await devButton.click();
  await page.waitForURL("**/dashboard", { timeout: 20000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(4000);

  // Capture dashboard at 1440 (representative)
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${OUT}/dashboard-1440.png`, fullPage: true });
  const dashText = await page.locator("body").innerText().catch(() => "");
  fs.writeFileSync(`${OUT}/dashboard-body-text.txt`, dashText);

  // -------- Portfolio
  await page.locator('aside a[title="Portfolio"]').first().click().catch(async () => {
    await page.getByRole("link", { name: /portfolio/i }).first().click();
  });
  await page.waitForURL("**/portfolio", { timeout: 15000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(2500);

  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/portfolio-1440.png`, fullPage: true });

  // Holdings tab — the F-501/F-502 verification surface
  const holdingsTab = page.getByRole("tab", { name: /holdings/i });
  if (await holdingsTab.count()) {
    await holdingsTab.first().click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/portfolio-holdings-tab-1440.png`, fullPage: true });

    // Table HTML
    const tableHtml = await page.locator("table").first().innerHTML().catch(() => "");
    fs.writeFileSync(`${OUT}/holdings-table.html`, tableHtml);

    // Body text for KPI strip & TOTAL row
    const portText = await page.locator("body").innerText().catch(() => "");
    fs.writeFileSync(`${OUT}/portfolio-body-text.txt`, portText);

    // Surface specific TOTAL row cell text and WEIGHT column cells
    const tfootText = await page.locator("table tfoot").first().innerText().catch(() => "(no tfoot)");
    fs.writeFileSync(`${OUT}/holdings-tfoot.txt`, tfootText);

    // Each WEIGHT cell — find the column index by header
    // We grab full row text array, then pick rows with weights.
    const rows = await page.$$eval("table tbody tr", (trs) =>
      trs.map((tr) => {
        const cells = Array.from(tr.querySelectorAll("td")).map((td) => td.innerText.trim());
        return cells;
      })
    );
    fs.writeFileSync(`${OUT}/holdings-rows.json`, JSON.stringify(rows, null, 2));

    // Also collect header names
    const heads = await page.$$eval("table thead th", (ths) =>
      ths.map((th) => th.innerText.trim())
    );
    fs.writeFileSync(`${OUT}/holdings-heads.json`, JSON.stringify(heads, null, 2));
  }

  // -------- Alerts list
  await page.locator('aside a[title="Alerts"]').first().click().catch(async () => {
    await page.getByRole("link", { name: /alerts/i }).first().click();
  });
  await page.waitForURL("**/alerts", { timeout: 15000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(2500);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/alerts-1440.png`, fullPage: true });
  const alertsBody = await page.locator("body").innerText().catch(() => "");
  fs.writeFileSync(`${OUT}/alerts-body-text.txt`, alertsBody);

  // click first alert row
  const rowSel = page.locator('[role="button"]:has-text("low alert"), button:has-text("low alert"), li:has-text("low alert")').first();
  if (await rowSel.count()) {
    await rowSel.click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/alerts-selected-1440.png`, fullPage: true });
    const sheetText = await page.locator("body").innerText().catch(() => "");
    fs.writeFileSync(`${OUT}/alerts-selected-body-text.txt`, sheetText);
  }

  // -------- Instrument detail (regression)
  await page.locator('aside a[title="Dashboard"]').first().click().catch(async () => {
    await page.getByRole("link", { name: /dashboard/i }).first().click();
  });
  await page.waitForURL("**/dashboard", { timeout: 15000 });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(2000);

  const instrumentLink = page.locator('a[href^="/instruments/"]').first();
  if (await instrumentLink.count()) {
    await instrumentLink.click();
    await page.waitForLoadState("networkidle").catch(() => {});
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/instrument-1440.png`, fullPage: true });
  }

  // count limit=50 occurrences in network log (F-503 regression check)
  const limit50 = networkAll.filter((r) => r.url.includes("limit=50"));
  const topMoversAll = networkAll.filter((r) => r.url.includes("top-movers"));
  fs.writeFileSync(`${OUT}/topmovers-network.json`, JSON.stringify(topMoversAll, null, 2));
  fs.writeFileSync(`${OUT}/limit50-count.txt`, String(limit50.length));

  fs.writeFileSync(`${OUT}/console-errors.json`, JSON.stringify(consoleErrors, null, 2));
  fs.writeFileSync(`${OUT}/network-errors.json`, JSON.stringify(networkErrors, null, 2));

  await browser.close();
  console.log("DONE. Console errs:", consoleErrors.length, "Network 4xx/5xx:", networkErrors.length, "limit=50 hits:", limit50.length);
})();
