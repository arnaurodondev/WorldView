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

// Warn if WS is insecure in production — JWT token travels in query param
const wsBaseUrl = process.env.NEXT_PUBLIC_WS_BASE_URL ?? "ws://localhost:8010";
if (process.env.NODE_ENV === "production" && wsBaseUrl.startsWith("ws://")) {
  console.warn(
    "[SECURITY] NEXT_PUBLIC_WS_BASE_URL uses ws:// (plaintext). " +
    "In production, use wss:// to encrypt WebSocket JWT tokens in transit."
  );
}

const nextConfig: NextConfig = {
  // Enable React strict mode for better dev-time error detection
  reactStrictMode: true,

  // Standalone output: produces a self-contained server.js + minimal node_modules.
  // Required for the Docker multi-stage build (see Dockerfile).
  // The standalone output is ~120 MB vs ~500 MB with full node_modules.
  output: "standalone",

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

  // Security headers applied to every response (all routes, all methods).
  // These headers harden the browser environment and protect against common
  // web vulnerabilities without requiring any application-level changes.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          // Prevent clickjacking — no page should ever be framed
          { key: "X-Frame-Options", value: "DENY" },
          // Prevent MIME-type sniffing (e.g., serving JS as text/html)
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Control referrer information leaked to external sites (news article links)
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Disable browser features we never use
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // HSTS only in production — localhost breaks with HSTS preload
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
    NEXT_PUBLIC_ZITADEL_URL:
      process.env.NEXT_PUBLIC_ZITADEL_URL ?? "http://localhost:8080",
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
