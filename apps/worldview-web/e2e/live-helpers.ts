/**
 * e2e/live-helpers.ts — canonical LIVE-BACKEND auth + utilities for @live specs.
 *
 * WHY THIS EXISTS
 * ---------------
 * The pre-existing `qa-live-stack.spec.ts` authenticates by clicking a "Dev Login"
 * button on `/login`. The 2026-06-22 E2E-gaps audit found that button does NOT
 * render on this deployment (Zitadel is configured, and `GET /api/v1/auth/login`
 * returns 502) — so that whole spec fails at auth. This helper replaces it with a
 * deployment-robust seam that the audit explicitly recommends:
 *
 *   1. Mint a REAL RS256 JWT from the backend dev-login endpoint
 *      (`POST {API}/v1/auth/dev-login`). The backend signs it with the same key
 *      the downstream services verify, so every subsequent call is genuinely
 *      authenticated against the LIVE stack — no data stubs.
 *   2. Inject that token into the app by intercepting ONLY the silent-refresh
 *      call the frontend fires on mount (`POST /api/v1/auth/refresh`) and
 *      returning `{ access_token, expires_in, user }`. The AuthContext stores the
 *      token in React state and attaches it as `Authorization: Bearer …` to every
 *      gateway call — exactly as a real session would.
 *
 * CRITICAL: we intercept ONLY `/api/v1/auth/refresh`. We do NOT install a
 * catch-all "(glob)/api/v1/(glob) -> {}" stub (that is the mock-driven pattern in
 * `shell-helpers.ts`). Every other request flows to the real S9 gateway, so these
 * specs exercise real backend response shapes and real-data integration.
 *
 * RATE-LIMIT TOLERANCE (audit BUG-3): the gateway aggressively 429s under rapid
 * fan-out navigation. `gotoLive()` retries on a 429-bearing navigation with
 * exponential backoff, and `@live` specs run on a SERIAL project (see
 * playwright.config.ts) so parallel workers don't trip the limiter.
 *
 * USAGE:
 *   import { installLiveAuth, gotoLive, APP_ROUTES } from "./live-helpers";
 *   test.beforeEach(async ({ page }) => { await installLiveAuth(page); });
 *   await gotoLive(page, "/dashboard");
 */

import { expect, request as pwRequest, type Page, type Route } from "@playwright/test";

// ── Backend base URL ──────────────────────────────────────────────────────────

/**
 * API_BASE — where the LIVE S9 gateway listens. Defaults to the local dev port
 * (8000) but is overridable via env so the same specs can run against a remote
 * dev stack. This is the DIRECT gateway URL (not the Next.js `/api` proxy) —
 * we hit dev-login server-to-server to mint the JWT before the browser loads.
 */
export const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8000";

// ── The decoded JWT claims we care about (for the user object) ──────────────────

interface DevLoginResponse {
  access_token: string;
}

/** Minimal claim subset we read out of the minted JWT to build the user object. */
interface JwtClaims {
  sub?: string;
  tenant_id?: string;
  oidc_sub?: string;
  exp?: number;
}

/**
 * decodeJwtClaims — read the (public, base64url) payload of a JWT WITHOUT
 * verifying the signature. We only need `sub`/`tenant_id`/`exp` to populate the
 * frontend's `user` object and to size the refresh `expires_in`. Verification is
 * the backend's job — these claims are not a trust boundary in the test harness.
 */
function decodeJwtClaims(token: string): JwtClaims {
  const payload = token.split(".")[1];
  if (!payload) return {};
  // base64url → base64, then decode. Node's Buffer handles padding tolerantly.
  const b64 = payload.replace(/-/g, "+").replace(/_/g, "/");
  try {
    return JSON.parse(Buffer.from(b64, "base64").toString("utf8")) as JwtClaims;
  } catch {
    return {};
  }
}

// ── Token minting ───────────────────────────────────────────────────────────────

/**
 * mintDevJwt — call the backend dev-login endpoint and return a REAL RS256 JWT.
 *
 * WHY a fresh Playwright APIRequestContext (not `page.request`): this runs in the
 * test process before any page navigation, server-to-server against the gateway.
 * It does not depend on browser cookies and is reusable across specs.
 *
 * Throws a descriptive error if dev-login is unavailable so a misconfigured stack
 * fails loudly at setup instead of cascading into confusing 401s mid-spec.
 */
export async function mintDevJwt(): Promise<string> {
  const ctx = await pwRequest.newContext();
  try {
    const res = await ctx.post(`${API_BASE}/v1/auth/dev-login`, {
      data: {},
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok()) {
      throw new Error(
        `dev-login failed (HTTP ${res.status()}). Is the live stack up at ${API_BASE}? ` +
          `Body: ${await res.text()}`,
      );
    }
    const body = (await res.json()) as DevLoginResponse;
    if (!body.access_token) {
      throw new Error(`dev-login returned no access_token: ${JSON.stringify(body)}`);
    }
    return body.access_token;
  } finally {
    await ctx.dispose();
  }
}

// ── Auth injection ───────────────────────────────────────────────────────────────

/**
 * installLiveAuth — mint a real JWT and wire the refresh-route seam.
 *
 * Returns the minted token so a spec can ALSO make direct authenticated backend
 * assertions (e.g. "hit /v1/alert-rules and confirm the rule we just created
 * persists"). The token is short-lived (~5 min on this deployment); specs that
 * run long can call `mintDevJwt()` again for a fresh one.
 */
export async function installLiveAuth(page: Page): Promise<string> {
  const token = await mintDevJwt();
  const claims = decodeJwtClaims(token);

  // The frontend computes refresh timing from `expires_in`. Derive it from the
  // JWT `exp` when present so the silent-refresh timer matches the real token's
  // lifetime; fall back to a safe 5 min if the claim is missing.
  const nowSec = Math.floor(Date.now() / 1000);
  const expiresIn = claims.exp && claims.exp > nowSec ? claims.exp - nowSec : 300;

  // Intercept ONLY the silent-refresh call. AuthContext fires this on mount; we
  // answer with the real token + a user object so the app authenticates. NB: the
  // glob matches both the bare path and any query string the client may append.
  await page.route("**/api/v1/auth/refresh", (route: Route) => {
    void route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: token,
        expires_in: expiresIn,
        user: {
          // Use the real subject/tenant from the JWT so any UI that echoes them
          // (e.g. tenant-scoped views) lines up with what the backend enforces.
          user_id: claims.sub ?? "dev-user",
          tenant_id: claims.tenant_id ?? "dev-tenant",
          email: "dev@worldview.local",
          name: "Dev User",
          avatar_url: null,
        },
      }),
    });
  });

  return token;
}

// ── Navigation with rate-limit tolerance ────────────────────────────────────────

/**
 * KNOWN_BACKEND_GAP_PATHS — gateway path fragments whose 404 is a SERVER gap
 * (route not yet shipped by S9), NOT a frontend bug. The smoke tolerates 404s on
 * these so it keeps guarding real frontend regressions. FLAGGED for a backend
 * agent — see the report. Trim this list as the backend ships each route.
 */
export const KNOWN_BACKEND_GAP_PATHS: readonly string[] = ["/api/v1/alert-rules"];

/** Console + network problems captured during a live navigation. */
export interface LivePageHealth {
  /** Uncaught page errors (JS exceptions) seen while on the route. */
  pageErrors: string[];
  /** console.error messages seen while on the route. */
  consoleErrors: string[];
  /** Non-2xx/3xx responses (excluding tolerated 429s) seen while on the route. */
  badResponses: Array<{ url: string; status: number }>;
}

/**
 * attachHealthListeners — start capturing errors/bad responses on a page.
 *
 * Returns a `health` object that fills up as events fire, plus a `detach()` to
 * stop listening. We deliberately TOLERATE 429 (rate limit, audit BUG-3) — a
 * burst of authenticated fan-out calls legitimately trips the dev limiter and is
 * not a frontend defect. Everything else 4xx/5xx is recorded.
 *
 * WHY filter out a few known-noisy sources: Sentry/analytics beacons and the
 * Next.js dev HMR socket are not product API calls; counting them would make the
 * smoke test flaky for reasons unrelated to the journeys under test.
 */
export function attachHealthListeners(page: Page): {
  health: LivePageHealth;
  detach: () => void;
} {
  const health: LivePageHealth = { pageErrors: [], consoleErrors: [], badResponses: [] };

  const onPageError = (err: Error) => health.pageErrors.push(err.message);
  const onConsole = (msg: { type: () => string; text: () => string }) => {
    if (msg.type() === "error") health.consoleErrors.push(msg.text());
  };
  const onResponse = (res: { url: () => string; status: () => number }) => {
    const url = res.url();
    const status = res.status();
    // Only watch our own gateway calls (the /api proxy). Ignore static assets,
    // HMR, Sentry, and 429s (tolerated rate-limit per the audit).
    if (!url.includes("/api/v1/")) return;
    if (status === 429) return;
    // KNOWN BACKEND GAP (flagged for a backend agent): the S9 gateway on this
    // deployment does NOT expose /v1/alert-rules — every method 404s and the
    // route is absent from the gateway OpenAPI. The frontend correctly calls the
    // documented route (the alerts page loads the rule count via useAlertRules),
    // so this 404 is a SERVER gap, not a frontend defect. We tolerate it here so
    // the smoke still guards real frontend regressions; the dedicated wizard spec
    // annotates the gap explicitly. Remove this exemption once S9 ships the route.
    if (status === 404 && KNOWN_BACKEND_GAP_PATHS.some((p) => url.includes(p))) return;
    if (status >= 400) health.badResponses.push({ url, status });
  };

  page.on("pageerror", onPageError);
  page.on("console", onConsole as never);
  page.on("response", onResponse as never);

  return {
    health,
    detach: () => {
      page.off("pageerror", onPageError);
      page.off("console", onConsole as never);
      page.off("response", onResponse as never);
    },
  };
}

/**
 * gotoLive — navigate to an in-app route with 429-aware retry.
 *
 * The gateway 429s under rapid navigation (audit BUG-3). When the navigation
 * itself returns 429 we back off and retry a few times. We wait for
 * `networkidle` so the page's fan-out calls settle before the caller asserts.
 */
export async function gotoLive(
  page: Page,
  path: string,
  opts: { retries?: number; timeout?: number } = {},
): Promise<void> {
  const retries = opts.retries ?? 3;
  // WHY a generous default goto timeout: against a `next dev` server (the local
  // live-run target), the FIRST visit to a route triggers on-demand compilation
  // that can take 20-40s for data-heavy pages (chat, instrument tabs). A
  // production build is far faster, but the harness must not flake on dev cold
  // starts — so we wait up to 60s for the document, then assert content.
  const gotoTimeout = opts.timeout ?? 60_000;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const resp = await page.goto(path, {
      waitUntil: "domcontentloaded",
      timeout: gotoTimeout,
    });
    // A 429 on the document navigation itself → back off and retry.
    if (resp && resp.status() === 429 && attempt < retries) {
      await page.waitForTimeout(2000 * (attempt + 1)); // 2s, 4s, 6s …
      continue;
    }
    // Let client-side fan-out calls settle. networkidle can be slow on data-rich
    // pages, so bound it and tolerate the timeout (assertions follow regardless).
    await page
      .waitForLoadState("networkidle", { timeout: 15_000 })
      .catch(() => {/* data-heavy page kept the network busy; fine */});
    return;
  }
}

/**
 * assertAuthenticated — fail fast if a live navigation bounced us to /login.
 *
 * The (app) layout redirects unauthenticated users to /login. If our refresh
 * seam worked, we should NEVER land there. This is the single most important
 * smoke assertion — it proves the live-auth harness itself is healthy.
 */
export async function assertAuthenticated(page: Page): Promise<void> {
  expect(page.url(), "live-auth seam failed — bounced to /login").not.toContain("/login");
}

// ── Route catalogue for the all-route smoke ──────────────────────────────────────

/**
 * APP_ROUTES — the key authenticated routes the all-route smoke must cover.
 *
 * Instrument tabs use AAPL (confirmed live-present with quotes + fundamentals).
 * The `?tab=` deep-links match the InstrumentDetail tab controller so each tab
 * actually mounts. We avoid routes known to depend on absent data (e.g. a KG
 * graph that may be empty) for the hard "must load" smoke; those get their own
 * soft-fail specs.
 */
export const APP_ROUTES: Array<{ label: string; path: string }> = [
  { label: "dashboard", path: "/dashboard" },
  { label: "screener", path: "/screener" },
  { label: "instrument · quote", path: "/instruments/AAPL?tab=quote" },
  { label: "instrument · financials", path: "/instruments/AAPL?tab=financials" },
  { label: "instrument · intelligence", path: "/instruments/AAPL?tab=intelligence" },
  { label: "portfolio", path: "/portfolio" },
  { label: "watchlists", path: "/watchlists" },
  { label: "alerts", path: "/alerts" },
  { label: "chat", path: "/chat" },
  { label: "news", path: "/news" },
];
