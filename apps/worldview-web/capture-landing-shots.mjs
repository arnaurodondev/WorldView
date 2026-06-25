/**
 * capture-landing-shots.mjs — landing-page marketing screenshots.
 *
 * Captures the 8 real product crops the redesigned landing page wires into its
 * ProductShot frames (docs/design/2026-06-23-landing-page-redesign.md §4).
 *
 * Run from apps/worldview-web/:
 *   node capture-landing-shots.mjs
 *
 * Requires: platform running at localhost:3001 (frontend) + the S9 gateway,
 * with `make seed` data loaded so the graph / news / portfolio surfaces have
 * content. Output: apps/worldview-web/public/landing/*.png at deviceScaleFactor
 * 2 (retina), cropped to marketing ratios.
 *
 * IMPORTANT (same constraint as capture-screenshots.mjs): the auth token lives
 * in React state (in-memory). page.goto() after login unmounts React and loses
 * the token → login redirect. ALL navigation after the initial dev-login MUST
 * be client-side (sidebar links / global chords that the app routes via
 * router.push), never page.goto().
 *
 * AFTER CAPTURE: flip the `placeholder` props off in the landing components
 * (HeroSection, FeatureGrid, KnowledgeGraphSpotlight) so the real PNGs render
 * instead of the fallback panels. Grep for `placeholder` in components/landing.
 */

import { chromium } from "@playwright/test";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = "http://localhost:3001";
const OUT_DIR = path.resolve(__dirname, "public/landing");
// Generous viewport so we can crop tight marketing rectangles out of it.
const VIEWPORT = { width: 1680, height: 1050 };

fs.mkdirSync(OUT_DIR, { recursive: true });

// ── Helpers ───────────────────────────────────────────────────────────────────

async function settle(page, ms = 3500) {
  // networkidle can hang forever with SSE/WebSocket connections — cap it then
  // proceed and rely on the fixed delay for layout/paint to finish.
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => null);
  await page.waitForTimeout(ms);
}

/**
 * snap — screenshot. If `clip` is provided, crop to that rectangle (used for
 * the marketing ratios); otherwise capture the full viewport.
 */
async function snap(page, filename, clip) {
  const dest = path.join(OUT_DIR, filename);
  await page.screenshot({ path: dest, fullPage: false, clip });
  console.log(`  ✓  landing/${filename}`);
}

/** A 16:10 clip rectangle anchored at (x,y). Width drives height (w * 10/16). */
function clip16x10(x, y, w) {
  return { x, y, width: w, height: Math.round((w * 10) / 16) };
}

/** Global chord (g → key) — preserves React auth state via router.push. */
async function chord(page, key, expectedPathRe) {
  await page.click("body");
  await page.waitForTimeout(200);
  await page.keyboard.press("g");
  await page.waitForTimeout(150); // within the chord-reset window
  await page.keyboard.press(key);
  await page.waitForURL(expectedPathRe, { timeout: 15_000 });
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function devLogin(page) {
  await page.goto(`${FRONTEND}/login`);
  const devBtn = page.locator("button", { hasText: /dev login/i });
  await devBtn.waitFor({ timeout: 15_000 });
  await devBtn.click();
  await page.waitForURL(`**\/dashboard**`, { timeout: 30_000 });
}

// ── Main ──────────────────────────────────────────────────────────────────────

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 2 });

// Pre-seed cookie consent so the banner never blocks the UI.
await context.addInitScript(() => {
  localStorage.setItem(
    "worldview.cookie-consent.v1",
    JSON.stringify({
      version: 1,
      necessary: true,
      analytics: false,
      preferences: true,
      decided_at: "2026-01-01T00:00:00.000Z",
    }),
  );
});

const page = await context.newPage();

console.log("Authenticating via Dev Login…");
await devLogin(page);
console.log("Authenticated — on /dashboard. (Client-side nav only from here.)\n");

// Navigate to a ticker's instrument page by clicking the first AG Grid row on
// the screener (rows fire router.push('/instruments/{ticker}') — preserves auth).
async function gotoInstrument() {
  await chord(page, "s", /\/screener/);
  const agRow = page.locator(".ag-row").first();
  await agRow.waitFor({ timeout: 20_000 });
  await agRow.click();
  await page.waitForURL(/\/instruments\//, { timeout: 20_000 });
  await settle(page, 5000);
}

// ── hero-intelligence.png + feat-instrument.png + feat-graph.png ──────────────
console.log("Instrument page (Intelligence + Quote tabs)");
await gotoInstrument();

// feat-instrument.png — the default Quote tab (chart + fundamentals), 16:10.
await snap(page, "feat-instrument.png", clip16x10(360, 110, 1280));

// Switch to the Intelligence tab for the graph crops.
const intBtn = page.locator("button").filter({ hasText: /^INTELLIGENCE$/ }).first();
await intBtn.click();
await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => null);
// Select a node so the relations / detail panel populates.
const relationBtn = page.locator('button[aria-label^="Select "]').first();
await relationBtn.waitFor({ timeout: 20_000 }).catch(() => null);
await page.waitForTimeout(2500); // sigma layout settle
if ((await page.locator('button[aria-label^="Select "]').count()) > 0) {
  await relationBtn.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await relationBtn.click({ force: true });
  await page.waitForTimeout(1500);
}

// hero-intelligence.png — graph + relations panel, ~640×440 (≈1.45 ratio).
await snap(page, "hero-intelligence.png", { x: 360, y: 110, width: 1280, height: 880 });
// feat-graph.png — tighter 16:10 crop of the same graph.
await snap(page, "feat-graph.png", clip16x10(380, 130, 1180));

// ── graph-spotlight.png — denser graph (intelligence/connections route) ───────
console.log("Knowledge-graph spotlight");
// Try the dedicated graph route via the command palette; fall back to the
// instrument Intelligence tab crop we already have.
try {
  await page.keyboard.press("Meta+k");
  const input = page
    .locator('[role="dialog"] input, [cmdk-input], input[placeholder*="Search"]')
    .first();
  await input.waitFor({ timeout: 4000 });
  await input.fill("connections");
  await page.waitForTimeout(500);
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/(connections|intelligence)/, { timeout: 8_000 });
  await settle(page, 5000);
  await snap(page, "graph-spotlight.png", { x: 320, y: 110, width: 1440, height: 1040 });
} catch {
  console.log("  (no dedicated graph route — reusing instrument graph crop)");
  await snap(page, "graph-spotlight.png", { x: 320, y: 110, width: 1440, height: 1040 });
}

// ── feat-portfolio.png ────────────────────────────────────────────────────────
console.log("Portfolio");
await chord(page, "p", /\/portfolio/);
await settle(page, 4000);
await snap(page, "feat-portfolio.png", clip16x10(360, 110, 1280));

// ── feat-screener.png ─────────────────────────────────────────────────────────
console.log("Screener");
await chord(page, "s", /\/screener/);
await page.locator(".ag-row").first().waitFor({ timeout: 20_000 }).catch(() => null);
await settle(page, 3000);
await snap(page, "feat-screener.png", clip16x10(360, 110, 1280));

// ── feat-news.png ─────────────────────────────────────────────────────────────
console.log("News (Top Today)");
await chord(page, "n", /\/news$/);
await settle(page, 4000);
await snap(page, "feat-news.png", clip16x10(360, 110, 1280));

// ── feat-chat.png ─────────────────────────────────────────────────────────────
console.log("Chat (cited answer)");
await chord(page, "c", /\/chat/);
await settle(page, 3000);
// Ask a /path query so the cited answer + confidence bar render, if an input
// is available. Best-effort: if the chat composer changes, we still snap.
try {
  const composer = page
    .locator('textarea, input[type="text"], [contenteditable="true"]')
    .first();
  await composer.waitFor({ timeout: 5000 });
  await composer.click();
  await composer.type("/path NVDA TSM");
  await page.keyboard.press("Enter");
  // Wait for the assistant answer + citations to stream in.
  await page.waitForTimeout(9000);
} catch {
  console.log("  (chat composer not found — snapping empty state)");
}
await snap(page, "feat-chat.png", clip16x10(320, 110, 1280));

await browser.close();
console.log(`\nDone. 8 landing screenshots saved to ${OUT_DIR}`);
console.log(
  "Next: flip the `placeholder` props OFF in components/landing/{HeroSection,FeatureGrid,KnowledgeGraphSpotlight}.tsx",
);
