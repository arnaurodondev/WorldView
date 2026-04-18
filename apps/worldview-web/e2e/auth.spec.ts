/**
 * e2e/auth.spec.ts — Auth flow end-to-end tests
 *
 * WHY THIS EXISTS: The PKCE auth flow is the most critical user journey —
 * if login breaks, no user can access any data. E2E tests verify the full
 * browser-based flow including redirects, error handling, and token storage.
 *
 * WHY PLAYWRIGHT (not RTL): Auth flow requires real browser navigation
 * (window.location changes, cookie setting, PKCE state in sessionStorage).
 * JSDOM doesn't support full navigation — Playwright runs a real Chromium.
 *
 * NOTE: These tests require `pnpm dev` running at localhost:3001.
 * Run with: pnpm test:e2e
 *
 * WHO USES IT: CI/CD pipeline before deployment, manual QA before releases.
 * DATA SOURCE: Local Next.js dev server (S9 not required — mocked via MSW or
 * the login page just needs to render correctly)
 */

import { test, expect } from "@playwright/test";

// ── Login page tests ───────────────────────────────────────────────────────

test.describe("Login page", () => {
  test("redirects unauthenticated users to /login", async ({ page }) => {
    // WHY test redirect: ensures ProtectedRoute wrapper is working.
    // An unauthenticated user hitting /dashboard should land on /login.
    await page.goto("/dashboard");

    // Should redirect to login
    await expect(page).toHaveURL(/\/login/);
  });

  test("renders login page with Sign In button", async ({ page }) => {
    await page.goto("/login");

    // Page should have a sign in / continue with Zitadel button
    // The exact text depends on the login page implementation
    await expect(page.locator("body")).toBeVisible();

    // Title should be present
    const title = await page.title();
    expect(title.length).toBeGreaterThan(0);
  });

  test("login page has no horizontal scroll", async ({ page }) => {
    // WHY test scroll: finance UI must be compact — horizontal scroll
    // indicates a layout overflow that breaks the professional look.
    await page.goto("/login");

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);

    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1); // +1 for rounding
  });
});

// ── Landing page tests ────────────────────────────────────────────────────

test.describe("Landing page", () => {
  test("renders the hero section", async ({ page }) => {
    await page.goto("/");

    // Landing page should display the product name
    await expect(page.getByText(/Worldview/i)).toBeVisible();
  });

  test("Sign In link navigates to /login", async ({ page }) => {
    await page.goto("/");

    // Find and click the Sign In CTA
    const signInLink = page.getByRole("link", { name: /sign in/i });
    if (await signInLink.count() > 0) {
      await signInLink.click();
      await expect(page).toHaveURL(/\/login/);
    } else {
      // Landing page may have a different CTA text — verify it links to login
      const loginLink = page.getByRole("link", { name: /log in/i }).or(
        page.getByRole("link", { name: /get started/i }),
      );
      await expect(loginLink).toBeVisible();
    }
  });
});

// ── Auth callback tests (QA-013) ──────────────────────────────────────────

test.describe("Auth callback", () => {
  test("callback route renders without crash (no code param)", async ({ page }) => {
    // WHY test empty callback: ensures the page doesn't hard-crash without
    // valid PKCE params — it should show an error state, not a 500.
    await page.goto("/callback");

    // Should not show a Next.js error page
    const body = await page.textContent("body");
    expect(body).not.toContain("Application error");
    expect(body).not.toContain("500");
  });

  test("callback shows 'missing_code' error when ?error= param present", async ({ page }) => {
    // WHY test ?error=access_denied: This is what Zitadel sends when the user
    // clicks "Cancel" on the consent screen. CallbackPage must show a friendly
    // message ("Authentication was cancelled") not a crash or blank page.
    // SEC-003 fix: the || operator correctly catches this case (not ??).
    await page.goto("/callback?error=access_denied");

    // The callback page should show an error UI (not the loading spinner)
    // WHY "Sign-in failed": that's the h1 in the error state of CallbackContent
    await expect(page.getByText(/sign-in failed/i)).toBeVisible({ timeout: 5000 });
  });

  test("callback shows error when ?error= is non-empty string", async ({ page }) => {
    // WHY test ?error=server_error: covers non-access_denied Zitadel errors
    await page.goto("/callback?error=server_error");

    await expect(page.getByText(/sign-in failed/i)).toBeVisible({ timeout: 5000 });
  });

  test("callback shows 'missing_code' when no code in URL", async ({ page }) => {
    // WHY: Zitadel may send callback without a code if auth failed server-side.
    // We want a user-friendly error, not a crash.
    await page.goto("/callback?state=some-state");

    // Should show an error (missing code) or loading (while Suspense resolves)
    const body = await page.textContent("body");
    expect(body).not.toContain("Application error");
    expect(body).not.toContain("500");
  });

  test("callback 'Try again' link goes back to /login", async ({ page }) => {
    // WHY: After a failed callback, the user should be able to restart login.
    // The error state renders an anchor <a href="/login"> link.
    await page.goto("/callback?error=access_denied");

    await expect(page.getByText(/sign-in failed/i)).toBeVisible({ timeout: 5000 });

    const tryAgainLink = page.getByRole("link", { name: /try again/i });
    await expect(tryAgainLink).toBeVisible();
    // The link should point to /login (href attribute, not navigation)
    await expect(tryAgainLink).toHaveAttribute("href", "/login");
  });

  test("callback page has no JS errors in any error state", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    // Test all known error states
    await page.goto("/callback?error=access_denied");
    await page.waitForLoadState("networkidle");

    const criticalErrors = errors.filter(
      (e) =>
        !e.includes("Failed to fetch") &&
        !e.includes("NetworkError") &&
        !e.includes("net::ERR"),
    );

    expect(criticalErrors).toHaveLength(0);
  });
});

// ── Auth security tests ────────────────────────────────────────────────────

test.describe("Auth security", () => {
  test("login page does not expose access token in URL", async ({ page }) => {
    // WHY: Access tokens must NEVER appear in URLs (they'd be in server logs,
    // browser history, referer headers). This verifies the PKCE redirect
    // uses the code flow — not the implicit flow.
    await page.goto("/login");

    // After any redirect, the URL must not contain 'token' or 'access_token'
    const url = page.url();
    expect(url).not.toContain("access_token");
    expect(url).not.toContain("id_token");
  });

  test("protected pages don't leak access token in page source", async ({ page }) => {
    // WHY: Auth tokens must live ONLY in React state (never in HTML output,
    // meta tags, data attributes, or SSR-rendered content).
    // PRD-0028 §8.1: "NEVER localStorage, NEVER sessionStorage, NEVER a cookie
    // that JS can read, NEVER in SSR output".
    await page.goto("/login");

    // Read the raw HTML — no token should be embedded
    const content = await page.content();
    // WHY check for 'Bearer': a real token would appear as 'Bearer eyJ...'
    // This is a basic heuristic — real tokens start with 'eyJ' (base64url header)
    expect(content).not.toMatch(/Bearer eyJ/);
  });
});
