/**
 * Thesis Appendix G screenshot capture — J1–J5.
 * node capture-thesis-screenshots.mjs  (run from apps/worldview-web)
 *
 * Auth: dev-login stores JWT in React state (no httpOnly cookie).
 * All navigation MUST use real rendered <a> clicks (Next.js Link = soft nav).
 * router.push() inside components can't be called from Playwright directly.
 *
 * Pages accessible via sidebar <a>: dashboard, portfolio, alerts, chat.
 * Pages accessible by clicking rendered links:
 *   J3 /instruments/:ticker — TickerLink <a> on portfolio holdings table.
 *   J4 /alerts              — sidebar link (shows signals timeline per J4 caption).
 */

import { chromium } from "@playwright/test";
import { statSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = "http://localhost:3001";
const OUT_DIR  = path.resolve(__dirname, "../../thesis/figures");
const VIEWPORT = { width: 1920, height: 1080 };

async function settle(page, ms = 3500) {
  try { await page.waitForLoadState("networkidle", { timeout: 8000 }); } catch (_) {}
  await page.waitForTimeout(ms);
}

async function snap(page, filename) {
  const dest = path.join(OUT_DIR, filename);
  await page.screenshot({ path: dest, fullPage: false });
  const kb = Math.round(statSync(dest).size / 1024);
  console.log(`  ✓  ${filename}  (${kb}KB)`);
}

async function clickNav(page, href, urlPattern) {
  await page.locator(`a[href="${href}"]`).first().click();
  await page.waitForURL(urlPattern ?? `**${href}**`, { timeout: 15_000 });
}

// ── Launch ────────────────────────────────────────────────────────────────────
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
const page = await ctx.newPage();

// ── Auth ──────────────────────────────────────────────────────────────────────
console.log("Logging in…");
await page.goto(`${FRONTEND}/login`);
try {
  await page.locator("button", { hasText: /accept all/i }).click({ timeout: 4000 });
  await page.waitForTimeout(400);
} catch (_) {}
await page.locator("button", { hasText: /dev login/i }).click({ timeout: 15_000 });
await page.waitForURL(`${FRONTEND}/dashboard`, { timeout: 20_000 });
console.log("Auth OK.\n");

// ── J1 — Market exploration: dashboard ───────────────────────────────────────
console.log("J1 — Market exploration (dashboard)");
await settle(page, 5000);
await snap(page, "g-j1-market-exploration.png");

// ── J2 — Portfolio management ─────────────────────────────────────────────────
console.log("J2 — Portfolio management");
await clickNav(page, "/portfolio");
await settle(page, 4500);
await snap(page, "g-j2-portfolio-management.png");

// ── J3 — Entity intelligence: click a TickerLink from the holdings table ──────
// TickerLink renders <a href="/instruments/{ticker}"> — real Next.js Link
console.log("J3 — Entity intelligence (instrument detail via TickerLink)");
// Wait for holdings table rows to render, then click any instrument <a>
await page.waitForSelector(`a[href*="/instruments/"]`, { timeout: 10_000 });
// Prefer AAPL; fall back to first available ticker link
const aaplHref = `/instruments/AAPL`;
const preferred = page.locator(`a[href="${aaplHref}"]`).first();
const anyInstr  = page.locator(`a[href*="/instruments/"]`).first();
if (await preferred.isVisible({ timeout: 2000 })) {
  console.log("  → clicking AAPL link");
  await preferred.click();
} else {
  console.log("  → clicking first instrument link");
  await anyInstr.click();
}
await page.waitForURL(`**/instruments/**`, { timeout: 15_000 });
await settle(page, 5000);
await snap(page, "g-j3-entity-intelligence.png");

// ── J4 — News and signal discovery: alerts page ───────────────────────────────
// /alerts is in the sidebar and shows the signals timeline described in J4 caption
console.log("J4 — News and signal discovery (alerts / signals timeline)");
await clickNav(page, "/alerts");
await settle(page, 4000);
await snap(page, "g-j4-news-and-signals.png");

// ── J5 — Conversational research ──────────────────────────────────────────────
console.log("J5 — Conversational research (chat)");
await clickNav(page, "/chat");
await settle(page, 4000);
await snap(page, "g-j5-conversational-chat.png");

await browser.close();
console.log("\nDone — thesis/figures/ updated.");
