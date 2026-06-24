/**
 * Playwright script — Appendix G thesis screenshots (J1–J5).
 *
 * Run from apps/worldview-web/:
 *   node capture-screenshots.mjs
 *
 * Requires: platform running at localhost:3001 (frontend) + localhost:8000 (gateway).
 * Output: thesis/figures/g-j{1-5}-*.png at 1920×1080
 *
 * IMPORTANT: auth token lives in React state (in-memory).
 * page.goto() after login unmounts React and loses the token → login redirect.
 * All navigation after the initial login MUST be client-side (sidebar links
 * or keyboard chords that the app's hotkey system handles via router.push).
 */

import { chromium } from "@playwright/test";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = "http://localhost:3001";
const OUT_DIR = path.resolve(__dirname, "../../thesis/figures");
const VIEWPORT = { width: 1920, height: 1080 };
const TICKER = "AAPL";

// ── Helpers ───────────────────────────────────────────────────────────────────

async function settle(page, ms = 3500) {
  // networkidle can hang forever when the app has SSE or WebSocket connections.
  // Wait at most 5s for idle, then proceed regardless and rely on the fixed delay.
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => null);
  await page.waitForTimeout(ms);
}

async function snap(page, filename) {
  const dest = path.join(OUT_DIR, filename);
  await page.screenshot({ path: dest, fullPage: false });
  console.log(`  ✓  ${filename}`);
}

/**
 * navigateViaSidebar — click a sidebar <Link> to preserve React auth state.
 * The Link renders aria-label={label} unconditionally (regardless of expanded/
 * collapsed sidebar state), so we use that as the reliable selector.
 */
async function navigateViaSidebar(page, label, expectedPath) {
  // aria-label is set unconditionally on every nav link (CollapsibleSidebar.tsx:235)
  const link = page.locator(`aside nav a[aria-label="${label}"]`);
  await link.click();
  await page.waitForURL(`**${expectedPath}`, { timeout: 15_000 });
}

/**
 * navigateViaCommandPalette — open ⌘K, type a query, press Enter.
 * Used for routes not in the sidebar (e.g. /news).
 */
async function navigateViaCommandPalette(page, query, expectedPath) {
  // Open command palette — ⌘K on macOS / Ctrl+K on Linux
  await page.keyboard.press("Meta+k");
  // Wait for the command palette dialog to appear
  const input = page.locator('[role="dialog"] input, [cmdk-input], input[placeholder*="Search"]').first();
  await input.waitFor({ timeout: 5000 });
  await input.fill(query);
  await page.waitForTimeout(500);
  // Click the first result that matches the expected path
  const result = page.locator(`[role="option"]:has-text("${query}"), [cmdk-item]:has-text("${query}")`).first();
  await result.waitFor({ timeout: 3000 }).catch(() => null);
  if (await result.count() > 0) {
    await result.click();
  } else {
    // Fallback: press Enter to select the first result
    await page.keyboard.press("Enter");
  }
  await page.waitForURL(`**${expectedPath}`, { timeout: 15_000 });
}

/**
 * navigateViaAnchor — inject a client-side navigation by clicking a
 * synthetic anchor in the page context. Next.js App Router intercepts
 * same-origin anchor clicks and routes them via the client-side router,
 * preserving React state.
 */
async function navigateViaAnchor(page, href, expectedPath) {
  await page.evaluate((targetHref) => {
    const a = document.createElement("a");
    a.href = targetHref;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, href);
  await page.waitForURL(`**${expectedPath}`, { timeout: 15_000 });
}

// ── Auth ──────────────────────────────────────────────────────────────────────

/**
 * devLogin — authenticate using the dev-login button on the /login page.
 * Leaves the page on /dashboard via CLIENT-SIDE navigation (router.replace).
 * React state is preserved — DO NOT call page.goto() again after this.
 */
async function devLogin(page) {
  await page.goto(`${FRONTEND}/login`);
  const devBtn = page.locator("button", { hasText: /dev login/i });
  await devBtn.waitFor({ timeout: 15_000 });
  await devBtn.click();
  await page.waitForURL(`**\/dashboard**`, { timeout: 30_000 });
}

// ── Main ──────────────────────────────────────────────────────────────────────

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });

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
    })
  );
});

const page = await context.newPage();

console.log("Authenticating via Dev Login…");
await devLogin(page);
// We are now on /dashboard via React client-side navigation.
// Auth token lives in React state. DO NOT use page.goto() from here on.
console.log("Authenticated — on /dashboard.\n");

// ── J1 — Market exploration: dashboard ───────────────────────────────────────
console.log("J1 — Market exploration");
// Wait for the morning-brief narrative to load before snapping — the brief is
// fetched asynchronously and the banner shows blank if we snap too early.
await page.locator('[data-testid="brief-narrative"]').waitFor({ timeout: 20_000 }).catch(() => null);
await page.waitForTimeout(2000); // extra settle for market-data rows to paint
await snap(page, "g-j1-market-exploration.png");

// ── J2 — Portfolio management ────────────────────────────────────────────────
console.log("J2 — Portfolio management");
// Use global chord g→p (router.push) — more reliable than sidebar click during data load.
await page.click("body");
await page.waitForTimeout(200);
await page.keyboard.press("g");
await page.waitForTimeout(150);
await page.keyboard.press("p");
await page.waitForURL(/\/portfolio/, { timeout: 15_000 });
await settle(page, 4000);
await snap(page, "g-j2-portfolio-management.png");

// ── J3 — Entity intelligence: instrument detail page, three tabs ─────────────
console.log("J3 — Entity intelligence");

// Both the portfolio holdings and the screener use AG Grid — rows fire
// onRowClicked → router.push('/instruments/{ticker}') when clicked.
// Class `.ag-row` is the stable AG Grid row selector; clicking it preserves
// React state via the Next.js router, unlike synthetic anchor navigation.

// First: try AG Grid rows on the portfolio page (we're already there from J2).
let agRow = page.locator(".ag-row").first();
let rowVisible = await agRow.isVisible({ timeout: 6_000 }).catch(() => false);

if (!rowVisible) {
  // Navigate to screener via global chord g→s (router.push, auth preserved).
  await page.click("body");
  await page.waitForTimeout(200);
  await page.keyboard.press("g");
  await page.waitForTimeout(150);
  await page.keyboard.press("s");
  await page.waitForURL(/\/screener/, { timeout: 15_000 });
  // Wait for AG Grid to paint data rows (not just skeleton).
  agRow = page.locator(".ag-row").first();
  await agRow.waitFor({ timeout: 20_000 });
}

await agRow.click();
await page.waitForURL(/\/instruments\//, { timeout: 20_000 });
console.log("  Navigated to instrument page:", page.url());
await settle(page, 5000);

// J3a — Quote tab (default on load)
await snap(page, "g-j3a-entity-quote.png");

// J3b — Financials tab
const finBtn = page.locator("button").filter({ hasText: /^FINANCIALS$/ }).first();
await finBtn.click();
await settle(page, 4000);
await snap(page, "g-j3b-entity-fundamentals.png");

// J3c — Intelligence tab (with a node selected so the bottom detail bar populates)
const intBtn = page.locator("button").filter({ hasText: /^INTELLIGENCE$/ }).first();
await intBtn.click();
// Wait until a TopRelationsBlock relation button appears (data bundle loaded).
// If after 20s nothing appears, capture without selection.
await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => null);
const relationBtn = page.locator('button[aria-label^="Select "]').first();
await relationBtn.waitFor({ timeout: 20_000 }).catch(() => null);
await page.waitForTimeout(2000); // extra settle for graph layout + sigma render

// Trigger node selection via TopRelationsBlock relation buttons.
// aria-label="Select {label} ({relType})" → onNodeSelect() → SelectionDetailPanel fills.
const relCount = await page.locator('button[aria-label^="Select "]').count();
console.log(`  [dbg] relation buttons found: ${relCount}`);
if (relCount > 0) {
  // Scroll the button into view first, then click with force in case partially off-screen.
  await relationBtn.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await relationBtn.click({ force: true });
  await page.waitForTimeout(1500);
  // Verify inspector filled
  const inspEmpty = await page.locator('[data-testid="inspector-empty"]').isVisible().catch(() => false);
  console.log(`  [dbg] inspector empty after click: ${inspEmpty}`);
} else {
  // Fallback: non-navigable entity chip
  const detailChip = page.locator('button[aria-label^="Show details for"]').first();
  const chipCount = await page.locator('button[aria-label^="Show details for"]').count();
  console.log(`  [dbg] detail chips found: ${chipCount}`);
  if (chipCount > 0) {
    await detailChip.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    await detailChip.click({ force: true });
    await page.waitForTimeout(1500);
  }
}
await snap(page, "g-j3c-entity-intelligence.png");

// ── J4 — News and signal discovery ───────────────────────────────────────────
console.log("J4 — News and signal discovery");
// /news is not in the sidebar but has a global chord: g → n (GlobalHotkeyBindings.tsx:108).
// The chord system calls router.push('/news') which preserves React auth state.
// Ensure body has focus first so the chord isn't eaten by a focused input element.
await page.click("body");
await page.waitForTimeout(200);
await page.keyboard.press("g");
await page.waitForTimeout(150); // within the 1200ms chord reset window
await page.keyboard.press("n");
await page.waitForURL(/\/news$/, { timeout: 15_000 });
await settle(page, 4000);
await snap(page, "g-j4-news-and-signals.png");

// ── J5 — Conversational research: chat interface ──────────────────────────────
console.log("J5 — Conversational research");
// /chat has global chord: g → c (GlobalHotkeyBindings.tsx:109).
await page.click("body");
await page.waitForTimeout(200);
await page.keyboard.press("g");
await page.waitForTimeout(150);
await page.keyboard.press("c");
await page.waitForURL(/\/chat/, { timeout: 15_000 });
await settle(page, 4000);
await snap(page, "g-j5-conversational-chat.png");

await browser.close();
console.log("\nAll 7 screenshots saved to thesis/figures/");
