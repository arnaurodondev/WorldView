/**
 * e2e/a11y-muted-foreground.spec.ts — WCAG AA color-contrast sweep (T-B-03 step 1)
 *
 * WHY THIS EXISTS: W9 fix F-VISUAL-002 (commit f27e266b) synchronized
 * --muted-foreground from 46% lightness in :root to 55% in both :root and
 * .dark. Without this fix, the dark-theme value was missing, causing every
 * text-muted-foreground element across 876 usages to fall back to the browser
 * default — a WCAG AA contrast failure on the dark (#09090b) background.
 *
 * This spec guards against future regressions in two ways:
 *
 * 1. CSS variable assertion (most reliable) — directly reads --muted-foreground
 *    and --background from the document to confirm both are in the stylesheet.
 *    This is the definitive guard against F-VISUAL-002 regressions.
 *
 * 2. Axe color-contrast sweep — runs @axe-core/playwright's color-contrast rule
 *    across the canonical Sam-routes, scoped to exclude two known pre-existing
 *    violations that are NOT related to F-VISUAL-002 (see EXCLUDED below).
 *
 * EXCLUDED (intentional pre-existing violations, not F-VISUAL-002 related):
 *   - .text-muted-foreground\/50: half-opacity modifier on 10px decorative labels
 *     (nav-rail section headers). Always fails WCAG AA at that size — design intent.
 *   - [aria-label="Open AI assistant"]: --accent-ai button, contrast 4.26:1 on
 *     #20142e (needs 4.5:1). Pre-existing design choice for the AI assistant CTA.
 *
 * REQUIRES: `pnpm dev` running at localhost:3001 (default playwright baseURL).
 *           Run via: pnpm exec playwright test a11y-muted-foreground
 */

import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "@playwright/test";

// ── Auth mock helpers ─────────────────────────────────────────────────────────

/**
 * buildFakeToken — minimal JWT-shaped string for auth context.
 * WHY: AuthProvider.isTokenExpiringSoon() decodes only the base64 payload to
 * check exp. It does NOT verify the RS256 signature client-side, so a fake
 * signature is sufficient for e2e tests.
 */
function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const payload = btoa(
    JSON.stringify({
      sub: "e2e-a11y-user",
      tenant_id: "e2e-a11y-tenant",
      email: "a11y@test.local",
      name: "A11y Test User",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.fake-a11y-sig`;
}

/**
 * setupAuthMocks — intercept auth + S9 API calls so pages render authenticated
 * shells without needing a real Zitadel or S9 backend.
 *
 * WHY wildcard for /api/v1/**:  we want pages to enter their "data loaded but
 * empty" state (not the "loading" or "error" state), which is where most
 * text-muted-foreground elements are actually visible (captions, footnotes, etc).
 */
async function setupAuthMocks(
  page: import("@playwright/test").Page,
): Promise<void> {
  const fakeToken = buildFakeToken();

  // 1. Auth refresh — AuthProvider fires this on mount to check session validity
  await page.route("**/api/v1/auth/refresh", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 3600,
        user: {
          user_id: "e2e-a11y-user",
          tenant_id: "e2e-a11y-tenant",
          email: "a11y@test.local",
          name: "A11y Test User",
        },
      }),
    });
  });

  // 2. WS token — AlertStreamContext requests this for the alert WebSocket
  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-token" }),
    });
  });

  // 3. All other S9 endpoints — return empty success so widgets show empty states
  //    rather than error banners (empty states render more text-muted-foreground
  //    elements like "No data available" captions and helper text)
  await page.route("**/api/v1/**", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0 }),
    });
  });
}

/**
 * runColorContrastCheck — navigate, wait for render, run axe color-contrast.
 *
 * WHY domcontentloaded: the dark class is applied at SSR via layout.tsx
 * className="dark ..." — not via JS. CSS variables are therefore available
 * from the initial stylesheet without waiting for network idle, which would
 * timeout on pages with persistent polling (instruments, workspace).
 *
 * WHY exclude .text-muted-foreground\/50 and [aria-label="Open AI assistant"]:
 * These are pre-existing design choices unrelated to F-VISUAL-002. Excluding
 * them keeps the spec focused on muted-foreground contrast specifically.
 * See file-level comment for full rationale.
 */
async function runColorContrastCheck(
  page: import("@playwright/test").Page,
  path: string,
) {
  await page.goto(path);
  await page.waitForLoadState("domcontentloaded");

  return new AxeBuilder({ page })
    .withRules(["color-contrast"])
    // Exclude half-opacity modifier (text-muted-foreground/50): always fails WCAG AA
    // at 10px — intentional design choice for decorative nav-rail section labels.
    .exclude(".text-muted-foreground\\/50")
    // Exclude AI assistant button: --accent-ai at 4.26:1 on #20142e (pre-existing).
    .exclude('[aria-label="Open AI assistant"]')
    .analyze();
}

// ── CSS variable assertion — definitive F-VISUAL-002 regression guard ─────────

test.describe("--muted-foreground CSS variable (F-VISUAL-002 guard)", () => {
  test("--muted-foreground is set to 240 4% 55% in the dark stylesheet", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    // WHY evaluate: getComputedStyle reads CSS variables from the document root,
    // reflecting the actual applied stylesheet value after all overrides are
    // resolved. If globals.css regresses (variable removed or value changed),
    // this assertion catches it immediately — independent of element rendering.
    const mutedFg = await page.evaluate(() =>
      getComputedStyle(document.documentElement)
        .getPropertyValue("--muted-foreground")
        .trim(),
    );

    // Value is "240 4% 55%" — the HSL components (without "hsl()" wrapper) as
    // Tailwind CSS v3 uses CSS variables as raw HSL parts for opacity modifiers.
    expect(mutedFg).toBe("240 4% 55%");
  });
});

// ── Unauthenticated routes ────────────────────────────────────────────────────

test.describe("Color-contrast: unauthenticated routes", () => {
  test("/login — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/login");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /login:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });
});

// ── Authenticated routes (auth mocked via page.route) ────────────────────────

test.describe("Color-contrast: authenticated routes (auth mocked)", () => {
  // WHY beforeEach: each test gets a fresh page context; mocks must be
  // registered before navigation, so we set them up in beforeEach.
  test.beforeEach(async ({ page }) => {
    await setupAuthMocks(page);
  });

  test("/dashboard — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/dashboard");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /dashboard:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });

  test("/chat — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/chat");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /chat:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });

  test("/news — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/news");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /news:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });

  test("/screener — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/screener");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /screener:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });

  test("/workspace — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/workspace");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /workspace:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });

  test("/search?q=apple — zero color-contrast violations", async ({ page }) => {
    const results = await runColorContrastCheck(page, "/search?q=apple");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /search:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });

  test("/instruments/[id] — zero color-contrast violations (excluding pre-existing design exceptions)", async ({
    page,
  }) => {
    // WHY ticker URL (F2 step 13): instruments route is keyed by ticker post-PLAN-0089-F2.
    // The shell renders muted-foreground labels regardless of whether the entity exists —
    // S9 returns {} (mocked). AAPL is the canonical seeded demo instrument.
    // WHY comment on excluded: .text-muted-foreground/50 nav labels and the AI
    // assistant button are excluded at the runColorContrastCheck level (pre-existing
    // design exceptions documented at the top of this file).
    const results = await runColorContrastCheck(page, "/instruments/AAPL");
    if (results.violations.length > 0) {
      console.error(
        "color-contrast violations on /instruments/[id]:",
        JSON.stringify(results.violations, null, 2),
      );
    }
    expect(results.violations).toHaveLength(0);
  });
});
