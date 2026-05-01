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

import { getAllDocs } from "@/lib/docs";

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

  // QA iter-1 (SEO M-7): enumerate every docs page so search engines
  // discover deep content. Without this, only /docs is in the sitemap
  // and the ~50 future pages stay invisible to crawlers.
  const docs = getAllDocs();
  const docsRoutes: MetadataRoute.Sitemap = docs.map((d) => ({
    url: `${baseUrl}${d.url}`,
    lastModified: d.frontmatter.updated ? new Date(d.frontmatter.updated) : now,
    changeFrequency: "monthly",
    // Root /docs index gets the highest priority; deep pages slightly less.
    priority: d.slug.length === 0 ? 0.9 : 0.7,
  }));

  return [...publicRoutes, ...docsRoutes];
}
