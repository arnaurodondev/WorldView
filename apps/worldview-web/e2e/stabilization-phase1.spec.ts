/**
 * e2e/stabilization-phase1.spec.ts — PLAN-0049 T-D-4-06.
 *
 * WHY THIS EXISTS: Vitest covers the unit-level contracts but cannot guarantee
 * that the stabilization fixes hold once the real Next.js shell, ProtectedRoute
 * wrapper, AuthContext, and TanStack Query hydration are layered together.
 * Three E2E scenarios pin the stabilization wave's user-visible promises:
 *
 *   1. Empty portfolio doesn't render a "large black panel" — Holdings tab
 *      shows an honest empty state and Watchlist tab shows the create-CTA.
 *   2. SnapTrade Connection Portal v4 callbacks (only ``connection_id``, no
 *      ``authorizationId`` / ``userId`` / ``sessionId``) succeed without
 *      tripping the "Missing required callback parameters" error guard.
 *   3. Dashboard MorningBriefCard renders SOMETHING after auth — either
 *      structured ``[data-testid="brief-section"]`` cards (preferred) OR the
 *      ``[data-testid="brief-narrative"]`` markdown fallback. Either path is
 *      acceptable; the test fails only if neither renders.
 *
 * AUTH STRATEGY: Same fake-token + page.route() interception pattern used in
 * dashboard.spec.ts — no real Zitadel / S9 backend required. We mock the
 * /api/v1/auth/refresh endpoint to bypass OIDC, then stub all S9 endpoints
 * with empty/empty-success responses so widgets render their empty states
 * (which is exactly the surface this spec is testing).
 *
 * NOTE: Requires ``pnpm dev`` running at localhost:3001 — the Playwright
 * config's ``webServer`` block starts it automatically. Do NOT run this spec
 * in this thread; the parent harness will run it from the e2e pipeline.
 */

import { test, expect } from "@playwright/test";

// ── Fake-JWT helper (mirrors dashboard.spec.ts) ──────────────────────────────
/**
 * buildFakeToken — produce a JWT-shaped string with a far-future ``exp``.
 *
 * AuthContext.isTokenExpiringSoon() decodes ONLY the payload to check ``exp``;
 * it does not verify the RS256 signature client-side. So a fake "sig" is fine
 * for E2E — the real Zitadel JWKS is never contacted in this flow.
 */
function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const payload = btoa(
    JSON.stringify({
      sub: "e2e-stabilization-user",
      tenant_id: "e2e-stabilization-tenant",
      email: "stabilization@test.local",
      name: "Stabilization Test User",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.fake-e2e-sig`;
}

/**
 * mockAuth — install a page.route() handler that satisfies the AuthContext
 * refresh call so isAuthenticated becomes true without a real OIDC callback.
 *
 * MUST be called before page.goto() — Playwright route handlers attach
 * synchronously but only intercept future navigations, so any code racing
 * the navigation needs the mocks already in place.
 */
async function mockAuth(
  page: import("@playwright/test").Page,
  fakeToken: string,
): Promise<void> {
  await page.route("**/api/v1/auth/refresh", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 3600,
        user: {
          user_id: "e2e-stabilization-user",
          tenant_id: "e2e-stabilization-tenant",
          email: "stabilization@test.local",
          name: "Stabilization Test User",
        },
      }),
    });
  });

  // WHY mock the WS-token endpoint: AlertStreamContext requests a short-lived
  // WS token on mount; without this mock the request 404s in the dev shell
  // and AlertStreamContext logs a noisy error that pollutes the test output.
  await page.route("**/api/v1/auth/ws-token", (route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-token" }),
    });
  });
}

// ── Scenario 1: empty portfolio renders honest empty states ──────────────────

test.describe("PLAN-0049 stabilization — empty portfolio guards", () => {
  test("Holdings tab shows no large black panel for an empty portfolio", async ({ page }) => {
    const token = buildFakeToken();
    await mockAuth(page, token);

    // Stub every S9 endpoint with the smallest valid empty response shape:
    //   - getPortfolios → single empty manual portfolio
    //   - getHoldings   → empty holdings array
    //   - everything else → "{}" so widgets render their empty branches
    // WHY explicit shapes (not blanket "{}"): the Portfolio page's TanStack
    // queries normalise to types/api.ts shapes — undefined/missing fields
    // can crash the page (BP-265). Returning honest empties is safest.
    await page.route("**/api/v1/portfolios", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            portfolio_id: "port-empty",
            name: "Empty Portfolio",
            currency: "USD",
            owner_id: "e2e-stabilization-user",
            kind: "manual",
            created_at: "2026-04-29T00:00:00Z",
            updated_at: "2026-04-29T00:00:00Z",
          },
        ]),
      }),
    );
    await page.route("**/api/v1/portfolios/*/holdings", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          portfolio_id: "port-empty",
          holdings: [],
          total_value: null,
          total_cost: null,
          total_unrealised_pnl: null,
          total_unrealised_pnl_pct: null,
        }),
      }),
    );
    await page.route("**/api/v1/portfolios/*/value-history**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          points: [],
          metadata: { last_snapshot_at: null, next_scheduled_run_utc: null },
        }),
      }),
    );
    await page.route("**/api/v1/watchlists**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      }),
    );
    // Fallback for everything else (kept LAST so it doesn't pre-empt specific routes).
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");

    // The Holdings tab is the default — wait for the Tabs shell to mount.
    await expect(page.getByRole("tab", { name: /holdings/i })).toBeVisible({ timeout: 10000 });

    // Scan all .bg-card panels and assert none are tall (>100px) AND empty
    // of children. This is the "large black panel" the stabilization fix
    // killed: an unstyled flex container with no children appearing as a
    // void on the page.
    const panels = page.locator(".bg-card");
    const count = await panels.count();
    for (let i = 0; i < count; i++) {
      const panel = panels.nth(i);
      const visible = await panel.isVisible();
      if (!visible) continue;
      const box = await panel.boundingBox();
      if (!box || box.height <= 100) continue;
      // Tall panel — make sure it has visible children. innerText OR child
      // node count is sufficient; an empty void would have neither.
      const innerText = await panel.innerText();
      const childCount = await panel.locator(":scope > *").count();
      expect(innerText.trim().length > 0 || childCount > 0).toBeTruthy();
    }
  });

  test("Watchlist tab shows the empty CTA when there are no watchlists", async ({ page }) => {
    const token = buildFakeToken();
    await mockAuth(page, token);

    // Same fixtures as Scenario 1 (empty everywhere).
    await page.route("**/api/v1/portfolios", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            portfolio_id: "port-empty",
            name: "Empty Portfolio",
            currency: "USD",
            owner_id: "e2e-stabilization-user",
            kind: "manual",
            created_at: "2026-04-29T00:00:00Z",
            updated_at: "2026-04-29T00:00:00Z",
          },
        ]),
      }),
    );
    await page.route("**/api/v1/watchlists**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      }),
    );
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/portfolio");
    await expect(page.getByRole("tab", { name: /watchlist/i })).toBeVisible({ timeout: 10000 });

    // Click the Watchlist tab. The Tabs primitive uses role="tab" — that's
    // the canonical accessible selector and decouples us from class names.
    await page.getByRole("tab", { name: /watchlist/i }).click();

    // Empty CTA copy includes "No watchlist" — match case-insensitively. The
    // exact phrase varies between the WatchlistsTabPanel and surrounding
    // empty-state copy (e.g. "No watchlists yet" vs "Create your first
    // watchlist"); either matches the regex below.
    await expect(
      page.getByText(/no watchlist|create.*watchlist|first watchlist/i),
    ).toBeVisible({ timeout: 10000 });
  });
});

// ── Scenario 2: SnapTrade Connection Portal v4 callback ──────────────────────

test.describe("PLAN-0049 stabilization — SnapTrade v4 callback parity", () => {
  test("v4 callback (no authorizationId / userId / sessionId) does not show 'Missing required'", async ({ page }) => {
    const token = buildFakeToken();
    await mockAuth(page, token);

    // F-QAC-04 fix: track whether the page actually CALLED the upstream
    // callback endpoint with a v4-shaped query (carries connection_id but
    // NOT authorizationId/userId/sessionId). Without this, the test would
    // green-light a regression where the page never sends the request and
    // simply lingers in the loading state.
    let callbackHit = false;
    let callbackUrl = "";
    await page.route("**/api/v1/brokerage-connections/*/callback**", (route, request) => {
      callbackHit = true;
      callbackUrl = request.url();
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          connection_id: "test-conn-123",
          portfolio_id: "port-empty",
          brokerage_name: "Interactive Brokers",
          status: "active",
          last_synced_at: null,
          created_at: "2026-04-29T00:00:00Z",
        }),
      });
    });
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    // WHY this exact URL: the plan's contract is "v4 only sends connectionId
    // (ours, embedded in the redirect_uri) and connection_id (SnapTrade's
    // newly-renamed authorizationId)". Visiting WITHOUT authorizationId/
    // userId/sessionId must succeed.
    await page.goto(
      "/portfolio/brokerage/callback?connectionId=test-conn-123&connection_id=snap-auth-xyz",
    );

    // The error guard returned this exact copy when params were missing —
    // it must NEVER appear in the v4 path.
    await expect(
      page.getByText(/Missing required callback parameters/i),
    ).not.toBeVisible({ timeout: 5000 });

    // F-QAC-04 fix: tightened to require the success UI specifically (not
    // the in-progress loading state which would false-pass even if the page
    // never reached the callback endpoint).
    await expect(
      page.getByText(/connected successfully/i),
    ).toBeVisible({ timeout: 10000 });

    // F-QAC-04 fix (corrected in iter-2): the callback page DELIBERATELY
    // renames v4's `connection_id` query param to v3's `authorizationId`
    // before sending to S9 — see callback/page.tsx:67-74,119-126 and
    // lib/gateway.ts. So the OUTBOUND URL is always v3-shaped:
    //   /v1/brokerage-connections/{id}/callback?authorizationId=...
    // The point of the test is to confirm the inbound v4 query (only
    // connection_id present, no authorizationId/userId/sessionId in the
    // URL) is correctly translated to the v3 outbound shape and reaches
    // the upstream — not that the v4 names survive the proxy.
    expect(callbackHit).toBe(true);
    expect(callbackUrl).toContain("authorizationId=snap-auth-xyz");
    // userId / sessionId were absent inbound and the page does not
    // synthesise values for them, so they must be absent outbound too.
    expect(callbackUrl).not.toMatch(/[?&]userId=[^&]/);
    expect(callbackUrl).not.toMatch(/[?&]sessionId=[^&]/);
  });
});

// ── Scenario 3: dashboard MorningBriefCard renders something ─────────────────

test.describe("PLAN-0049 stabilization — MorningBriefCard renders content", () => {
  test("dashboard renders structured sections OR narrative fallback", async ({ page }) => {
    const token = buildFakeToken();
    await mockAuth(page, token);

    // WHY a populated brief: the empty branch ("AI brief unavailable") is a
    // valid state but it's not what this scenario tests. We force the LIVE
    // render path so we can assert one of the two acceptable outcomes
    // (sections OR narrative fallback).
    await page.route("**/api/v1/briefings/morning", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          // narrative is long enough to trigger the "Read more" expand.
          narrative:
            "## Drivers\n\n- Tech rallied 1.2%\n- 10Y yield -3bp\n\n## Implications\n\n- Watch Fed minutes Wed\n\n" +
            "Markets opened mixed; tech outperformed and energy lagged. Banks led the rally on rising bond yields. " +
            "Volatility ticked up modestly but breadth remained healthy across sectors.",
          summary: "Markets opened mixed; tech outperformed.",
          headline: "Markets opened mixed; tech outperformed.",
          risk_summary: null,
          entity_mentions: [],
          citations: [],
          generated_at: new Date().toISOString(),
          cached: false,
          entity_id: null,
          sections: [
            { title: "Drivers", bullets: ["Tech rallied 1.2%", "10Y yield -3bp"] },
            { title: "Implications", bullets: ["Watch Fed minutes Wed"] },
          ],
        }),
      }),
    );
    await page.route("**/api/v1/**", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
    );

    await page.goto("/dashboard");

    // Wait for the dashboard shell to mount.
    await expect(page.getByRole("main")).toBeVisible({ timeout: 10000 });

    // Click "Read more" so the structured render path is reachable. If the
    // brief is short enough that the button isn't shown, the test still
    // passes via the OR clause below.
    const readMore = page.getByRole("button", { name: /read more/i });
    if (await readMore.isVisible().catch(() => false)) {
      await readMore.click();
    }

    // Acceptable outcomes:
    //   - ≥ 1 [data-testid="brief-section"] (structured) — primary path.
    //   - 1 [data-testid="brief-narrative"] (markdown fallback) — legacy path.
    // EITHER passes; only "neither" fails. Use Playwright's expect.poll so
    // the assertion respects React's async render timing.
    await expect
      .poll(
        async () => {
          const sectionCount = await page
            .locator("[data-testid='brief-section']")
            .count();
          const narrativeCount = await page
            .locator("[data-testid='brief-narrative']")
            .count();
          return sectionCount + narrativeCount;
        },
        { timeout: 10000, message: "expected at least one brief-section OR brief-narrative" },
      )
      .toBeGreaterThanOrEqual(1);
  });
});
