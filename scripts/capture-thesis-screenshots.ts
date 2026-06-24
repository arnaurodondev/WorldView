/**
 * Playwright script to capture Appendix G thesis screenshots (J1–J5).
 *
 * Run from the worldview-web directory:
 *   cd apps/worldview-web
 *   npx playwright --config=../../scripts/capture-playwright.config.ts \
 *       ../../scripts/capture-thesis-screenshots.ts
 *
 * Or directly:
 *   cd apps/worldview-web && npx ts-node ../../scripts/capture-thesis-screenshots.ts
 *
 * Requires: platform running at localhost:3001 (frontend) + localhost:8000 (gateway).
 * Output: thesis/figures/g-j{1-5}-*.png (1920×1080 PNG, full-page)
 */

import { chromium, Browser, Page } from "playwright";
import * as path from "path";

const FRONTEND = "http://localhost:3001";
const OUT_DIR = path.resolve(__dirname, "../thesis/figures");
const VIEWPORT = { width: 1920, height: 1080 };

// Instrument to use for J3 entity intelligence (AAPL has full data)
const TICKER = "AAPL";

async function devLogin(page: Page): Promise<void> {
  await page.goto(`${FRONTEND}/login`);
  // Wait for the Dev Login button (only shown when Zitadel is not configured)
  const devBtn = page.locator("button", { hasText: /dev login/i });
  await devBtn.waitFor({ timeout: 15_000 });
  await devBtn.click();
  // Wait for redirect to dashboard after successful auth
  await page.waitForURL(`${FRONTEND}/dashboard`, { timeout: 20_000 });
}

async function settle(page: Page, ms = 3000): Promise<void> {
  // Wait for network to quiet down, then a short buffer for renders
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
}

async function screenshot(page: Page, filename: string): Promise<void> {
  const dest = path.join(OUT_DIR, filename);
  await page.screenshot({ path: dest, fullPage: false });
  console.log(`  ✓  ${filename}`);
}

async function main(): Promise<void> {
  const browser: Browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  console.log("Authenticating via Dev Login…");
  await devLogin(page);
  console.log("Authenticated. Starting captures.\n");

  // ── J1 — Market exploration ──────────────────────────────────────────────
  console.log("J1 — Market exploration");
  await page.goto(`${FRONTEND}/dashboard`);
  await settle(page, 4000);
  await screenshot(page, "g-j1-market-exploration.png");

  // ── J2 — Portfolio management ────────────────────────────────────────────
  console.log("J2 — Portfolio management");
  await page.goto(`${FRONTEND}/portfolio`);
  await settle(page, 4000);
  await screenshot(page, "g-j2-portfolio-management.png");

  // ── J3 — Entity intelligence (3 tabs: Quote / Financials / Intelligence) ─
  console.log("J3 — Entity intelligence");
  await page.goto(`${FRONTEND}/instruments/${TICKER}`);
  await settle(page, 5000);

  // J3a — Quote tab (default, already active on load)
  await screenshot(page, "g-j3a-entity-quote.png");

  // J3b — Financials tab
  await page.click("button:has-text('FINANCIALS')");
  await settle(page, 4000);
  await screenshot(page, "g-j3b-entity-fundamentals.png");

  // J3c — Intelligence tab
  await page.click("button:has-text('INTELLIGENCE')");
  await settle(page, 5000);
  await screenshot(page, "g-j3c-entity-intelligence.png");

  // ── J4 — News and signal discovery ──────────────────────────────────────
  console.log("J4 — News and signal discovery");
  await page.goto(`${FRONTEND}/news`);
  await settle(page, 4000);
  await screenshot(page, "g-j4-news-and-signals.png");

  // ── J5 — Conversational research ────────────────────────────────────────
  console.log("J5 — Conversational research");
  await page.goto(`${FRONTEND}/chat`);
  await settle(page, 4000);
  await screenshot(page, "g-j5-conversational-chat.png");

  await browser.close();
  console.log("\nAll 7 screenshots captured → thesis/figures/");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
