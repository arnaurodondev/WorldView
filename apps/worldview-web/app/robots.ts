/**
 * app/robots.ts — robots.txt generator (T-A-1-14)
 *
 * WHY THIS EXISTS: Next.js 15 generates /robots.txt at this route. Without
 * it, search engines crawl every authenticated route and waste crawl budget
 * on routes that just 302 to /login. We allow the marketing surface +
 * /docs and disallow everything that requires auth.
 */

import type { MetadataRoute } from "next";

const baseUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://worldview.local";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: ["/", "/docs", "/docs/*", "/feedback", "/login", "/register"],
        // Authenticated app shell — every route under (app), /admin/*,
        // /api/* — gated by middleware, not useful to crawl.
        disallow: [
          "/api/",
          "/admin/",
          "/dashboard",
          "/instrument/",
          "/portfolio",
          "/screener",
          "/chat",
          "/alerts",
          "/workspace",
          "/news",
          "/data",
          "/callback",
          "/settings/",
        ],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
  };
}
