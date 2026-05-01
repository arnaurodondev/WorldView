/**
 * next.config.ts — Next.js 15 configuration for worldview-web
 *
 * WHY THIS EXISTS: Configures the Next.js app router, environment variables,
 * and the critical API proxy rewrite. All S9 calls go through `/api/*` which
 * this config rewrites to `API_GATEWAY_URL/*` at the Next.js server layer.
 *
 * WHO USES IT: Next.js build + dev server
 * DESIGN REFERENCE: PRD-0028 §6.4 Frontend App Structure
 *
 * CRITICAL RULE: Frontend NEVER constructs direct backend URLs.
 * All data fetching goes through /api/* → S9 gateway.
 */

import type { NextConfig } from "next";

// PLAN-0059 W0 fix F-016 (2026-04-30): in production SERVING (not build), refuse
// to start with ws:// — previous behaviour was a console.warn that was easy to
// miss. JWT travels in URL (still — F-015 deferred to Wave D), so plaintext is
// a hard failure, not a warning. We detect serving via NEXT_PHASE so the build
// step (Docker, CI) can complete with the dev default value; the deploy
// pipeline must override NEXT_PUBLIC_WS_BASE_URL at runtime to wss://.
const wsBaseUrl = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010";
const isProductionServer =
  process.env.NODE_ENV === "production" &&
  process.env.NEXT_PHASE === "phase-production-server";
if (isProductionServer && wsBaseUrl.startsWith("ws://")) {
  throw new Error(
    "[SECURITY] NEXT_PUBLIC_WS_BASE_URL uses ws:// (plaintext) in production. " +
    "Set NEXT_PUBLIC_WS_BASE_URL=wss://... before starting. " +
    "WebSocket JWT tokens travel in the URL query string and would be exposed " +
    "in proxies / logs / network captures."
  );
}
// Build-time + dev: log a warn (preserved by `removeConsole.exclude: ["warn"]`).
if (process.env.NODE_ENV === "production" && wsBaseUrl.startsWith("ws://") && !isProductionServer) {
  console.warn(
    "[SECURITY] NEXT_PUBLIC_WS_BASE_URL uses ws:// — set wss:// at deploy time."
  );
}

const nextConfig: NextConfig = {
  // Enable React strict mode for better dev-time error detection
  reactStrictMode: true,

  // SEC-005 FIX: Remove X-Powered-By: Next.js header to avoid leaking stack info
  poweredByHeader: false,

  // PLAN-0059 W0 F-CODE-NEW-014 — build/runtime tuning.
  // - optimizePackageImports: tree-shakes large icon/UI bundles per import site
  //   (lucide-react alone ships 1000+ icons; without this Next pulls the whole
  //   barrel file into every chunk that imports a single icon). ~5-8% bundle reduction.
  // - removeConsole in production: strips dev-only console.log statements but keeps
  //   console.error/warn for Sentry surfacing.
  // - productionBrowserSourceMaps: required for Sentry sourcemap upload (Wave A-2 T-A-2-03).
  experimental: {
    // PLAN-0059 W0 fix F-006 (2026-04-30): React Compiler (auto-memoization).
    // The Compiler emits `useMemo`/`useCallback`/`React.memo` automatically
    // for components/hooks that satisfy its rules-of-React rules. With it on,
    // the perf budgets in W4 (Plan §G) measure against an auto-memoized
    // baseline — the way Linear / Vercel Dashboard / Cal.com run.
    // Requires `babel-plugin-react-compiler` (installed alongside this flag).
    reactCompiler: true,
    optimizePackageImports: [
      "lucide-react",
      "@radix-ui/react-icons",
      "@tanstack/react-query",
      "date-fns",
      "recharts",
    ],
  },
  compiler: {
    removeConsole:
      process.env.NODE_ENV === "production"
        ? { exclude: ["error", "warn"] }
        : false,
  },
  // PLAN-0059 W0 fix F-014 (2026-04-30): production sourcemaps DISABLED until
  // T-A-2-03 (Sentry wiring) lands. Otherwise `.map` files would be served at
  // /_next/static/chunks/*.js.map exposing absolute build paths and full
  // unminified source. Re-enable in tandem with `withSentryConfig({ hideSourceMaps: true })`
  // so Sentry can upload them at build time without leaving them publicly reachable.
  productionBrowserSourceMaps: false,

  // Standalone output: produces a self-contained server.js + minimal node_modules.
  // Required for the Docker multi-stage build (see Dockerfile).
  // The standalone output is ~120 MB vs ~500 MB with full node_modules.
  output: "standalone",

  // BT-001 FIX: Server-side redirect for /instruments → /screener.
  // Previously handled by a client-side router.replace() in instruments/page.tsx,
  // which caused a 404 flash on SSR and broke non-JS crawlers / link previews.
  async redirects() {
    return [
      {
        source: "/instruments",
        destination: "/screener",
        permanent: false, // 307 temporary — may change if we add an instruments index page
      },
    ];
  },

  // API gateway proxy rewrite:
  // /api/v1/* → API_GATEWAY_URL/v1/*
  // This means components call `/api/v1/portfolios` and Next.js
  // transparently forwards to `http://localhost:8000/v1/portfolios`.
  // In production, API_GATEWAY_URL points to the Hetzner k3s S9 service.
  async rewrites() {
    const apiGatewayUrl =
      process.env.API_GATEWAY_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiGatewayUrl}/:path*`,
      },
    ];
  },

  // Security headers applied to every response.
  //
  // PLAN-0059 I-6 hardening: the per-request Content-Security-Policy now
  // lives in `middleware.ts` (nonce-based, strict-dynamic). The other
  // security headers stay here because they are STATIC (don't change per
  // request) and `headers()` is the Next-recommended path for static
  // header config. Per-request dynamic headers go through middleware.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          // Prevent clickjacking — no page should ever be framed.
          { key: "X-Frame-Options", value: "DENY" },
          // Prevent MIME-type sniffing (e.g., serving JS as text/html).
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Control referrer info leaked to external sites (news article links).
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Disable browser features we never use.
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // HSTS only in production — localhost breaks with HSTS preload.
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }]
            : []),
        ],
      },
    ];
  },

  // Expose env vars to the browser (NEXT_PUBLIC_ prefix required)
  // These are safe to expose: they are service URLs, not secrets.
  env: {
    // WS connects directly to S10 — Next.js rewrites don't apply to WebSocket protocol
    // So we expose the S10 WS URL directly (ADR-F-02)
    NEXT_PUBLIC_WS_BASE_URL:
      process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010",
    // App name used in TopBar, page titles, and landing page
    NEXT_PUBLIC_APP_NAME: process.env.NEXT_PUBLIC_APP_NAME ?? "Worldview",
    // Zitadel OIDC configuration — used by login/callback pages for PKCE flow
    // These are NOT secrets: they are public OIDC params that belong in the browser.
    // The actual tokens are handled server-side by S9 (never visible in the browser).
    //
    // WHY no default for NEXT_PUBLIC_ZITADEL_URL: login/page.tsx gates the
    // "Dev Login" affordance on `!process.env.NEXT_PUBLIC_ZITADEL_URL` (the
    // O-AU-01 fix). A ?? fallback here would inject "http://localhost:8080"
    // at build time so the var is never absent — permanently suppressing the
    // dev-login button even when Zitadel is not running. Leave it undefined
    // when not set; the login page's initiateLogin() already surfaces a clear
    // error if someone clicks "Sign in with Zitadel" without the var set.
    NEXT_PUBLIC_ZITADEL_URL: process.env.NEXT_PUBLIC_ZITADEL_URL,
    NEXT_PUBLIC_ZITADEL_CLIENT_ID:
      process.env.NEXT_PUBLIC_ZITADEL_CLIENT_ID ?? "worldview-web",
  },

  // Allow images from common financial data providers
  // These will be used for company logos and market imagery
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.eodhd.com" },
      { protocol: "https", hostname: "**.clearbit.com" },
      { protocol: "https", hostname: "**.logo.clearbit.com" },
    ],
  },
};

export default nextConfig;
