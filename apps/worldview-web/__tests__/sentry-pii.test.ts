/**
 * __tests__/sentry-pii.test.ts — PII guard unit tests
 *
 * WHY THESE TESTS:
 * The stripPii / stripPiiSync functions are the privacy boundary between
 * worldview's users and Sentry (a third-party SaaS). If they regress, PII
 * (auth headers, tickers in URLs, user email) leaks to Sentry.
 *
 * WHY IMPORT FROM lib/sentry/strip-pii (not from sentry.*.config.ts):
 * The config files call Sentry.init() on import, which would require a real
 * DSN or extensive mocking. The strip functions are pure utilities exported
 * from a separate module — no Sentry SDK involvement needed for testing.
 *
 * PLAN-0065 T-D-01, PRD-0034 §3 FR-T3-1
 */

import { describe, it, expect } from "vitest";
import {
  stripPii,
  stripPiiSync,
  type SentryEventShape,
} from "@/lib/sentry/strip-pii";

// ─── Helper: build a minimal event with only the fields we want to test ──────

function makeEvent(overrides: Partial<SentryEventShape> = {}): SentryEventShape {
  return {
    request: {
      url: "https://app.worldview.io/v1/portfolio",
      headers: {},
      cookies: undefined,
      query_string: undefined,
    },
    ...overrides,
  };
}

// ─── stripPiiSync (synchronous portion) ──────────────────────────────────────

describe("stripPiiSync — authorization header", () => {
  it("removes authorization header (lower-case)", () => {
    // Verify the client-side path: browsers send 'authorization' (all-lowercase)
    // per the Fetch spec; Sentry captures it verbatim.
    const event = makeEvent({
      request: {
        url: "https://app.worldview.io/api/v1/portfolios",
        headers: {
          authorization: "Bearer eyJhbGciOiJSUzI1NiJ9.test",
          "content-type": "application/json",
        },
      },
    });

    stripPiiSync(event);

    // Auth header must be gone
    expect(event.request?.headers?.["authorization"]).toBeUndefined();
    // Non-auth headers must survive
    expect(event.request?.headers?.["content-type"]).toBe("application/json");
  });

  it("removes Authorization header (title-case)", () => {
    // Some HTTP clients send Title-Case headers; strip both forms.
    const event = makeEvent({
      request: {
        url: "https://app.worldview.io/api/v1/portfolios",
        headers: { Authorization: "Bearer tok" },
      },
    });
    stripPiiSync(event);
    expect(event.request?.headers?.["Authorization"]).toBeUndefined();
  });
});

describe("stripPiiSync — x-internal-jwt header (server-side path)", () => {
  it("removes x-internal-jwt header", () => {
    // The X-Internal-JWT header is added by S9 for backend service auth.
    // If a server-side Sentry event captured this header, it would leak
    // the signed JWT used for inter-service communication.
    const event = makeEvent({
      request: {
        url: "https://app.worldview.io/api/v1/news",
        headers: {
          "x-internal-jwt": "eyJhbGciOiJSUzI1NiJ9.service-token",
          accept: "application/json",
        },
      },
    });

    stripPiiSync(event);

    // JWT header removed
    expect(event.request?.headers?.["x-internal-jwt"]).toBeUndefined();
    // Other headers intact
    expect(event.request?.headers?.["accept"]).toBe("application/json");
  });

  it("removes X-Internal-JWT header (title-case)", () => {
    const event = makeEvent({
      request: {
        url: "https://app.worldview.io/api/v1/news",
        headers: { "X-Internal-JWT": "tok" },
      },
    });
    stripPiiSync(event);
    expect(event.request?.headers?.["X-Internal-JWT"]).toBeUndefined();
  });
});

describe("stripPiiSync — query_string", () => {
  it("removes query_string entirely", () => {
    // Query strings contain Sam's research footprint (e.g. ?q=AAPL&exchange=NYSE).
    // Sentry captures query_string as a separate field on the request object.
    const event = makeEvent({
      request: {
        url: "https://app.worldview.io/screener",
        headers: {},
        query_string: "q=AAPL&sector=technology&exchange=NYSE",
      },
    });

    stripPiiSync(event);

    expect(event.request?.query_string).toBeUndefined();
  });
});

describe("stripPiiSync — cookies", () => {
  it("removes cookies entirely", () => {
    const event = makeEvent({
      request: {
        url: "https://app.worldview.io/dashboard",
        headers: {},
        cookies: { session: "abc123", remember_me: "xyz" },
      },
    });

    stripPiiSync(event);

    expect(event.request?.cookies).toBeUndefined();
  });
});

describe("stripPiiSync — URL slug redaction", () => {
  it("redacts instrument ticker slug", () => {
    // /instruments/AAPL/ownership → /instruments/<redacted>/ownership
    // Preserves the route class (instruments) without the specific ticker.
    const event = makeEvent({
      request: { url: "https://app.worldview.io/instruments/AAPL/ownership" },
    });

    stripPiiSync(event);

    expect(event.request?.url).toBe(
      "https://app.worldview.io/instruments/<redacted>/ownership",
    );
  });

  it("redacts entity UUID slug in URL", () => {
    const entityId = "01HXZZZZZZZZZZZZZZZZZZZZZZ"; // 26-char valid ULID (charset: [0-9A-HJKMNP-TV-Z], no I/L/O/U)
    const event = makeEvent({
      request: { url: `https://app.worldview.io/entities/${entityId}/graph` },
    });

    stripPiiSync(event);

    // The slug is replaced but the surrounding path segments remain
    expect(event.request?.url).toContain("<redacted>");
    expect(event.request?.url).not.toContain(entityId);
  });

  it("redacts instrument ticker in breadcrumb fetch URLs", () => {
    // Sentry auto-captures fetch() calls as breadcrumbs — these include the
    // full URL which reveals which instrument Sam was looking at.
    const event = makeEvent({
      breadcrumbs: {
        values: [
          {
            data: {
              url: "https://app.worldview.io/api/v1/instruments/NVDA/ohlcv",
              method: "GET",
            },
          },
        ],
      },
    });

    stripPiiSync(event);

    expect(event.breadcrumbs?.values?.[0]?.data?.url).toBe(
      "https://app.worldview.io/api/v1/instruments/<redacted>/ohlcv",
    );
  });
});

describe("stripPiiSync — extra keys", () => {
  it("drops extra keys matching the secret key pattern", () => {
    const event = makeEvent({
      extra: {
        jwt_token: "eyJ...",
        api_key: "sk-live-xxx",
        debug_info: "some safe value",
        user_password: "hunter2",
      },
    });

    stripPiiSync(event);

    // Secret-looking keys removed
    expect(event.extra?.jwt_token).toBeUndefined();
    expect(event.extra?.api_key).toBeUndefined();
    expect(event.extra?.user_password).toBeUndefined();
    // Non-secret keys survive
    expect(event.extra?.debug_info).toBe("some safe value");
  });
});

// ─── stripPii (async — adds email hashing on top of sync strip) ──────────────

describe("stripPii — user.email hashing", () => {
  it("replaces user.email with its hex SHA-256 digest", async () => {
    // Email is replaced with a one-way hash. Sentry can still cluster events
    // by user without seeing the plaintext address. The hash is deterministic
    // so two events from the same user produce the same Sentry user identity.
    const event = makeEvent({ user: { email: "sam@worldview.io" } });

    const result = await stripPii(event);

    // Must no longer be the plaintext address
    expect(result?.user?.email).not.toBe("sam@worldview.io");
    // Must be a 64-character hex SHA-256 digest
    expect(result?.user?.email).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is deterministic — same email always produces same hash", async () => {
    const eventA = makeEvent({ user: { email: "test@example.com" } });
    const eventB = makeEvent({ user: { email: "test@example.com" } });

    const [a, b] = await Promise.all([stripPii(eventA), stripPii(eventB)]);

    // Deterministic hash: useful for Sentry's user-clustering feature
    expect(a?.user?.email).toBe(b?.user?.email);
  });

  it("leaves events without user.email untouched", async () => {
    const event = makeEvent({ user: { id: "u_01HXTEST" } });

    const result = await stripPii(event);

    // No email field → no modification
    expect(result?.user?.email).toBeUndefined();
    // Other user fields preserved
    expect(result?.user?.id).toBe("u_01HXTEST");
  });
});
