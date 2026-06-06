/**
 * e2e/chat-polish.spec.ts — PLAN-0089 K Block I T-23
 *
 * THREE PLAYWRIGHT ACCEPTANCE TESTS for the Wave K chat surface:
 *   1. Density gate ≥50 [data-cell] elements at 1440×900 (acceptance gate #1).
 *   2. Citation hover reveals the hovercard within 300ms (acceptance gate #12).
 *   3. ⌘D toggles the ToolTraceDrawer ONLY when ?debug=1 is in the URL (Q-8).
 *
 * FIXTURE STRATEGY:
 *   The /chat page reads threads + messages from S9 via TanStack Query and
 *   streams new messages via POST /v1/chat/stream. To exercise a deterministic
 *   "full" chat surface (turns + citations + tools + contradictions) without
 *   a live backend, the tests intercept the S9 routes via page.route() and
 *   serve a hand-crafted thread containing one user turn + one assistant
 *   turn with 5 citations, 2 contradictions and 4 follow-up chips' worth of
 *   primitives. This mirrors the unit-level density fixture in
 *   features/chat/components/__tests__/chat-density.test.tsx.
 *
 *   TODO(PLAN-0089-K-FU): the chat page does NOT yet read `thread_id` from
 *   the URL — it stores activeThreadId in component state. As a result the
 *   `?thread_id=fixture-thread-1` query param in `goto()` is informational
 *   (matches the test's intent of seeding a specific thread). The tests
 *   below rely on the page rendering whichever thread the GET /v1/threads
 *   list returns first, which is the fixture we inject. Once the page wires
 *   thread_id ← URL the assertions stay valid (deterministic fixture wins).
 *
 * RUNTIME NOTE:
 *   Playwright requires a running dev server (pnpm dev) on localhost:3001.
 *   In agent contexts without a dev server, `pnpm exec playwright test --list`
 *   confirms the spec parses. Full runtime execution is deferred to the QA
 *   pass (after merge, on CI with `make test:e2e`).
 *
 * AUTH:
 *   Fake JWT injected via addInitScript — same pattern as the W7
 *   instrument-intelligence.spec.ts. The /chat page is auth-gated.
 */

import { test, expect, type Page } from "@playwright/test";

// ── Auth helper ──────────────────────────────────────────────────────────

function buildFakeToken(): string {
  // base64url-safe JWT for the dev-login path. The header / payload are
  // hand-crafted so the page-level auth guard accepts them; the signature
  // is a placeholder (S9 is not contacted in e2e).
  const b64url = (s: string) =>
    Buffer.from(s).toString("base64").replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = b64url(
    JSON.stringify({
      sub: "e2e-chat-polish",
      tenant_id: "e2e-tenant",
      email: "chat-polish@test.local",
      name: "Chat Polish E2E",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  );
  return `${header}.${payload}.fake-chat-polish-sig`;
}

// ── Fixture: a single thread with one dense assistant turn ────────────────

const THREAD_ID = "fixture-thread-1";
const MESSAGE_ID = "fixture-msg-1";

const FIXTURE_THREADS = [
  {
    thread_id: THREAD_ID,
    title: "Wave K density fixture",
    owner_id: "e2e-chat-polish",
    created_at: "2026-05-26T14:00:00Z",
    updated_at: "2026-05-26T14:01:24Z",
    message_count: 2,
    messages: [],
  },
];

// WHY 5 citations + 3 contradictions: the density fixture must clear the
// ≥50 cells gate by itself; the unit test in chat-density.test.tsx uses
// the same payload shape with 5 turns. Here a single dense turn plus the
// rail's repeated cells push us past 50.
function makeCitation(idx: number) {
  return {
    id: `c-${idx}`,
    kind: "article",
    title: `Source ${idx}`,
    source: "Bloomberg",
    url: "https://example.com",
    relevance_score: 0.7,
  };
}

const FIXTURE_MESSAGES = [
  {
    message_id: "fixture-user-1",
    thread_id: THREAD_ID,
    role: "user",
    content: "What's the outlook on Apple?",
    created_at: "2026-05-26T14:00:30Z",
    citations: [],
  },
  {
    message_id: MESSAGE_ID,
    thread_id: THREAD_ID,
    role: "assistant",
    content: "Apple's outlook is mixed. [1] [2] [3] Bear/bull views below.",
    created_at: "2026-05-26T14:01:00Z",
    citations: [
      makeCitation(1),
      makeCitation(2),
      makeCitation(3),
      makeCitation(4),
      makeCitation(5),
    ],
    contradictions: [
      { claim_type: "outlook", strength: 0.85 },
      { claim_type: "guidance_change", strength: 0.5 },
      { claim_type: "supplier_risk", strength: 0.3 },
    ],
    provider: "DeepInfra",
    model: "deepseek-r1",
    latency_ms: 1450,
  },
];

// ── Route setup ───────────────────────────────────────────────────────────

async function setupRoutes(page: Page): Promise<void> {
  // Catch-all 200-empty so unmatched calls don't 404 and trigger error
  // banners. Registered first so explicit routes below override.
  await page.route("**/v1/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  // List threads — the /chat page boots with this and picks the first.
  await page.route("**/v1/threads*", async (route) => {
    if (route.request().method() !== "GET") {
      // POST creates a new thread — return the fixture so the page lands
      // on it.
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(FIXTURE_THREADS[0]),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ threads: FIXTURE_THREADS }),
    });
  });

  // Fetch a specific thread (and its messages).
  await page.route(`**/v1/threads/${THREAD_ID}*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...FIXTURE_THREADS[0], messages: FIXTURE_MESSAGES }),
    });
  });

  // Messages list (some routes split out from the thread object).
  await page.route(`**/v1/threads/${THREAD_ID}/messages*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ messages: FIXTURE_MESSAGES }),
    });
  });
}

async function seedChatPage(page: Page, withDebug = false): Promise<void> {
  await page.addInitScript((token) => {
    window.localStorage.setItem("wv_access_token", token);
    window.localStorage.setItem("wv_refresh_token", "fake-chat-polish-refresh");
  }, buildFakeToken());

  // TODO(PLAN-0089-K-FU): once the chat page reads `thread_id` from the URL
  // this query-string will deterministically pin the fixture thread.
  const url = withDebug
    ? `/chat?thread_id=${THREAD_ID}&debug=1`
    : `/chat?thread_id=${THREAD_ID}`;
  await page.goto(url);
  await page.waitForLoadState("networkidle");
}

// ── Tests ─────────────────────────────────────────────────────────────────

test.describe("Chat Polish (PLAN-0089 Wave K)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupRoutes(page);
  });

  test("density gate ≥50 [data-cell] elements at 1440×900", async ({ page }) => {
    // WHY this gate: matches acceptance gate #1 (≥50 cells visible above
    // the fold). The fixture above renders 1 dense assistant turn + the
    // ChatContextRail's four sections — comfortably >50 in production.
    await seedChatPage(page);
    await page.waitForSelector("[data-cell]", { timeout: 10_000 });
    const cells = await page.locator("[data-cell]").count();
    expect(cells).toBeGreaterThanOrEqual(50);
  });

  test("citation hover reveals the hovercard within 300ms", async ({ page }) => {
    // WHY 300ms: HoverCard openDelay is 250ms inside CitationStrip; the
    // 300ms ceiling adds 50ms slack for layout + Radix mount jitter. If
    // future tweaks loosen the delay above 250ms the test catches it.
    await seedChatPage(page);
    // CitationStrip rows carry [data-citation-row]. Hover the first one;
    // Radix renders the HoverCardContent with attribute
    // data-radix-popper-content-wrapper at mount time. We assert on the
    // hovercard content container that CitationHoverCard emits.
    const firstRow = page.locator("[data-citation-row]").first();
    await firstRow.waitFor({ state: "visible", timeout: 10_000 });
    await firstRow.hover();
    // Radix portals content under the body — match either the data-state
    // attribute on the content (when used as HoverCardContent) or the
    // popper wrapper Radix injects.
    await expect(
      page.locator('[data-radix-popper-content-wrapper], [role="dialog"]').first(),
    ).toBeVisible({ timeout: 300 });
  });

  test("?debug=1 reveals the ToolTraceDrawer via ⌘D (Q-8 gate)", async ({ page }) => {
    // WHY the negative case is asserted in the same test: the Q-8 lock is
    // BOTH directions — debug=0 must keep the drawer hidden EVEN with the
    // chord. A separate test could allow the negative case to silently
    // regress.
    await seedChatPage(page, /* withDebug */ true);
    await page.waitForSelector("[data-cell]", { timeout: 10_000 });
    // The drawer is gated on a focused assistant turn. Click the assistant
    // message turn to focus it before firing the chord.
    const assistantTurn = page.locator(`[data-message-turn="${MESSAGE_ID}"]`).first();
    await assistantTurn.click();
    // ⌘D on macOS / Ctrl+D on linux/win — useToolTraceChord handles both.
    await page.keyboard.press("Meta+D");
    await expect(page.locator('[data-testid="tool-trace-drawer"]')).toBeVisible({
      timeout: 1000,
    });

    // Negative case: same chord without ?debug=1 must NOT open the drawer.
    await seedChatPage(page, /* withDebug */ false);
    await page.waitForSelector("[data-cell]", { timeout: 10_000 });
    await page.keyboard.press("Meta+D");
    await expect(page.locator('[data-testid="tool-trace-drawer"]')).not.toBeVisible();
  });
});
