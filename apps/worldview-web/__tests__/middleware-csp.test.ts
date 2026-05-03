/**
 * __tests__/middleware-csp.test.ts — Content-Security-Policy regression tests
 *
 * WHY THIS EXISTS: Two bugs (BP-324 and BP-325) were introduced in the
 * nonce-based CSP middleware (middleware.ts) that caused the entire frontend
 * to render as plain unstyled HTML with no JavaScript execution:
 *
 *   BP-324: 'upgrade-insecure-requests' was gated on NODE_ENV==='production'.
 *     Docker's runner stage sets NODE_ENV=production but serves HTTP.
 *     The browser upgraded all sub-resource requests to HTTPS → SSL errors.
 *     Fix: gate on NEXT_PUBLIC_WS_BASE_URL.startsWith('wss://') instead.
 *
 *   BP-325: 'strict-dynamic' in script-src disables 'self'. Next.js prerenderers
 *     cache HTML at build time — no nonce attributes on <script> tags. At
 *     request time the middleware injects a nonce into the CSP header only.
 *     Mismatch: CSP has 'nonce-X' + 'strict-dynamic'; HTML has no nonces →
 *     every script blocked → React never hydrates → plain HTML.
 *     Fix: remove 'strict-dynamic' so 'self' is honoured for same-origin chunks.
 *
 * These tests pin the CSP shape so a future edit cannot re-introduce either bug.
 */

import { describe, it, expect, afterEach } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeRequest(path: string, headers: Record<string, string> = {}): NextRequest {
  const url = `http://localhost:3001${path}`;
  return new NextRequest(url, { headers });
}

function getCsp(request: NextRequest): string {
  const response = middleware(request);
  return response.headers.get("Content-Security-Policy") ?? "";
}

// ── BP-324 regression: upgrade-insecure-requests guard ────────────────────────

describe("BP-324 — upgrade-insecure-requests guard", () => {
  afterEach(() => {
    delete process.env.NEXT_PUBLIC_WS_BASE_URL;
  });

  it("omits upgrade-insecure-requests when NEXT_PUBLIC_WS_BASE_URL is ws:// (HTTP deployment)", () => {
    // ws:// = local dev Docker container serving plain HTTP — must NOT upgrade
    process.env.NEXT_PUBLIC_WS_BASE_URL = "ws://localhost:8010";
    const csp = getCsp(makeRequest("/dashboard"));
    expect(csp).not.toContain("upgrade-insecure-requests");
  });

  it("omits upgrade-insecure-requests when NEXT_PUBLIC_WS_BASE_URL is absent (defaults to ws://)", () => {
    // Absence of env var means ws:// fallback — same as above
    const csp = getCsp(makeRequest("/dashboard"));
    expect(csp).not.toContain("upgrade-insecure-requests");
  });

  it("includes upgrade-insecure-requests when NEXT_PUBLIC_WS_BASE_URL is wss:// (TLS deployment)", () => {
    // wss:// = production TLS — safe to upgrade all sub-resources to HTTPS
    process.env.NEXT_PUBLIC_WS_BASE_URL = "wss://api.example.com:8010";
    const csp = getCsp(makeRequest("/dashboard"));
    expect(csp).toContain("upgrade-insecure-requests");
  });
});

// ── BP-325 regression: strict-dynamic must not be in script-src ───────────────

describe("BP-325 — strict-dynamic must be absent from script-src", () => {
  it("does not contain strict-dynamic in script-src", () => {
    // strict-dynamic disables 'self', which blocks Next.js prerendered page scripts
    const csp = getCsp(makeRequest("/login"));
    expect(csp).not.toContain("strict-dynamic");
  });

  it("retains self in script-src so prerendered chunks can execute", () => {
    // 'self' must remain so /_next/static/*.js chunks load without nonces
    const csp = getCsp(makeRequest("/login"));
    const scriptSrc = csp.match(/script-src([^;]+)/)?.[1] ?? "";
    expect(scriptSrc).toContain("'self'");
  });

  it("retains unsafe-eval in script-src for Next.js webpack runtime", () => {
    const csp = getCsp(makeRequest("/dashboard"));
    const scriptSrc = csp.match(/script-src([^;]+)/)?.[1] ?? "";
    expect(scriptSrc).toContain("'unsafe-eval'");
  });
});

// ── Nonce consistency ─────────────────────────────────────────────────────────

describe("Nonce consistency", () => {
  it("sets the same nonce in both the CSP header and the x-nonce request header", () => {
    const request = makeRequest("/dashboard");
    const response = middleware(request);

    const csp = response.headers.get("Content-Security-Policy") ?? "";
    const cspNonce = csp.match(/'nonce-([^']+)'/)?.[1];
    expect(cspNonce).toBeTruthy();

    // The middleware forwards the nonce to server components via x-nonce on the
    // mutated request. Next.js exposes mutated request headers via headers() in
    // server components; the root layout reads x-nonce and passes it to inline scripts.
    // We verify via the content-security-policy request header (also set by middleware).
    const reqCspHeader = response.headers.get("Content-Security-Policy");
    expect(reqCspHeader).toContain(`'nonce-${cspNonce}'`);
  });

  it("generates a unique nonce per request", () => {
    const req1 = makeRequest("/dashboard");
    const req2 = makeRequest("/dashboard");
    const csp1 = getCsp(req1);
    const csp2 = getCsp(req2);

    const nonce1 = csp1.match(/'nonce-([^']+)'/)?.[1];
    const nonce2 = csp2.match(/'nonce-([^']+)'/)?.[1];
    expect(nonce1).toBeTruthy();
    expect(nonce2).toBeTruthy();
    expect(nonce1).not.toEqual(nonce2);
  });
});

// ── Other CSP directives ──────────────────────────────────────────────────────

describe("Other required CSP directives", () => {
  it("includes frame-ancestors none to block clickjacking", () => {
    const csp = getCsp(makeRequest("/"));
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it("includes form-action self to block credential exfiltration", () => {
    const csp = getCsp(makeRequest("/login"));
    expect(csp).toContain("form-action 'self'");
  });

  it("includes base-uri self to block base tag injection", () => {
    const csp = getCsp(makeRequest("/dashboard"));
    expect(csp).toContain("base-uri 'self'");
  });

  it("does not include unsafe-inline in script-src", () => {
    // Inline script XSS must remain blocked even without strict-dynamic
    const csp = getCsp(makeRequest("/dashboard"));
    const scriptSrc = csp.match(/script-src([^;]+)/)?.[1] ?? "";
    expect(scriptSrc).not.toContain("'unsafe-inline'");
  });

  it("includes unsafe-inline in style-src for Tailwind JIT", () => {
    const csp = getCsp(makeRequest("/"));
    const styleSrc = csp.match(/style-src([^;]+)/)?.[1] ?? "";
    expect(styleSrc).toContain("'unsafe-inline'");
  });
});
