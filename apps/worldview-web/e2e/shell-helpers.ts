/**
 * e2e/shell-helpers.ts — shared auth + S9 stubs for PRD-0089 W1 shell specs.
 *
 * WHY THIS EXISTS: the six shell-*.spec.ts files all need the same
 * fake-JWT + auth-refresh + S9 catch-all stub before they navigate. Sharing
 * it via a single helper keeps the specs focused on the assertion they
 * actually make instead of repeating ~80 lines of mock plumbing.
 *
 * USAGE:
 *   import { installShellAuthMocks } from "./shell-helpers";
 *   test.beforeEach(async ({ page }) => { await installShellAuthMocks(page); });
 */

import type { Page, Route } from "@playwright/test";

/** Build a JWT-shaped token with a 1-hour exp so AuthContext treats it as valid. */
export function buildFakeToken(): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  const payload = btoa(JSON.stringify({
    sub: "e2e-test-user",
    tenant_id: "e2e-test-tenant",
    email: "e2e@test.local",
    name: "E2E Test User",
    exp: Math.floor(Date.now() / 1000) + 3600,
  })).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${header}.${payload}.fake-e2e-sig`;
}

/** Single-watchlist response with one AAPL member — drives the click test. */
export const SAMPLE_WATCHLISTS_RESPONSE = [
  {
    watchlist_id: "wl-e2e-1",
    name: "Tech",
    owner_id: "e2e-test-user",
    member_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    members: [
      {
        entity_id: "e-aapl",
        instrument_id: "i-aapl",
        ticker: "AAPL",
        name: "Apple Inc.",
        added_at: "2026-01-01T00:00:00Z",
        resolution: "resolved",
      },
    ],
  },
];

/**
 * installShellAuthMocks — wire fake auth + S9 catch-all stubs so the
 * (app)/layout renders without crashing. Specific specs may add their own
 * page.route() overrides AFTER calling this to inject richer payloads.
 */
export async function installShellAuthMocks(page: Page): Promise<void> {
  const fakeToken = buildFakeToken();

  await page.route("**/api/v1/auth/refresh", (route: Route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: fakeToken,
        expires_in: 3600,
        user: {
          user_id: "e2e-test-user",
          tenant_id: "e2e-test-tenant",
          email: "e2e@test.local",
          name: "E2E Test User",
        },
      }),
    });
  });

  await page.route("**/api/v1/auth/ws-token", (route: Route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ token: "fake-ws-token" }),
    });
  });

  // Watchlists — populated so the WatchlistPanel renders an AAPL row.
  await page.route("**/api/v1/watchlists**", (route: Route) => {
    if (route.request().method() === "GET") {
      void route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_WATCHLISTS_RESPONSE),
      });
      return;
    }
    void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });

  // Search — return ticker-as-id so IndexStrip resolution succeeds.
  await page.route("**/api/v1/search/instruments**", (route: Route) => {
    const url = new URL(route.request().url());
    const q = url.searchParams.get("q") ?? "UNKNOWN";
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: [{ instrument_id: `id-${q}`, ticker: q, name: `${q} Resolved` }],
      }),
    });
  });

  // Batch quotes — flat $100 / +0.5% across the board.
  await page.route("**/api/v1/quotes/batch**", (route: Route) => {
    const body = route.request().postDataJSON() as { instrument_ids?: string[] } | null;
    const ids = body?.instrument_ids ?? [];
    const quotes = Object.fromEntries(
      ids.map((id) => [id, {
        ticker: id,
        price: 100,
        change: 0.5,
        change_pct: 0.5,
        timestamp: new Date().toISOString(),
        volume: 1_000_000,
        freshness_status: "live",
      }]),
    );
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ quotes }),
    });
  });

  // Catch-all for every remaining S9 route — empty success keeps the layout
  // crash-free while individual specs are focused on UI assertions only.
  await page.route("**/api/v1/**", (route: Route) => {
    void route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
}
