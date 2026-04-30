/**
 * app/sitemap.ts — sitemap.xml generator (T-A-1-14)
 *
 * WHY THIS EXISTS: Next.js 15 generates a public /sitemap.xml when this file
 * exists in the app directory. Search engines discover the canonical URL set
 * via the sitemap; without it, deep pages (docs, feedback) may take longer
 * to be indexed.
 *
 * WHAT WE LIST: only public, indexable routes. Authenticated routes (/chat,
 * /dashboard, /portfolio) are excluded — they redirect to login for guests
 * and would just bloat the sitemap.
 *
 * WHY hardcoded baseUrl env var: NEXT_PUBLIC_SITE_URL is set per environment
 * (worldview.local in dev, your prod domain in prod). Falls back to the
 * thesis-demo URL if unset.
 */

import type { MetadataRoute } from "next";

const baseUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://worldview.local";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();

  // Public marketing routes — indexable by search engines.
  const publicRoutes: MetadataRoute.Sitemap = [
    {
      url: `${baseUrl}/`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1.0,
    },
    {
      url: `${baseUrl}/docs`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${baseUrl}/feedback`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.5,
    },
    {
      url: `${baseUrl}/login`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.4,
    },
    {
      url: `${baseUrl}/register`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.7,
    },
  ];

  return publicRoutes;
}
