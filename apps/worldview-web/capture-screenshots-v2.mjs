/**
 * Thesis Appendix G screenshot capture v2 — J1, J3a/b/c, J5.
 * node capture-screenshots-v2.mjs  (run from apps/worldview-web)
 *
 * Auth: dev-login stores JWT in React state (no httpOnly cookie).
 * All navigation MUST use real rendered <a> clicks — never page.goto() after
 * login, or the React state is wiped and the user is redirected to /login.
 *
 * Changes vs v1:
 *   J1  — 10 s settle; explicit wait for a visible news/heatmap element.
 *   J3  — 3 tab screenshots (j3a quote, j3b fundamentals, j3c intelligence)
 *          instead of a single j3 screenshot.
 *   J5  — send a real finance question and wait for the AI response to stream
 *          before screenshotting so we capture a non-empty conversation.
 */

import { chromium } from "@playwright/test";
import { statSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND  = "http://localhost:3001";
const OUT_DIR   = path.resolve(__dirname, "../../thesis/figures");
const VIEWPORT  = { width: 1920, height: 1080 };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Wait for network idle then add extra settle time (ms).
 * The networkidle timeout is generous because some pages have background polls.
 */
async function settle(page, ms = 3500) {
  try {
    await page.waitForLoadState("networkidle", { timeout: 12_000 });
  } catch (_) {
    // networkidle may never fire on pages with long-polling — that's OK
  }
  await page.waitForTimeout(ms);
}

/**
 * Screenshot helper — writes to OUT_DIR and logs file size.
 */
async function snap(page, filename) {
  const dest = path.join(OUT_DIR, filename);
  await page.screenshot({ path: dest, fullPage: false });
  const kb = Math.round(statSync(dest).size / 1024);
  console.log(`  ✓  ${filename}  (${kb} KB)`);
}

/**
 * Click an <a> link by href and wait for the URL to change.
 * Uses the first matching element in case duplicates exist (e.g. sidebar + body).
 */
async function clickNav(page, href, urlPattern) {
  await page.locator(`a[href="${href}"]`).first().click();
  await page.waitForURL(urlPattern ?? `**${href}**`, { timeout: 20_000 });
}

// ---------------------------------------------------------------------------
// Launch browser
// ---------------------------------------------------------------------------
const browser = await chromium.launch({ headless: true });
const ctx  = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: 1 });
const page = await ctx.newPage();

// ---------------------------------------------------------------------------
// Auth — dev-login on /login (the only page.goto we ever call)
// ---------------------------------------------------------------------------
console.log("Logging in via dev-login…");
await page.goto(`${FRONTEND}/login`);

// Dismiss any cookie/consent banner if present
try {
  await page.locator("button", { hasText: /accept all/i }).click({ timeout: 4_000 });
  await page.waitForTimeout(400);
} catch (_) {}

await page.locator("button", { hasText: /dev login/i }).click({ timeout: 15_000 });
// After dev-login the app redirects to /dashboard
await page.waitForURL(`${FRONTEND}/dashboard`, { timeout: 25_000 });
console.log("Auth OK.\n");

// ---------------------------------------------------------------------------
// J1 — Market exploration (dashboard)
// Settle 10 s; explicit wait for a visible content element so the screenshot
// isn't captured while the page is still showing loading skeletons.
// ---------------------------------------------------------------------------
console.log("J1 — Market exploration (dashboard)");

// Wait for at least one of: sector heatmap, morning-brief section, or a news card
await Promise.race([
  page.locator(".sector-heatmap").first().waitFor({ state: "visible", timeout: 15_000 })
    .catch(() => null),
  page.locator(".morning-brief").first().waitFor({ state: "visible", timeout: 15_000 })
    .catch(() => null),
  // generic news / article card selector — common class patterns used by the dashboard
  page.locator("article, [class*='news-card'], [class*='NewsCard'], [class*='BriefCard'], [class*='brief-card']")
    .first()
    .waitFor({ state: "visible", timeout: 15_000 })
    .catch(() => null),
]).catch(() => null);

// Add the full 10 s settle so charts and heatmap tiles finish rendering
await settle(page, 10_000);
await snap(page, "g-j1-market-exploration.png");

// ---------------------------------------------------------------------------
// Navigate to Portfolio so we can click a TickerLink to reach AAPL
// ---------------------------------------------------------------------------
console.log("\nNavigating to portfolio (to reach AAPL ticker link)…");
await clickNav(page, "/portfolio");
await settle(page, 4_500);

// ---------------------------------------------------------------------------
// J3a — Entity quote tab (AAPL instrument page, default tab)
// ---------------------------------------------------------------------------
console.log("J3a — Entity quote tab (AAPL)");

// Wait for holdings table ticker links to render
await page.waitForSelector(`a[href*="/instruments/"]`, { timeout: 15_000 });

// Prefer AAPL; fall back to any instrument link
const aaplLink = page.locator(`a[href="/instruments/AAPL"]`).first();
const anyLink  = page.locator(`a[href*="/instruments/"]`).first();

if (await aaplLink.isVisible({ timeout: 3_000 }).catch(() => false)) {
  console.log("  → clicking AAPL link");
  await aaplLink.click();
} else {
  console.log("  → AAPL not visible; clicking first instrument link");
  await anyLink.click();
}

await page.waitForURL(`**/instruments/**`, { timeout: 20_000 });

// 6 s settle for the instrument page to fully load (chart, snapshot metrics)
await settle(page, 6_000);
await snap(page, "g-j3a-entity-quote.png");

// ---------------------------------------------------------------------------
// J3b — Entity fundamentals tab
// ---------------------------------------------------------------------------
console.log("J3b — Entity fundamentals tab");

// The tab buttons render as uppercase text: "QUOTE", "FINANCIALS", "INTELLIGENCE".
// Use exact text match (case-insensitive regex) to find the right button.
// We filter to buttons whose trimmed text matches exactly, to avoid partial hits.
await page.locator("button", { hasText: /^FINANCIALS$/i }).first().click();
// Wait for the fundamentals content to settle (income statement, ratios, etc.)
await settle(page, 4_000);
await snap(page, "g-j3b-entity-fundamentals.png");

// ---------------------------------------------------------------------------
// J3c — Entity intelligence tab
// ---------------------------------------------------------------------------
console.log("J3c — Entity intelligence tab");

// Click the Intelligence tab button (exact text: "INTELLIGENCE")
await page.locator("button", { hasText: /^INTELLIGENCE$/i }).first().click();
// Wait for the KG neighbourhood graph and narrative bullets to render
await settle(page, 4_000);
await snap(page, "g-j3c-entity-intelligence.png");

// ---------------------------------------------------------------------------
// J4 — News and signal discovery (alerts page)
// We still capture J4 so we don't break the existing figure reference.
// ---------------------------------------------------------------------------
console.log("\nJ4 — News and signal discovery (alerts)");
await clickNav(page, "/alerts");
await settle(page, 4_000);
await snap(page, "g-j4-news-and-signals.png");

// ---------------------------------------------------------------------------
// J5 — Conversational research (chat with real content)
// ---------------------------------------------------------------------------
console.log("\nJ5 — Conversational research (chat)");
await clickNav(page, "/chat");
await settle(page, 4_000);

// The chat thread list renders threads as div[role=button] (not <a> tags).
// We look for substantive conversations — the "What did Microsoft…" or AAPL threads
// are good choices. Strategy: prefer any thread whose title contains financial content.
// Fall back to "Start new chat" + send a real question.

const PREFERRED_THREAD_PATTERNS = [
  /microsoft.*earn/i,
  /apple.*revenue/i,
  /aapl/i,
  /holdings.*exposed/i,
  /nvda.*overvalued/i,
  /tsla/i,
];

// Locate all thread buttons in the chat history nav
const threadButtons = page.locator('[aria-label="Chat history"] [role="button"]');
const threadCount = await threadButtons.count();
console.log(`  → Found ${threadCount} existing threads`);

let clickedThread = false;

// Try to find and click a substantive thread
for (const pattern of PREFERRED_THREAD_PATTERNS) {
  for (let i = 0; i < threadCount; i++) {
    try {
      const btn = threadButtons.nth(i);
      const text = (await btn.textContent().catch(() => "")) ?? "";
      if (pattern.test(text)) {
        console.log(`  → Clicking thread matching ${pattern}: "${text.trim().substring(0, 60)}"`);
        await btn.click();
        await settle(page, 5_000);
        clickedThread = true;
        break;
      }
    } catch (_) {}
  }
  if (clickedThread) break;
}

if (!clickedThread && threadCount > 0) {
  // Click the first available thread if none matched our preferences
  console.log("  → No preferred thread found; clicking first available thread");
  await threadButtons.first().click();
  await settle(page, 5_000);
  clickedThread = true;
}

if (!clickedThread) {
  // No existing conversations at all — start a new chat and send a question.
  const QUESTION =
    "What is Apple's current revenue breakdown by segment and how has it trended over the past year?";

  console.log("  → No existing threads — starting new chat and sending question…");
  await page.locator("button[aria-label='Start new chat']").first().click();
  await page.waitForTimeout(1_500);

  // The chat input is a textarea with aria-label="Chat message input"
  const chatInput = page.locator("textarea[aria-label='Chat message input']").first();
  await chatInput.waitFor({ state: "visible", timeout: 10_000 });
  await chatInput.click();
  await chatInput.fill(QUESTION);
  await page.waitForTimeout(400); // let send button activate

  // Send via the aria-labeled send button; fall back to Enter
  const sendBtn = page.locator("button[aria-label='Send message']").first();
  if (await sendBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await sendBtn.click();
    console.log("  → Sent via 'Send message' button");
  } else {
    await chatInput.press("Enter");
    console.log("  → Sent via Enter key");
  }

  // Wait up to 30 s for the AI response to appear and stream in.
  // The response renders as a new message block in the chat feed.
  console.log("  → Waiting up to 30 s for AI response to stream in…");
  try {
    // Wait for any text content to appear that is NOT the user's own message
    await page.waitForFunction(
      (question) => {
        const paras = Array.from(document.querySelectorAll("p, [class*='message'] *"));
        return paras.some(
          (el) =>
            el.textContent &&
            el.textContent.trim().length > 80 &&
            !el.textContent.includes(question.substring(0, 30))
        );
      },
      QUESTION,
      { timeout: 30_000 }
    );
    console.log("  → AI response detected (text length > 80 chars)");
  } catch (_) {
    console.log("  ⚠  Response detection timed out — taking screenshot anyway");
  }

  // Extra settle for streaming to finish
  await settle(page, 8_000);
}

await snap(page, "g-j5-conversational-chat.png");

// ---------------------------------------------------------------------------
// Done
// ---------------------------------------------------------------------------
await browser.close();
console.log("\nDone — thesis/figures/ updated.");
