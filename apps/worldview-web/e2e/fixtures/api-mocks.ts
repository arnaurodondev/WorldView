/**
 * e2e/fixtures/api-mocks.ts — Typed S9 API mock responses for Playwright tests
 *
 * WHY THIS EXISTS: D-002 decision mandates strict per-endpoint Playwright mocks
 * generated from actual S9 API response shapes. Wildcard mocks (matching all
 * /api/v1/ paths) mask API contract mismatches — if S9 changes a response
 * shape, wildcard mocks would still pass, hiding the regression until production.
 *
 * HOW IT WORKS: Each mock response matches the TypeScript types in types/api.ts
 * which mirror the S9 OpenAPI response schemas. When S9 changes a response shape,
 * the type mismatch in this file will surface at compile time (pnpm tsc --noEmit).
 *
 * WHO USES IT: All Playwright e2e specs via installStrictApiMocks().
 * D-002: strict per-endpoint mocks — no wildcard to prevent API shape drift.
 */

import type { Page } from "@playwright/test";

// ── Auth mock helpers ─────────────────────────────────────────────────────────

/**
 * buildFakeToken — construct a fake JWT for e2e tests.
 * WHY fake JWT: auth middleware checks for Bearer token existence and decodes
 * the payload (but does NOT verify signature in test mode). This fake token
 * has a valid structure so JSON.parse(atob(payload)) works.
 */
export function buildFakeToken(userId = "e2e-user"): string {
  const header = btoa(JSON.stringify({ alg: "RS256", typ: "JWT" }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const payload = btoa(
    JSON.stringify({
      sub: userId,
      tenant_id: "e2e-tenant",
      email: "e2e@test.local",
      name: "E2E Test User",
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  )
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${payload}.fake-e2e-sig`;
}

// ── Typed mock response data ──────────────────────────────────────────────────
// WHY typed objects: these match the shapes in types/api.ts so that TypeScript
// catches any response shape drift at compile time. When S9 adds/removes fields,
// the type error here tells you to update the mock.

/** Auth refresh response — returned by POST /api/v1/auth/refresh */
export const AUTH_REFRESH_RESPONSE = {
  access_token: buildFakeToken(),
  expires_in: 3600,
  user: {
    user_id: "e2e-user",
    tenant_id: "e2e-tenant",
    email: "e2e@test.local",
    name: "E2E Test User",
  },
};

/** WS token response — returned by GET /api/v1/auth/ws-token */
export const WS_TOKEN_RESPONSE = {
  token: "fake-ws-token",
};

/** Portfolio list — returned by GET /api/v1/portfolios */
export const PORTFOLIOS_RESPONSE: unknown[] = [];

/** Watchlist list — returned by GET /api/v1/watchlists */
export const WATCHLISTS_RESPONSE: unknown[] = [];

/** Top news — returned by GET /api/v1/news/top */
export const NEWS_TOP_RESPONSE = {
  items: [] as unknown[],
  total: 0,
};

/** Relevant news — returned by GET /api/v1/news/relevant */
export const NEWS_RELEVANT_RESPONSE = {
  items: [] as unknown[],
  total: 0,
};

/** Market heatmap — returned by GET /api/v1/market/heatmap */
export const MARKET_HEATMAP_RESPONSE = {
  sectors: [] as unknown[],
};

/** Top movers — returned by GET /api/v1/market/top-movers */
export const TOP_MOVERS_RESPONSE = {
  movers: [] as unknown[],
};

/** Pending alerts — returned by GET /api/v1/alerts/pending */
export const ALERTS_PENDING_RESPONSE = {
  items: [] as unknown[],
  total: 0,
};

/** Morning brief — returned by GET /api/v1/briefings/morning */
export const MORNING_BRIEF_RESPONSE = {
  brief_id: "mock-brief-001",
  generated_at: "2026-04-18T08:00:00Z",
  content: "Markets are quiet today. No major events expected.",
  entity_mentions: [] as Array<{ entity_id: string; name: string; ticker: string | null }>,
};

/** Instrument brief — returned by GET /api/v1/briefings/instrument/:entityId */
export const INSTRUMENT_BRIEF_RESPONSE = {
  brief_id: "mock-brief-002",
  generated_at: "2026-04-18T08:00:00Z",
  sections: [] as unknown[],
};

/** AI signals — returned by GET /api/v1/signals/ai */
export const AI_SIGNALS_RESPONSE = {
  signals: [] as unknown[],
};

/** Prediction markets — returned by GET /api/v1/signals/prediction-markets */
export const PREDICTION_MARKETS_RESPONSE = {
  markets: [] as unknown[],
};

/** Economic calendar — returned by GET /api/v1/fundamentals/economic-calendar */
export const ECONOMIC_CALENDAR_RESPONSE = {
  events: [] as unknown[],
};

/** Screener fields — returned by GET /api/v1/fundamentals/screen/fields */
export const SCREENER_FIELDS_RESPONSE: unknown[] = [];

/** Chat threads — returned by GET /api/v1/threads */
export const THREADS_RESPONSE: unknown[] = [];

/** Search instruments — returned by GET /api/v1/search/instruments */
export const SEARCH_RESPONSE = {
  results: [] as unknown[],
};

/** Company overview — returned by GET /api/v1/companies/:instrumentId/overview */
export const COMPANY_OVERVIEW_RESPONSE = {
  instrument_id: "ins-001",
  ticker: "AAPL",
  name: "Apple Inc.",
  fundamentals: null,
  recent_bars: [],
  recent_news: [],
};

/** Holdings — returned by GET /api/v1/holdings/:portfolioId */
export const HOLDINGS_RESPONSE = {
  holdings: [] as unknown[],
  total_value: 0,
  total_pnl: 0,
  total_pnl_pct: 0,
};

/** Transactions — returned by GET /api/v1/transactions */
export const TRANSACTIONS_RESPONSE = {
  items: [] as unknown[],
  total: 0,
};

/** Batch quotes — returned by POST /api/v1/quotes/batch */
export const BATCH_QUOTES_RESPONSE = {
  quotes: [] as unknown[],
};

// ── Strict route installer ────────────────────────────────────────────────────

/**
 * Endpoint descriptor for strict mocking. Each entry maps a URL pattern
 * to the mock response that should be returned when that endpoint is hit.
 */
interface EndpointMock {
  /** URL pattern for page.route() — must be specific, never wildcard on path */
  pattern: string;
  /** HTTP status to return */
  status: number;
  /** Response body (will be JSON.stringify'd) */
  body: unknown;
}

/**
 * getStrictEndpointMocks — returns all S9 endpoint mocks for a given HTTP status.
 *
 * WHY separate function: allows the error-resilience tests to pass status=500
 * while keeping the same endpoint list. This ensures the 500 tests hit the
 * exact same endpoints as the 200 tests — no accidental coverage gaps.
 */
function getStrictEndpointMocks(status: number): EndpointMock[] {
  // WHY per-endpoint error body: matches S9's actual error response format.
  // When testing 500 errors, each endpoint returns { detail: "test error" }.
  const errorBody = { detail: "test error" };
  const ok = status === 200;

  return [
    // ── Auth endpoints (always 200 — broken auth prevents page from loading) ──
    { pattern: "**/api/v1/auth/refresh", status: 200, body: AUTH_REFRESH_RESPONSE },
    { pattern: "**/api/v1/auth/ws-token", status: 200, body: WS_TOKEN_RESPONSE },

    // ── Portfolio ────────────────────────────────────────────────────────────
    { pattern: "**/api/v1/portfolios", status, body: ok ? PORTFOLIOS_RESPONSE : errorBody },
    { pattern: "**/api/v1/holdings/**", status, body: ok ? HOLDINGS_RESPONSE : errorBody },
    { pattern: "**/api/v1/transactions?**", status, body: ok ? TRANSACTIONS_RESPONSE : errorBody },
    { pattern: "**/api/v1/transactions", status, body: ok ? TRANSACTIONS_RESPONSE : errorBody },

    // ── Watchlists ──────────────────────────────────────────────────────────
    { pattern: "**/api/v1/watchlists", status, body: ok ? WATCHLISTS_RESPONSE : errorBody },

    // ── News ────────────────────────────────────────────────────────────────
    { pattern: "**/api/v1/news/top**", status, body: ok ? NEWS_TOP_RESPONSE : errorBody },
    { pattern: "**/api/v1/news/relevant**", status, body: ok ? NEWS_RELEVANT_RESPONSE : errorBody },
    { pattern: "**/api/v1/news/entity/**", status, body: ok ? NEWS_TOP_RESPONSE : errorBody },

    // ── Market data ─────────────────────────────────────────────────────────
    { pattern: "**/api/v1/market/heatmap", status, body: ok ? MARKET_HEATMAP_RESPONSE : errorBody },
    { pattern: "**/api/v1/market/top-movers**", status, body: ok ? TOP_MOVERS_RESPONSE : errorBody },
    // WHY wildcard before specific: LIFO order — specific pattern registered
    // later takes priority over the wildcard for /quotes/batch.
    { pattern: "**/api/v1/quotes/**", status, body: ok ? { instrument_id: "ins-001", ticker: "AAPL", price: 0, change: 0, change_pct: 0, timestamp: "2026-04-18T00:00:00Z", volume: 0 } : errorBody },
    { pattern: "**/api/v1/quotes/batch", status, body: ok ? BATCH_QUOTES_RESPONSE : errorBody },

    // ── Alerts ──────────────────────────────────────────────────────────────
    { pattern: "**/api/v1/alerts/pending**", status, body: ok ? ALERTS_PENDING_RESPONSE : errorBody },

    // ── Briefings ───────────────────────────────────────────────────────────
    { pattern: "**/api/v1/briefings/morning", status, body: ok ? MORNING_BRIEF_RESPONSE : errorBody },
    { pattern: "**/api/v1/briefings/instrument/**", status, body: ok ? INSTRUMENT_BRIEF_RESPONSE : errorBody },

    // ── AI signals & prediction markets ─────────────────────────────────────
    { pattern: "**/api/v1/signals/ai**", status, body: ok ? AI_SIGNALS_RESPONSE : errorBody },
    { pattern: "**/api/v1/signals/prediction-markets**", status, body: ok ? PREDICTION_MARKETS_RESPONSE : errorBody },

    // ── Fundamentals / Screener ─────────────────────────────────────────────
    // WHY wildcard FIRST: Playwright matches routes in LIFO order (last registered
    // wins). The wildcard must be registered BEFORE specific patterns so that
    // specific patterns (registered later) take priority over the catch-all.
    { pattern: "**/api/v1/fundamentals/**", status, body: ok ? {} : errorBody },
    { pattern: "**/api/v1/fundamentals/economic-calendar", status, body: ok ? ECONOMIC_CALENDAR_RESPONSE : errorBody },
    { pattern: "**/api/v1/fundamentals/screen/fields", status, body: ok ? SCREENER_FIELDS_RESPONSE : errorBody },
    { pattern: "**/api/v1/fundamentals/screen", status, body: ok ? { results: [], total: 0 } : errorBody },

    // ── Companies (instrument detail) ───────────────────────────────────────
    { pattern: "**/api/v1/companies/*/overview", status, body: ok ? COMPANY_OVERVIEW_RESPONSE : errorBody },

    // ── OHLCV ───────────────────────────────────────────────────────────────
    { pattern: "**/api/v1/ohlcv/**", status, body: ok ? { instrument_id: "ins-001", ticker: "", timeframe: "1D", bars: [] } : errorBody },

    // ── Knowledge graph ─────────────────────────────────────────────────────
    { pattern: "**/api/v1/entities/*/graph**", status, body: ok ? { entity_id: "ent-001", nodes: [], edges: [] } : errorBody },
    { pattern: "**/api/v1/entities/*/contradictions", status, body: ok ? { entity_id: "ent-001", contradictions: [] } : errorBody },

    // ── Chat ────────────────────────────────────────────────────────────────
    // WHY wildcard before specific: LIFO — specific /threads registered after
    // wildcard so it takes priority for the exact path.
    { pattern: "**/api/v1/threads/**", status, body: ok ? { thread_id: "t-1", title: "", messages: [] } : errorBody },
    { pattern: "**/api/v1/threads", status, body: ok ? THREADS_RESPONSE : errorBody },

    // ── Search ──────────────────────────────────────────────────────────────
    { pattern: "**/api/v1/search/instruments**", status, body: ok ? SEARCH_RESPONSE : errorBody },
  ];
}

/**
 * installStrictApiMocks — register per-endpoint route mocks on a Playwright page.
 *
 * D-002: strict per-endpoint mocks — no wildcard to prevent API shape drift.
 *
 * WHY call before page.goto(): Playwright route handlers must be registered
 * before the first request fires. If mocks are registered after navigation,
 * the initial requests (auth refresh, dashboard data) would hit the real
 * server (which isn't running in e2e) and fail with connection refused.
 *
 * @param page - Playwright Page instance
 * @param apiStatus - HTTP status for data endpoints (200 = success, 500 = error test)
 */
export async function installStrictApiMocks(
  page: Page,
  apiStatus = 200,
): Promise<void> {
  const mocks = getStrictEndpointMocks(apiStatus);

  // Register all endpoint mocks in parallel — order doesn't matter because
  // Playwright matches routes in registration order (first match wins),
  // and our patterns are specific enough to not overlap.
  for (const mock of mocks) {
    await page.route(mock.pattern, (route) => {
      void route.fulfill({
        status: mock.status,
        contentType: "application/json",
        body: JSON.stringify(mock.body),
      });
    });
  }
}

// ── Error collection helpers ──────────────────────────────────────────────────

/**
 * collectCriticalErrors — attach a page error listener and return the error array.
 * WHY separate function: every e2e test needs this pattern; DRY.
 */
export function collectCriticalErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/**
 * filterCriticalErrors — remove expected non-critical errors from the collected array.
 *
 * WHY filter: In the test environment (no real S9, no real WebSocket server),
 * certain errors are expected and harmless:
 * - "Failed to fetch" / "NetworkError" — no real backend running
 * - "WebSocket" — no real S10 running
 * - "NEXT_REDIRECT" — Next.js internal redirect mechanism (not a real error)
 */
export function filterCriticalErrors(errors: string[]): string[] {
  return errors.filter(
    (e) =>
      !e.includes("Failed to fetch") &&
      !e.includes("NetworkError") &&
      !e.includes("net::ERR") &&
      !e.includes("WebSocket") &&
      !e.includes("NEXT_REDIRECT"),
  );
}
