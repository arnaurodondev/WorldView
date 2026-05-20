/**
 * middleware.ts — Edge middleware: instrument-URL canonicalisation + per-request CSP nonce
 *
 * Two responsibilities (running in this order on every matched request):
 *
 * 1. INSTRUMENT URL CANONICALISATION (PRD-0089 F2 step 9)
 *    `/instruments/{slug}` is the analyst-facing canonical URL. The slug is
 *    a ticker (e.g. `AAPL`). This middleware enforces a single normal form
 *    so caches, share-links, and the browser history are deterministic.
 *      a. Lowercase → 301 redirect to uppercase. `/instruments/aapl` →
 *         `/instruments/AAPL`. WHY 301 (permanent): the analyst-facing
 *         canonical form never changes, and browsers / CDNs may cache the
 *         redirect — desired behaviour.
 *      b. Stripped index prefix. EODHD-style index tickers carry a leading
 *         `^` (e.g. `^GSPC` for the S&P 500). The `^` character requires
 *         URL-encoding (%5E) which is ugly in share-links. We strip it on
 *         entry — `/instruments/^GSPC` (or its encoded form
 *         `/instruments/%5EGSPC`) 301-redirects to `/instruments/GSPC`.
 *      c. Legacy ticker alias 301 (DEFERRED — see TODO below). Today the
 *         backend `resolve_security_id` already accepts both aliases and
 *         canonical tickers transparently, and the page-bundle endpoint
 *         returns 404 for true unknowns (which triggers the
 *         <InstrumentNotFound/> primitive). Surfacing the canonical-ticker
 *         301 in the URL bar is a UX nicety, not a correctness requirement.
 *         Wiring it from middleware requires an UNAUTHENTICATED S9 alias
 *         endpoint (today's resolver is authenticated). When that endpoint
 *         exists the wiring is a single `fetch` + a redirect early-return.
 *
 *    Constraints:
 *      - Edge runtime (fast, no Node-only APIs).
 *      - No infinite-loop risk: lowercase→uppercase fires only when the
 *        input strictly differs from `input.toUpperCase()` AND only when
 *        the path starts with `/instruments/`. The redirect target is
 *        always uppercase so a second pass through middleware on the same
 *        URL skips the redirect branch.
 *      - Special characters (`BRK.B`, `BF.B`, `RDS.A`) are valid path
 *        segments and are NOT redirected (they're already uppercase).
 *
 * 2. PER-REQUEST CSP NONCE (PLAN-0059 Wave I-6 — unchanged from before)
 *    Same as the previous middleware: generate 16 random bytes per request,
 *    inject as a base64 nonce into both the request `x-nonce` header (read
 *    by server components that emit inline <script> tags) and the response
 *    `Content-Security-Policy` header.
 *
 * COVERAGE (matcher below): every page route except static assets and the
 * Next.js internals. Login + dashboard + API routes all run through here.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// ── Nonce config ─────────────────────────────────────────────────────────────

// Bytes of randomness for the nonce. 16 → 128 bits, well above the 64-bit
// floor recommended by OWASP for CSP nonces.
const NONCE_BYTES = 16;

function generateNonce(): string {
  // Web Crypto in Edge runtime + Node 18+. globalThis.crypto.getRandomValues
  // is available everywhere Next.js middleware runs.
  const buf = new Uint8Array(NONCE_BYTES);
  crypto.getRandomValues(buf);
  // base64 encoding (URL-safe not required — CSP accepts standard base64).
  let s = "";
  for (const b of buf) s += String.fromCharCode(b);
  return btoa(s);
}

// ── Instrument URL canonicalisation ──────────────────────────────────────────

// WHY a precise pattern (not just `startsWith("/instruments/")`): we only
// want to canonicalise the dynamic-route slug (the segment AFTER /instruments/),
// not the list page itself (`/instruments`) and not deeper sub-paths
// (`/instruments/AAPL/something`). The regex captures group 1 = slug,
// group 2 = trailing remainder (preserved verbatim).
//
// Example match table:
//   /instruments              → no match (list page, leave it alone)
//   /instruments/             → no match (would be empty slug — let Next.js 404)
//   /instruments/aapl         → match, slug="aapl"
//   /instruments/BRK.B        → match, slug="BRK.B"
//   /instruments/^GSPC        → match, slug="^GSPC"
//   /instruments/%5EGSPC      → match, slug="%5EGSPC" (we decode below)
//   /instruments/AAPL/news    → match, slug="AAPL", remainder="/news"
const INSTRUMENT_PATH_RE = /^\/instruments\/([^/]+)(\/.*)?$/;

/**
 * Canonicalise an instrument URL path. Returns the canonical form, or
 * `null` if the input is already canonical (caller should not redirect).
 *
 * Rules (in order):
 *   1. Decode percent-encoded slug (URL bar form `%5E` → `^`).
 *   2. Strip leading `^` (index ticker prefix).
 *   3. Uppercase.
 * If the resulting slug differs from the input slug, return the new path
 * (preserving query string + trailing path). Otherwise return null.
 *
 * WHY pure / exported: lets the Vitest unit test exercise the logic
 * without spinning up a NextRequest. Edge code stays trivial to test.
 */
export function canonicaliseInstrumentPath(pathname: string): string | null {
  const m = INSTRUMENT_PATH_RE.exec(pathname);
  if (!m) return null;
  const originalSlug = m[1];
  const remainder = m[2] ?? "";

  // Decode the slug first so `^` and `.` round-trip correctly. We catch
  // decode failures defensively — a malformed `%XX` triplet shouldn't
  // crash the middleware; we fall through with the raw slug.
  let decoded: string;
  try {
    decoded = decodeURIComponent(originalSlug);
  } catch {
    decoded = originalSlug;
  }

  // Strip leading caret (index prefix). WHY strip not separate-route:
  // documented in commit body — the F2 plan offered either approach;
  // strip-`^` keeps the routing surface to a single `/instruments/[ticker]`
  // and avoids creating a parallel `/indices/[ticker]` tree that would
  // duplicate the InstrumentPageClient orchestration. Indices ARE
  // instruments (kind=index) — they share quote, fundamentals, and
  // intelligence panels. Future: if/when the page-bundle returns a
  // `kind=index` flag and the UI diverges meaningfully (e.g. no insider
  // transactions), we can introduce `/indices/[ticker]` as a thin
  // re-export at that point.
  const withoutCaret = decoded.startsWith("^") ? decoded.slice(1) : decoded;

  const upper = withoutCaret.toUpperCase();

  // If the canonical form matches the original slug verbatim, there is
  // nothing to do. We compare against `originalSlug` (not `decoded`) so a
  // pathname containing `%5E` is treated as non-canonical and redirected
  // to its decoded uppercase form.
  if (upper === originalSlug) return null;

  return `/instruments/${upper}${remainder}`;
}

// ── Main middleware ──────────────────────────────────────────────────────────

// Log every inbound request so Docker logs (`docker logs worldview-worldview-web-1`)
// show access traffic. Uses console.warn because production builds strip
// console.log (next.config.ts removeConsole) but preserve warn + error.
// Format mirrors Next.js dev-mode output for easy scanning.
function logRequest(request: NextRequest): void {
  const ts = new Date().toISOString();
  const method = request.method;
  const path = request.nextUrl.pathname + (request.nextUrl.search || "");
  console.warn(`[access] ${ts} ${method} ${path}`);
}

export function middleware(request: NextRequest): NextResponse {
  logRequest(request);

  // ── Stage 1: instrument URL canonicalisation ──────────────────────────────
  // WHY this runs FIRST: a 301 is a terminal response — no point computing a
  // nonce + CSP header for a response the browser will immediately discard.
  //
  // TODO (PRD-0089 F2 follow-up): wire legacy-alias 301 redirects. Requires an
  // UNAUTHENTICATED `GET /v1/instruments/aliases/{ticker}` endpoint on S9 that
  // returns `{canonical_ticker: "META"}` for inputs like `FB`. Today the
  // resolver lives behind OIDC auth (resolution.py uses ServiceClients which
  // require a bearer JWT) so we cannot fetch from middleware without leaking
  // tokens. Until that endpoint ships, the canonical-ticker 301 manifests one
  // hop later: page-bundle resolves the alias on the server and the UI
  // continues to show the legacy ticker in the URL — not wrong, just less
  // pretty.
  const canonical = canonicaliseInstrumentPath(request.nextUrl.pathname);
  if (canonical !== null) {
    // WHY new URL(...) clone: preserves the search string + hash unchanged.
    // We only mutate `pathname`; everything else passes through.
    const redirectUrl = new URL(request.nextUrl.toString());
    redirectUrl.pathname = canonical;
    // WHY 301 (permanent): the canonical form is permanent. CDNs and
    // browsers may cache the redirect — that's the desired behaviour
    // because it cuts a round-trip on subsequent visits to the same URL.
    return NextResponse.redirect(redirectUrl, 301);
  }

  // ── Stage 2: CSP nonce ────────────────────────────────────────────────────
  const nonce = generateNonce();

  // The CSP header. Differences from the previous next.config.ts version:
  //   - script-src: nonce + strict-dynamic (NO 'unsafe-inline')
  //   - style-src: still 'unsafe-inline' (Tailwind / shadcn limitation)
  //   - connect-src: dev needs to allow ws/wss to S10 alert WebSocket
  //   - everything else preserved verbatim
  //
  // wsOrigin is read from the public env var. In production the origin is
  // identical to the request origin; in dev it's localhost:8010.
  const wsBase = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010";
  const wsOrigin = wsBase.replace(/^wss?:\/\//, "");

  const cspDirectives = [
    "default-src 'self'",
    // 'unsafe-eval' is required by the Next.js webpack runtime (dynamic requires).
    // WHY NO 'strict-dynamic' — BP-325: Next.js prerenderers (SSG / ISR) cache HTML
    // at BUILD time before any per-request nonce exists. At request time the
    // middleware generates a fresh nonce and injects it into the CSP header, but the
    // prerendered HTML has NO nonce attributes on its <script> tags. With
    // 'strict-dynamic' in script-src, 'self' is silently disabled — every nonce-less
    // script is blocked, React never hydrates, and every prerendered page appears as
    // plain unstyled HTML with no interactivity.
    // Removing 'strict-dynamic' restores 'self', allowing all /_next/static/*.js
    // chunks to execute regardless of whether they carry a nonce attribute.
    // Nonces remain in the directive to authorise Next.js's inline RSC flight
    // payload scripts (which DO have nonce attributes). External-script XSS is still
    // blocked because we have no wildcard hosts and no 'unsafe-inline'.
    `script-src 'self' 'nonce-${nonce}' 'unsafe-eval'`,
    // Style-src: 'unsafe-inline' required for Tailwind JIT + AG Grid dynamic
    // <style> injection (AG Grid v35 injects ~20 inline <style> elements at
    // grid init without nonces). WHY no 'nonce-N' here: per CSP Level 3 §6.8.2,
    // the presence of nonce-* in style-src causes browsers to IGNORE
    // 'unsafe-inline' for inline <style> elements — the nonce override defeats
    // 'unsafe-inline'. Since Next.js <link rel="stylesheet"> elements are served
    // from /_next/static/ (covered by 'self'), the nonce on those elements is
    // not required in style-src. 'self' + 'unsafe-inline' is sufficient.
    // (BP-389: nonce-in-style-src blocks AG Grid inline styles)
    `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com`,
    // font-src: 'data:' is required for AG Grid's alpine theme which embeds
    // its icon font as a base64 data: URI inside the bundled CSS.
    // (BP-389: AG Grid icon font blocked by font-src without data:)
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' https://*.eodhd.com https://*.clearbit.com data: blob:",
    `connect-src 'self' ws://${wsOrigin} wss://${wsOrigin}`,
    "frame-ancestors 'none'",
    // base-uri locked to 'self' so attackers cannot redefine the relative-URL
    // base via a crafted <base> tag injection.
    "base-uri 'self'",
    // form-action locked to 'self' — credentials cannot be exfiltrated by an
    // injected form pointing to an external endpoint.
    "form-action 'self'",
    // upgrade-insecure-requests only when the app is actually behind HTTPS.
    // ROOT CAUSE OF BP-324: NODE_ENV=production is set in the Docker dev container
    // (required for Next.js standalone mode) but the container serves HTTP.
    // upgrade-insecure-requests causes Chrome/Safari to upgrade ALL sub-resource
    // requests (CSS/JS) from http://localhost:3001/... to https://localhost:3001/...
    // No HTTPS server exists → SSL handshake fails → every static asset gets
    // net::ERR_SSL_PROTOCOL_ERROR → page renders completely unstyled with no JS.
    // Navigation requests are exempt from the upgrade (HTML loads fine),
    // which is why content was visible but the page was broken.
    // FIX: use NEXT_PUBLIC_WS_BASE_URL as the HTTPS signal — wss:// means TLS
    // deployment; ws:// means HTTP (local dev Docker). Never use NODE_ENV alone.
    ...(wsBase.startsWith("wss://") ? ["upgrade-insecure-requests"] : []),
  ].join("; ");

  // Forward the nonce to the rendering server components via a request header.
  // The root layout reads it via `headers().get("x-nonce")` and passes it to
  // any inline <script> it renders. Next.js automatically applies it to its
  // own framework-emitted scripts when this header is present.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  // Some Next.js versions read the CSP from a request header to know which
  // scripts to nonce. Setting both is harmless.
  requestHeaders.set("content-security-policy", cspDirectives);

  const response = NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });

  // Set the CSP on the response so the browser enforces it.
  response.headers.set("Content-Security-Policy", cspDirectives);

  return response;
}

// Apply the middleware to every page + API route, but skip static assets and
// Next.js internals. The negative-lookahead pattern is the documented
// Next.js way to write a "everything except X" matcher.
export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - /_next/static (Next.js static files — bundled JS/CSS)
     * - /_next/image (image optimisation API)
     * - favicon.ico, robots.txt, sitemap.xml
     * - /public/* (everything in public/, served as-is)
     *
     * Note: the leading "/" is implicit; the regex is matched against the
     * pathname of the URL.
     */
    {
      source:
        "/((?!_next/static|_next/image|favicon.ico|robots.txt|sitemap.xml|manifest.webmanifest|icon-|og-image|twitter-card).*)",
      missing: [
        // Skip pre-fetches — they don't need CSP enforcement and re-running
        // the middleware on each one would burn nonce-generation cycles.
        // Coverage:
        //   - next-router-prefetch: emitted by Next.js Link prefetch.
        //   - purpose=prefetch: legacy Chrome / Safari prefetch.
        //   - sec-purpose=prefetch: modern Chrome/Edge prefetch (Speculation
        //     Rules API). Without this exclusion every browser-driven
        //     prefetch burns a fresh nonce.
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
        { type: "header", key: "sec-purpose", value: "prefetch" },
      ],
    },
  ],
};
