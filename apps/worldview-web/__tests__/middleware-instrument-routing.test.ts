/**
 * __tests__/middleware-instrument-routing.test.ts — instrument-URL canonicalisation tests
 *
 * WHY THIS EXISTS (PRD-0089 F2 step 9): the middleware enforces the
 * single-canonical-form rule for `/instruments/{ticker}` URLs:
 *   - lowercase → 301 to uppercase
 *   - leading `^` (index prefix) → 301 to stripped form
 *   - already-canonical (uppercase + no `^`) → pass through (NO redirect)
 *
 * These tests pin the canonicalisation logic and the regression cases that
 * matter to analysts:
 *   - Special-character tickers (BRK.B, BF.B, RDS.A) must NOT be redirected.
 *   - Index tickers (^GSPC) must be 301'd to the stripped form.
 *   - Lowercase typos (aapl) must be 301'd to uppercase.
 *   - Non-instrument paths must pass through to the CSP stage.
 *
 * SHAPE: we exercise both the exported pure function
 * `canonicaliseInstrumentPath` (deterministic, no network) and the full
 * `middleware()` entry point (asserts the 301 + Location header).
 *
 * WHY a separate file from middleware-csp.test.ts: keeps the CSP suite
 * focused on CSP regressions (BP-324/BP-325) and the routing suite focused
 * on URL canonicalisation. Failure attribution is cleaner when each
 * concern has its own file.
 */

import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";
import { middleware, canonicaliseInstrumentPath } from "../middleware";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeRequest(path: string): NextRequest {
  const url = `http://localhost:3001${path}`;
  return new NextRequest(url);
}

// ── canonicaliseInstrumentPath (pure unit) ────────────────────────────────────

describe("canonicaliseInstrumentPath", () => {
  // ── pass-through cases (return null) ──

  it("returns null for an already-canonical uppercase ticker", () => {
    expect(canonicaliseInstrumentPath("/instruments/AAPL")).toBeNull();
  });

  it("returns null for special-character tickers in uppercase (BRK.B / BF.B / RDS.A)", () => {
    // WHY these specific tickers: they are the production-data exemplars
    // for class-share / preferred-share tickers. A typo in the regex (e.g.
    // matching only [A-Z]) would silently route them through canonicalisation
    // and either drop the dot or redirect to a different path.
    expect(canonicaliseInstrumentPath("/instruments/BRK.B")).toBeNull();
    expect(canonicaliseInstrumentPath("/instruments/BF.B")).toBeNull();
    expect(canonicaliseInstrumentPath("/instruments/RDS.A")).toBeNull();
    expect(canonicaliseInstrumentPath("/instruments/BRK.A")).toBeNull();
  });

  it("returns null for non-instrument paths", () => {
    // WHY these: dashboard / screener / nested sub-paths must NOT trigger
    // any rewriting. The middleware's redirect branch is reserved for the
    // /instruments/{ticker} surface only.
    expect(canonicaliseInstrumentPath("/dashboard")).toBeNull();
    expect(canonicaliseInstrumentPath("/screener")).toBeNull();
    expect(canonicaliseInstrumentPath("/instruments")).toBeNull();
    expect(canonicaliseInstrumentPath("/instruments/")).toBeNull();
  });

  // ── lowercase → uppercase ──

  it("uppercases a lowercase ticker", () => {
    expect(canonicaliseInstrumentPath("/instruments/aapl")).toBe("/instruments/AAPL");
  });

  it("uppercases a mixed-case ticker", () => {
    expect(canonicaliseInstrumentPath("/instruments/MsFt")).toBe("/instruments/MSFT");
  });

  it("preserves a trailing sub-path while uppercasing the slug", () => {
    // WHY: future deep-links may target sub-resources (`/instruments/AAPL/news`).
    // The canonicaliser must not eat the trailing remainder.
    expect(canonicaliseInstrumentPath("/instruments/aapl/news")).toBe("/instruments/AAPL/news");
  });

  // ── index ticker (^ prefix) stripping ──

  it("strips a leading caret on an index ticker (^GSPC → GSPC)", () => {
    expect(canonicaliseInstrumentPath("/instruments/^GSPC")).toBe("/instruments/GSPC");
  });

  it("strips a leading caret on an already-uppercase index ticker", () => {
    // The decoded form is `^TNX`. After strip+upper it's `TNX`.
    expect(canonicaliseInstrumentPath("/instruments/^TNX")).toBe("/instruments/TNX");
  });

  it("decodes %5E (percent-encoded caret) and treats it as ^", () => {
    // Browsers commonly percent-encode `^` in URLs; analysts pasting a
    // share-link may carry the encoded form. Both must canonicalise the
    // same way.
    expect(canonicaliseInstrumentPath("/instruments/%5EGSPC")).toBe("/instruments/GSPC");
  });
});

// ── middleware() integration (asserts 301 + Location) ────────────────────────

describe("middleware — instrument URL canonicalisation", () => {
  it("301-redirects /instruments/aapl → /instruments/AAPL", () => {
    const response = middleware(makeRequest("/instruments/aapl"));
    expect(response.status).toBe(301);
    // WHY pathname check (not full URL equality): NextResponse.redirect emits
    // an absolute URL. We assert on the pathname so a future host change
    // doesn't break the test.
    const location = response.headers.get("location") ?? response.headers.get("Location") ?? "";
    expect(new URL(location).pathname).toBe("/instruments/AAPL");
  });

  it("301-redirects /instruments/^GSPC → /instruments/GSPC", () => {
    const response = middleware(makeRequest("/instruments/^GSPC"));
    expect(response.status).toBe(301);
    const location = response.headers.get("location") ?? response.headers.get("Location") ?? "";
    expect(new URL(location).pathname).toBe("/instruments/GSPC");
  });

  it("does NOT redirect /instruments/AAPL (already canonical)", () => {
    const response = middleware(makeRequest("/instruments/AAPL"));
    // WHY not-301 (not just 200): some Edge runtimes use 200 + headers,
    // others use a "next" sentinel. We assert the response was not a
    // redirect by checking the absence of a Location header AND a non-3xx
    // status. Either check alone could pass spuriously.
    expect(response.status).not.toBe(301);
    expect(response.status).not.toBe(302);
    expect(response.headers.get("location")).toBeNull();
  });

  it("does NOT redirect /instruments/BRK.B (special-char ticker, already canonical)", () => {
    // BP-465 regression: BRK.B is the canonical form (Berkshire Hathaway
    // Class B). The middleware MUST treat the dot as a normal character —
    // any inadvertent uppercase or strip of the dot would break the route.
    const response = middleware(makeRequest("/instruments/BRK.B"));
    expect(response.status).not.toBe(301);
    expect(response.headers.get("location")).toBeNull();
  });

  it("does NOT redirect /dashboard (non-instrument path)", () => {
    // WHY: the instrument-routing logic must be scoped to /instruments/*
    // and nothing else. A bug that 301'd every page would break the app
    // catastrophically. This is the canary.
    const response = middleware(makeRequest("/dashboard"));
    expect(response.status).not.toBe(301);
    expect(response.headers.get("location")).toBeNull();
  });

  it("preserves the query string on a canonicalising redirect", () => {
    // WHY: deep-links sometimes carry `?tab=intelligence` or similar.
    // Dropping the query on the 301 would surprise the user — the
    // post-redirect tab would reset to the default.
    const response = middleware(makeRequest("/instruments/aapl?tab=intelligence"));
    expect(response.status).toBe(301);
    const location = response.headers.get("location") ?? response.headers.get("Location") ?? "";
    const target = new URL(location);
    expect(target.pathname).toBe("/instruments/AAPL");
    expect(target.searchParams.get("tab")).toBe("intelligence");
  });

  // ── Legacy alias TODO sentinel ──
  // WHY this test exists: when the unauthenticated S9 alias-lookup endpoint
  // ships, the implementer should wire it into the middleware AND update
  // this test (replace the .skip with a real assertion that /instruments/FB
  // 301s to /instruments/META). Skipped tests show up in `pnpm test --run`
  // output as a clear reminder that the work item is pending.
  it.skip("legacy alias /instruments/FB → 301 /instruments/META (DEFERRED — needs S9 alias endpoint)", () => {
    // Pseudocode for the future implementer:
    //   const response = middleware(makeRequest("/instruments/FB"));
    //   expect(response.status).toBe(301);
    //   expect(new URL(response.headers.get("location")!).pathname)
    //     .toBe("/instruments/META");
  });
});
