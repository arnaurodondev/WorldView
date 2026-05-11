/**
 * lib/sentry/strip-pii.ts — Sentry PII scrubbing utilities
 *
 * WHY THIS EXISTS: Sentry captures stack traces + HTTP request context when
 * an unhandled exception fires. Without scrubbing, that context includes:
 *   - Authorization and X-Internal-JWT request headers (auth tokens)
 *   - Session cookies
 *   - Query strings (tickers, search terms, entity UUIDs — Sam's research footprint)
 *   - URL paths revealing which instrument Sam was viewing (e.g. /instruments/AAPL/)
 *   - Fetch breadcrumb URLs (Sentry's automatic network breadcrumbs are very noisy)
 *   - User email in plaintext
 *
 * WHY EXPORTED (not inlined in sentry.*.config.ts): tests can import these
 * functions directly and verify PII removal without initialising the Sentry SDK
 * or mocking anything at the module boundary.
 *
 * PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1
 */

/**
 * Matches URL path segments that identify a specific instrument, entity, or news item.
 * Examples that get redacted:
 *   /instruments/AAPL/ownership  → /instruments/<redacted>/ownership
 *   /entities/01HX.../graph      → /entities/<redacted>/graph
 *   /news/01HX.../detail         → /news/<redacted>/detail
 *
 * WHY GLOBAL FLAG 'g': the regex is reused across multiple calls via replace()
 * which resets lastIndex each time, so the 'g' flag is safe here.
 */
const SLUG_RE =
  /\/(instruments|entities|news)\/([A-Z]{1,10}|[0-9a-f]{8}-[0-9a-f-]{27}|[0-9A-HJKMNP-TV-Z]{26})(\/|$)/g;

/**
 * Matches extra-data keys that could contain auth material or secrets.
 * Covers common naming conventions (snake_case, camelCase, kebab-case).
 */
const SECRET_KEY_RE = /(?:token|secret|password|api[-_]?key|jwt)/i;

/**
 * Replace sensitive slug segments in a URL string with the literal "<redacted>".
 *
 * WHY we keep the route prefix: /instruments/ tells us the error class without
 * revealing Sam's specific research target. Stack traces stay useful.
 */
function redactSlugs(url: string): string {
  // Using a replacement function so we can preserve the trailing slash/end.
  return url.replace(SLUG_RE, (_, section, _slug, trailing) => `/${section}/<redacted>${trailing}`);
}

/**
 * Shape of the Sentry event fields we care about for PII stripping.
 * Defined here so the utility has no hard dependency on @sentry/types —
 * tests can import this file without the SDK being present.
 */
export interface SentryEventShape {
  request?: {
    cookies?: unknown;
    query_string?: unknown;
    headers?: Record<string, unknown>;
    url?: string;
    data?: unknown;
  };
  extra?: Record<string, unknown>;
  breadcrumbs?: {
    values?: Array<{
      data?: Record<string, unknown>;
    }>;
  };
  user?: {
    email?: string;
    [key: string]: unknown;
  };
}

/**
 * Synchronous portion of the PII strip — removes/rewrites all fields
 * except user.email (which requires async hashing handled separately).
 *
 * Mutates the event in-place (Sentry's beforeSend contract allows this).
 */
export function stripPiiSync(event: SentryEventShape): SentryEventShape {
  // ── request block ──────────────────────────────────────────────────────
  if (event.request) {
    // Cookies carry session identifiers — drop entirely
    delete event.request.cookies;

    // Query strings carry tickers, search queries, entity IDs
    // Sam's research footprint is in these (e.g. ?q=AAPL&sector=tech)
    delete event.request.query_string;

    // Drop raw body — never needed for error diagnosis; high PII risk
    delete event.request.data;

    // Strip auth headers — both lower and title case (HTTP normalisation varies)
    if (event.request.headers) {
      delete event.request.headers["authorization"];
      delete event.request.headers["Authorization"];
      delete event.request.headers["x-internal-jwt"];
      delete event.request.headers["X-Internal-JWT"];
    }

    // Rewrite URL slugs so Sentry sees the route class, not the identifier
    if (typeof event.request.url === "string") {
      event.request.url = redactSlugs(event.request.url);
    }
  }

  // ── extra keys — drop anything that looks like a secret ─────────────────
  if (event.extra) {
    for (const key of Object.keys(event.extra)) {
      if (SECRET_KEY_RE.test(key)) {
        delete event.extra[key];
      }
    }
  }

  // ── breadcrumbs — Sentry auto-captures fetch/XHR URLs ──────────────────
  // These are the noisiest PII source: every API call Sam makes is recorded
  // (e.g. "GET /v1/instruments/AAPL/ownership"). Rewrite slugs in each URL.
  const crumbs = event.breadcrumbs?.values;
  if (crumbs) {
    for (const crumb of crumbs) {
      if (crumb.data && typeof crumb.data.url === "string") {
        crumb.data.url = redactSlugs(crumb.data.url);
      }
    }
  }

  return event;
}

/**
 * Hash a string with SHA-256 using the Web Crypto API.
 *
 * Works in:
 *   - Browser (globalThis.crypto.subtle — W3C Web Crypto)
 *   - Node 18+ (globalThis.crypto.subtle — same interface, Node built-in)
 *   - Vitest / jsdom 25 (globalThis.crypto.subtle available)
 *
 * WHY async: SubtleCrypto.digest() is inherently async by spec. Sentry's
 * beforeSend accepts Promise<Event | null> since SDK v8, so this is fine.
 */
async function sha256Hex(text: string): Promise<string> {
  const encoded = new TextEncoder().encode(text);
  const buf = await globalThis.crypto.subtle.digest("SHA-256", encoded);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Full async PII strip — used as Sentry's `beforeSend` callback.
 *
 * Order: sync scrub first (cheap), then async email hash.
 * Returns null only when the event should be dropped entirely (currently unused,
 * but the per-fingerprint rate limiter in the Python backend uses this pattern).
 */
export async function stripPii(
  event: SentryEventShape,
): Promise<SentryEventShape | null> {
  // Run the cheap synchronous scrub first
  stripPiiSync(event);

  // Hash user.email — replaces plaintext with hex SHA-256
  // Sentry can still cluster events by user without seeing the address.
  if (event.user?.email && event.user.email.length > 0) {
    event.user.email = await sha256Hex(event.user.email);
  }

  return event;
}
