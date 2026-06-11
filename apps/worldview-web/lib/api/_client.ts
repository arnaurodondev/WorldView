/**
 * lib/api/_client.ts — Shared HTTP client + error types for all gateway modules.
 *
 * WHY THIS EXISTS: Every domain module under `lib/api/*.ts` needs the same
 * underlying `apiFetch` wrapper (auth header injection, JSON parsing, error
 * handling, malformed-path guard). Centralising it here keeps the modules
 * small, consistent, and lets us add cross-cutting concerns (retry, tracing,
 * Sentry breadcrumbs) in one place rather than 16.
 *
 * SCOPE: Internal to `lib/api/*` and `lib/gateway.ts`. Components MUST NOT
 * import from this file directly — they go through `createGateway` (see
 * `lib/gateway.ts` shim).
 *
 * SECURITY: Token is passed per-call via FetchOptions.token, never stored.
 * The factory pattern (`createXApi(t)`) closes over the token so consumers
 * never see it after instantiation.
 */

// ── Base URL ──────────────────────────────────────────────────────────────

/**
 * All API calls use the /api prefix, which next.config.ts rewrites to S9.
 * No port numbers, no service names — always /api/v1/...
 */
export const BASE = "/api";

// ── Error type ────────────────────────────────────────────────────────────

/**
 * GatewayError — typed error thrown by apiFetch for non-2xx responses.
 *
 * WHY a custom error: GatewayError includes the status code so callers can
 * distinguish 401 (re-auth needed) from 503 (service down) from 0 (client
 * fail-fast on malformed paths). TanStack Query's `error` is `unknown`; the
 * `instanceof GatewayError` guard in components recovers the status.
 */
export class GatewayError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "GatewayError";
  }
}

/**
 * GatewayTimeoutError — thrown when a request exceeds its timeout budget.
 *
 * WHY a subclass (R4 deferred item, 2026-06-10): before this, apiFetch had NO
 * request timeout at all — a hung S9 connection (half-open TCP, stalled
 * upstream) left the underlying fetch pending on browser defaults (up to
 * ~300s in Chromium). TanStack Query would show an eternal loading state
 * with no error surface. Callers can now `instanceof GatewayTimeoutError`
 * to render "request timed out — retry?" distinctly from a 5xx.
 *
 * WHY status 408 (Request Timeout): the closest semantic HTTP status. The
 * server never actually sent 408 — the abort is client-side — but reusing
 * the GatewayError status channel keeps every existing `error.status`
 * consumer working without a new error taxonomy.
 */
export class GatewayTimeoutError extends GatewayError {
  constructor(
    /** The timeout budget that was exceeded, in milliseconds. */
    public readonly timeoutMs: number,
    path: string,
  ) {
    super(408, `Request to ${path} timed out after ${timeoutMs}ms`);
    this.name = "GatewayTimeoutError";
  }
}

/**
 * DEFAULT_TIMEOUT_MS — default per-request timeout budget (15s).
 *
 * WHY 15s: generous enough for the slowest legitimate gateway round-trips we
 * observe (cold screener queries, KG depth-2 graph expansion ≈ 5-8s) while
 * still bounding a hung connection to something a user will plausibly wait
 * out. Callers with known-slow endpoints can override per call via
 * `FetchOptions.timeoutMs`.
 *
 * NOTE — STREAMING IS EXEMPT BY CONSTRUCTION: SSE / chat streaming
 * (lib/api/chat.ts `streamChat`) deliberately uses a RAW `fetch()` and never
 * goes through apiFetch, so long-lived streams are NOT subject to this
 * timeout. If you add a new streaming endpoint, do the same — a stream that
 * flows through apiFetch would be killed mid-response after 15s.
 */
export const DEFAULT_TIMEOUT_MS = 15_000;

// ── Fetch options ─────────────────────────────────────────────────────────

export interface FetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  token?: string;
  /**
   * Per-call timeout override in milliseconds (default DEFAULT_TIMEOUT_MS).
   * Pass `0` to disable the timeout entirely (escape hatch for known
   * long-running non-streaming calls — use sparingly).
   */
  timeoutMs?: number;
}

// ── Malformed path guard ──────────────────────────────────────────────────

/**
 * PLAN-0052 platform-QA fix (2026-05-01): defensive guard against the
 * "frontend passes literal `undefined`" race-condition class. Without
 * this, components that call e.g. `getCompanyOverview(instrumentId)`
 * before `instrumentId` resolves would fire `/v1/companies/undefined/overview`
 * → backend asyncpg `DataError: invalid UUID 'undefined'` → 500. Live
 * platform observed ~80 such 500s/hour from a single mounted screener
 * row whose useQuery's `enabled` guard wasn't sufficient.
 *
 * The path-segment check is intentionally narrow: only fail-fast when
 * the URL contains "/undefined", "/null", or trailing-empty segments.
 * It does NOT inspect URL params (those have their own validation) or
 * the body. Throws `GatewayError(0, "...")` so the calling useQuery
 * surfaces a clean error state instead of a 500 propagating.
 */
function _detectMalformedPath(path: string): string | null {
  // Match a path segment whose entire value is the literal string
  // "undefined" or "null" — these are JavaScript stringification
  // artifacts, never legitimate UUIDs / tickers / IDs.
  if (/\/undefined(\/|\?|$)/.test(path)) return "undefined";
  if (/\/null(\/|\?|$)/.test(path)) return "null";
  // Trailing-empty segment: `/companies//overview` — the templated id
  // was empty string. Same race; same fail-fast.
  if (/\/\/(\?|$)|\/\/[a-z]/i.test(path)) return "empty-segment";
  return null;
}

// ── Core fetch wrapper ────────────────────────────────────────────────────

/**
 * apiFetch — wrapper around fetch() with:
 * - Authorization header injection
 * - JSON response parsing
 * - Error response handling (throws GatewayError for non-2xx)
 * - Malformed path fail-fast (undefined/null id race)
 *
 * WHY a single shared wrapper across all domain modules: any change here
 * (retry policy, tracing header, error logging) lands in every API call
 * automatically. Without it, 100+ domain methods would each need patching.
 */
export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  // Fail-fast on malformed paths from undefined/null id race conditions.
  const malformed = _detectMalformedPath(path);
  if (malformed) {
    throw new GatewayError(
      0,
      `Refusing to call malformed path (${malformed} in ${path}). ` +
        `Likely a useQuery enabled-guard race; check the call site.`,
    );
  }

  const { body, token, timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = options;

  const headers: HeadersInit = {
    "Content-Type": "application/json",
    ...(rest.headers as Record<string, string> | undefined),
  };

  // WHY token in Authorization header (not cookie):
  // The access token lives in React state (AuthContext).
  // We pass it as Bearer token per standard OAuth2 (PRD-0025 §8).
  if (token) {
    (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`;
  }

  // ── Timeout wiring (R4 deferred item, 2026-06-10) ──────────────────────
  // AbortSignal.timeout() aborts the fetch with a DOMException named
  // "TimeoutError" once the budget elapses. We must COMBINE it with any
  // caller-provided signal (e.g. knowledge-graph.ts passes an AbortSignal so
  // unmounted graph queries tear down their HTTP connection) — otherwise the
  // timeout would silently REPLACE caller cancellation.
  // WHY AbortSignal.any: the only composition primitive that fires on
  // whichever signal aborts first. Available in all evergreen browsers +
  // Node 20.3+ (our toolchain floor); the typeof guard keeps older test
  // environments working by falling back to the caller signal alone.
  let signal: AbortSignal | undefined = rest.signal ?? undefined;
  if (timeoutMs > 0) {
    const timeoutSignal = AbortSignal.timeout(timeoutMs);
    signal =
      signal && typeof AbortSignal.any === "function"
        ? AbortSignal.any([signal, timeoutSignal])
        : signal ?? timeoutSignal;
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...rest,
      signal,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    // Map the AbortSignal.timeout() DOMException to our typed error so
    // callers (and TanStack Query error states) can distinguish "the request
    // timed out" from "the user/component cancelled it" (plain AbortError,
    // re-thrown unchanged so TanStack treats it as a cancellation).
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new GatewayTimeoutError(timeoutMs, path);
    }
    throw err;
  }

  if (!response.ok) {
    // Try to get error detail from JSON response body
    let detail = response.statusText;
    try {
      const errorBody = (await response.json()) as { detail?: string };
      detail = errorBody.detail ?? detail;
    } catch {
      // Response body not JSON — use statusText
    }
    throw new GatewayError(response.status, detail);
  }

  // Handle no-body responses: 204 No Content and 202 Accepted (async job queued).
  // WHY include 202: POST endpoints that queue async jobs (e.g., narrative generation)
  // return 202 with no body. Attempting response.json() on a null/empty body throws
  // a SyntaxError. We return undefined (cast to T) because the caller (e.g.,
  // useTriggerNarrativeGeneration) types the result as void.
  if (response.status === 204 || response.status === 202) {
    return undefined as unknown as T;
  }

  return response.json() as Promise<T>;
}

// ── Canonical staleTime constants (FR-8.4 / W0) ───────────────────────────────

/**
 * DEFAULT_STALE — single source of truth for per-domain staleTime values.
 *
 * WHY THIS EXISTS (HIGH-018, FR-8.4):
 * Before this constant, staleTime was specified inline at each useQuery call site,
 * resulting in the same endpoint being hit with different stale windows by different
 * components. For example, TopNews was fetched with staleTime: 30s in one widget
 * and staleTime: 60s in another — the shorter window "won" on any page that mounted
 * both, causing unnecessary refetches.
 *
 * This map is the canonical definition. API methods (getTopNews, getFundamentals,
 * etc.) should use `DEFAULT_STALE.news` as their default staleTime so every consumer
 * gets a consistent cache policy without having to know the domain rules.
 *
 * WHY `as const`: makes the values literal number types (not just `number`), so
 * TypeScript can catch accidental mutations and callers get auto-complete in
 * object destructuring.
 *
 * USAGE:
 *   import { DEFAULT_STALE } from "@/lib/api/_client";
 *   useQuery({ ..., staleTime: DEFAULT_STALE.news });
 *
 * Values (in milliseconds):
 *   news          — 5 min: news articles update frequently but not per-second
 *   fundamentals  — 1 hr:  quarterly data; rarely changes intra-day
 *   entityGraph   — 1 min: KG enrichment runs continuously; relatively fresh
 *   quotes        — 15 sec: matches S3 Valkey quote cache TTL
 *   screener      — 30 sec: filter results shift as prices move
 *   screenerFields — 6 hr: field definitions almost never change intra-day
 *   portfolio     — 1 min: holdings + valuation updated on every transaction
 *   alerts        — 15 sec: alert status must be nearly real-time
 */
export const DEFAULT_STALE = {
  news: 300_000,           // 5 minutes
  fundamentals: 3_600_000, // 1 hour
  entityGraph: 60_000,     // 1 minute
  quotes: 15_000,          // 15 seconds
  screener: 30_000,        // 30 seconds
  screenerFields: 21_600_000, // 6 hours
  portfolio: 60_000,       // 1 minute
  alerts: 15_000,          // 15 seconds
} as const;
