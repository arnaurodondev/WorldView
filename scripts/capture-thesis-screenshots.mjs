/**
 * Playwright script — Appendix G thesis screenshots (J1–J5).
 * Run from repo root: node scripts/capture-thesis-screenshots.mjs
 * Requires: platform running at localhost:3001 (frontend) + localhost:8000 (gateway).
 * Output: thesis/figures/g-j{1-5}-*.png at 1920×1080
 */

import { chromium } from "@playwright/test";
import { createRequire } from "module";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = "http://localhost:3001";
const OUT_DIR = path.resolve(__dirname, "../thesis/figures");
const VIEWPORT = { width: 1920, height: 1080 };
const TICKER = "AAPL";

async function devLogin(page) {
  await page.goto(`${FRONTEND}/login`);
  const devBtn = page.locator("button", { hasText: /dev login/i });
  await devBtn.waitFor({ timeout: 15_000 });
  await devBtn.click();
  await page.waitForURL(`${FRONTEND}/dashboard`, { timeout: 20_000 });
}

async function settle(page, ms = 3500) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
}

async function snap(page, filename) {
  const dest = path.join(OUT_DIR, filename);
  await page.screenshot({ path: dest, fullPage: false });
  console.log(`  ✓  ${filename}`);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
const page = await context.newPage();

console.log("Authenticating via Dev Login…");
await devLogin(page);
console.log("Authenticated.\n");

// J1 — Market exploration: dashboard (daily brief + sector heatmap)
console.log("J1 — Market exploration");
await page.goto(`${FRONTEND}/dashboard`);
await settle(page, 4000);
await snap(page, "g-j1-market-exploration.png");

// J2 — Portfolio management: holdings overview
console.log("J2 — Portfolio management");
await page.goto(`${FRONTEND}/portfolio`);
await settle(page, 4000);
await snap(page, "g-j2-portfolio-management.png");

// J3 — Entity intelligence: instrument detail page (AAPL), three tabs
console.log("J3 — Entity intelligence");
await page.goto(`${FRONTEND}/instruments/${TICKER}`);
await settle(page, 5000);
// J3a — Quote tab (default, active on load)
await snap(page, "g-j3a-entity-quote.png");
// J3b — Financials tab
await page.click("button:has-text('FINANCIALS')");
await settle(page, 4000);
await snap(page, "g-j3b-entity-fundamentals.png");
// J3c — Intelligence tab
await page.click("button:has-text('INTELLIGENCE')");
await settle(page, 5000);
await snap(page, "g-j3c-entity-intelligence.png");

// J4 — News and signal discovery: ranked feed
console.log("J4 — News and signal discovery");
await page.goto(`${FRONTEND}/news`);
await settle(page, 4000);
await snap(page, "g-j4-news-and-signals.png");

// J5 — Conversational research: chat interface
console.log("J5 — Conversational research");
await page.goto(`${FRONTEND}/chat`);
await settle(page, 4000);
await snap(page, "g-j5-conversational-chat.png");

await browser.close();
console.log("\nAll 7 screenshots saved to thesis/figures/");
