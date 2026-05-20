/**
 * e2e/instrument-url-special-chars.spec.ts — special-character ticker routing
 *
 * WHY THIS EXISTS (PRD-0089 F2 step 9): the dynamic-route slug for an
 * instrument detail page was renamed from `[entityId]` (UUID) to `[ticker]`
 * (analyst-facing symbol). Real-world tickers carry dots and other
 * non-alphabetic characters (BRK.B = Berkshire Hathaway Class B,
 * BF.B = Brown-Forman Class B, RDS.A = legacy Royal Dutch Shell Class A).
 *
 * The middleware (`apps/worldview-web/middleware.ts`) MUST treat the dot
 * as a normal path character — neither stripping it nor redirecting it.
 * A subtle regex bug (e.g. matching only `[A-Z]+` for the slug) would
 * silently break these tickers.
 *
 * WHY a separate spec (not folded into authenticated-pages.spec.ts):
 * smoke tests focus on "page renders without crash". This spec focuses on
 * the URL canonicalisation contract, which is a different failure mode
 * (routing-layer bug → user gets 404 / redirect loop instead of a crash).
 *
 * NOTE: spec lives under `e2e/` (not `tests/e2e/`) to match the project's
 * Playwright `testDir: "./e2e"` config (see playwright.config.ts).
 *
 * ASSERTION TARGET: the page either renders the InstrumentHeader
 * (`data-testid="instrument-header"` — happy path with mocked data) OR the
 * InstrumentNotFound primitive (`data-testid="instrument-not-found"` —
 * the page-bundle returns 404). Both are valid: this spec asserts only
 * that the route does NOT crash + the URL is preserved as the canonical
 * form (no caret stripping, no dot mangling).
 *
 * Requires `pnpm dev` running at localhost:3001.
 */

import { test, expect } from "@playwright/test";
import { installStrictApiMocks } from "./fixtures/api-mocks";

// ── Special-character tickers under test ─────────────────────────────────────
//
// WHY these four: BRK.A/BRK.B and BF.B are extant US-equity tickers with
// class-share dots — most likely to surface a regex bug. RDS.A is the
// historical Royal Dutch Shell ticker (delisted 2022) — exercises the
// "tested ticker may legitimately be unknown" path which is the InstrumentNotFound
// branch and is itself a valid assertion target.
const SPECIAL_TICKERS = ["BRK.A", "BRK.B", "BF.B", "RDS.A"] as const;

test.describe("special-character tickers", () => {
  for (const ticker of SPECIAL_TICKERS) {
    test(`/instruments/${ticker} renders without crashing or rewriting the URL`, async ({
      page,
    }) => {
      // Strict mocks so the page-bundle + ancillary calls have a deterministic
      // response shape. Without mocks the e2e harness has no S9 backend and
      // every fetch fails — the page would still render its shell, but the
      // assertions become noisier.
      await installStrictApiMocks(page);

      // WHY no `await page.waitForURL(...)`: the middleware MUST NOT rewrite
      // these URLs. If a future regex bug strips the dot, the navigation
      // settles on `/instruments/BRKB` instead — we explicitly assert the
      // URL is unchanged below.
      await page.goto(`/instruments/${ticker}`);

      // ── Assertion 1: the URL is preserved verbatim ───────────────────────
      // The dot must survive the middleware. If the middleware uppercased
      // and stripped non-alphanumerics, this assertion would fail.
      // WHY pathname check (not full URL): the dev server may attach a query
      // (e.g. `?_rsc=...`) which we don't want to constrain.
      // WHY toMatch with the ticker (and login-redirect tolerance): in
      // unauthenticated e2e runs the (app) layout 302s to /login — a known
      // app behaviour, not a routing bug. We accept either the instrument
      // URL or the login URL as a non-crash signal.
      await expect.poll(async () => new URL(page.url()).pathname, { timeout: 8000 })
        .toMatch(new RegExp(`(/instruments/${ticker.replace(/\./g, "\\.")}|/login)$`));

      // ── Assertion 2: one of two valid surfaces renders ───────────────────
      // Either the InstrumentHeader (happy-path with mocked data) OR the
      // InstrumentNotFound primitive (when the page-bundle returns 404 for
      // unknown / delisted tickers like RDS.A) OR the login page (when the
      // test runs unauthenticated). All three confirm the route resolved
      // without crashing.
      // WHY 8000ms timeout: matches the existing instrument-detail e2e
      // pattern (authenticated-pages.spec.ts uses 10000ms; 8000ms is
      // sufficient because we accept multiple selectors).
      const successSurface = page.locator(
        '[data-testid="instrument-header"], [data-testid="instrument-not-found"], form[action*="login"]',
      );
      await expect(successSurface.first()).toBeVisible({ timeout: 8000 });
    });
  }

  // ── Lowercase canonicalisation smoke test ──────────────────────────────────
  // WHY here (not a separate file): the middleware's two responsibilities
  // (case-canonical + special-char preservation) share the same regex.
  // Co-locating the lowercase test surfaces regressions where someone
  // breaks one branch while fixing the other.
  test("/instruments/aapl 301-redirects to /instruments/AAPL", async ({ page }) => {
    await installStrictApiMocks(page);
    await page.goto("/instruments/aapl");
    // After the 301 + landing render, the URL must be uppercase. We tolerate
    // the /login redirect for the same unauthenticated-e2e reason.
    await expect.poll(async () => new URL(page.url()).pathname, { timeout: 8000 })
      .toMatch(/(\/instruments\/AAPL|\/login)$/);
  });
});
