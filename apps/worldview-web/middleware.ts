/**
 * middleware.ts — Per-request nonce-based CSP
 *
 * PLAN-0059 Wave I-6 hardening: replaces the static `'unsafe-inline'` script-src
 * directive (in next.config.ts) with a per-request nonce. Inline scripts that
 * Next.js 15 App Router emits (React hydration payload, dynamic imports) are
 * authorised by the matching `nonce-{N}` directive; everything else is rejected.
 *
 * WHY this matters: `'unsafe-inline'` lets ANY injected `<script>` tag execute,
 * which defeats the primary purpose of CSP. A per-request nonce with
 * `strict-dynamic` lets the legitimate Next.js runtime emit and its dynamically
 * imported children but blocks attacker-injected script tags.
 *
 * IMPLEMENTATION (per Next.js docs):
 * https://nextjs.org/docs/app/building-your-application/configuring/content-security-policy
 *
 *   1. Generate 16 random bytes per request, base64-encode as the nonce.
 *   2. Inject the nonce into BOTH the request headers (so server components
 *      can read it via `headers().get("x-nonce")` and pass to inline <script>
 *      tags they emit) AND the response Content-Security-Policy header.
 *   3. `strict-dynamic` lets the nonced scripts dynamically load further
 *      modules without each one needing its own nonce.
 *   4. Style-src has both `'unsafe-inline'` (Tailwind JIT inline <style>)
 *      AND `'nonce-N'`. Next.js 15 auto-adds the nonce attribute to every
 *      <link rel="stylesheet"> when x-nonce is set. Safari blocks these
 *      stylesheets unless style-src also contains the matching nonce-source —
 *      it does NOT fall back to 'self' when a nonce attribute is present.
 *      Without 'nonce-N' in style-src the entire page renders unstyled.
 *
 * PERFORMANCE: middleware adds ~0.3ms per request for the nonce generation
 * + header copy. Negligible at the request scale we run.
 *
 * COVERAGE (matcher below): every route except static assets and the Next.js
 * internals. Login + dashboard + API routes all run through here.
 */

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

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
