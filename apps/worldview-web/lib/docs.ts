/**
 * lib/docs.ts — file-based documentation loader (PLAN-0052 Wave B T-B-2-02)
 *
 * WHY THIS EXISTS: PLAN-0052 Wave B builds an MDX-driven docs hub at /docs.
 * Rather than pull in a heavyweight CMS or the deprecated `contentlayer`
 * package, we walk a content directory at build/server time and produce
 * typed records that the dynamic route consumes.
 *
 * WHY NOT contentlayer: contentlayer is no longer maintained (last release
 * 2023). next-mdx-remote/rsc is the Vercel-recommended replacement and
 * works natively with Next.js 15 App Router Server Components.
 *
 * STORAGE LAYOUT:
 *   apps/worldview-web/content/docs/
 *     index.mdx                          → /docs
 *     getting-started/index.mdx          → /docs/getting-started
 *     getting-started/sign-up.mdx        → /docs/getting-started/sign-up
 *     api-reference/index.mdx            → /docs/api-reference
 *     ...
 *
 * Each .mdx file has frontmatter:
 *   ---
 *   title: Getting started
 *   description: Welcome to Worldview.
 *   section: Getting Started
 *   order: 1
 *   ---
 *
 * WHY SYNCHRONOUS fs reads: this runs only at build time / on the server
 * for static-prerender. Async would add complexity for zero benefit.
 */

// QA iter-1 (architecture M-AR1): server-only marker fails the build
// instantly if a Client Component accidentally imports this module —
// node:fs is unavailable in the browser. Type-only imports are unaffected.
import "server-only";

import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";

/**
 * The on-disk root for MDX docs. process.cwd() resolves to the
 * worldview-web app dir when Next builds; for tests we may need to override
 * via DOCS_CONTENT_ROOT env (used by vitest).
 */
const CONTENT_ROOT =
  process.env.DOCS_CONTENT_ROOT ?? path.join(process.cwd(), "content", "docs");

/**
 * DocFrontmatter — the typed shape of an MDX file's frontmatter block.
 * Everything except `title` is optional with sensible fallbacks so authors
 * can write minimal frontmatter and still render valid pages.
 */
export interface DocFrontmatter {
  title: string;
  description?: string;
  /** Sidebar section heading. Falls back to a humanised first slug segment. */
  section?: string;
  /** Sidebar sort order within the section. Lower = higher in the list. */
  order?: number;
  /** ISO-8601 last-updated date string; rendered in the footer. */
  updated?: string;
}

/**
 * DocPage — fully resolved record for one docs URL. The `slug` array is
 * the URL path segments after `/docs/` (empty array = root /docs page).
 * `body` is the raw MDX source; the dynamic route compiles it via
 * next-mdx-remote/rsc.
 */
export interface DocPage {
  slug: string[];
  url: string; // canonical URL e.g. "/docs/getting-started/sign-up"
  filePath: string; // absolute on-disk path (used for edit-on-GitHub)
  frontmatter: DocFrontmatter;
  body: string;
}

/**
 * walkDocsDir — recursively enumerate .mdx files under CONTENT_ROOT.
 *
 * WHY recurse synchronously: `fs.readdirSync` is fine at build time and
 * keeps the loader trivially testable. Returns a flat list of absolute
 * file paths.
 */
function walkDocsDir(dir: string, acc: string[] = []): string[] {
  if (!fs.existsSync(dir)) return acc;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkDocsDir(full, acc);
    } else if (entry.isFile() && entry.name.endsWith(".mdx")) {
      acc.push(full);
    }
  }
  return acc;
}

/**
 * filePathToSlug — derive the URL slug array from an MDX file path.
 *
 * Examples:
 *   content/docs/index.mdx                   → []
 *   content/docs/getting-started/index.mdx   → ["getting-started"]
 *   content/docs/api-reference/quotes.mdx    → ["api-reference", "quotes"]
 */
function filePathToSlug(filePath: string): string[] {
  const rel = path.relative(CONTENT_ROOT, filePath);
  const noExt = rel.replace(/\.mdx$/, "");
  // "index" at the end = section root; drop the trailing segment.
  const segments = noExt.split(path.sep).filter((s) => s !== "index");
  return segments;
}

/**
 * humaniseSlug — turn "getting-started" → "Getting Started". Used as a
 * sidebar/title fallback when frontmatter omits a section name.
 */
function humaniseSlug(slug: string): string {
  return slug
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * slugifyHeading — turn heading text into an HTML id anchor slug. Shared
 * between extractHeadings() and the MDX components map so TOC anchors and
 * rendered heading IDs always agree.
 *
 * QA iter-1 (bugs m-4): single source of truth — was duplicated in two
 * files where any drift would break all anchors silently.
 */
export function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-");
}

/**
 * isSafeSlugSegment — defensive validator for one URL slug segment.
 *
 * Currently lib/docs.ts looks slugs up via membership-test against the
 * pre-walked file tree (no fs.readFile with the user-controlled path),
 * so path traversal is structurally impossible. This validator is
 * defense-in-depth: a future refactor that joins the slug with
 * CONTENT_ROOT would otherwise risk traversal. Reject anything that
 * isn't strictly [a-z0-9-]+.
 *
 * QA iter-1 (bugs M-2, security M-1).
 */
export function isSafeSlugSegment(seg: string): boolean {
  return /^[a-z0-9][a-z0-9-]*$/i.test(seg);
}

/**
 * getAllDocs — load every MDX page on disk.
 *
 * WHY a module-level cache: Next.js 15 may invoke this loader once per
 * dynamic route and once per generateStaticParams, generateMetadata, etc.
 * Caching avoids redundant fs traversal during a single build.
 *
 * QA iter-1 (architecture M-AR2): cache is bypassed in development so
 * MDX content edits are picked up immediately by the Next dev server.
 * Production keeps the cache (build-time only — no staleness risk).
 */
let _cache: DocPage[] | null = null;
const CACHE_ENABLED = process.env.NODE_ENV === "production";

export function getAllDocs(): DocPage[] {
  if (CACHE_ENABLED && _cache) return _cache;

  const files = walkDocsDir(CONTENT_ROOT);
  const pages: DocPage[] = files.map((filePath) => {
    const raw = fs.readFileSync(filePath, "utf8");
    const parsed = matter(raw);
    const fm = parsed.data as Partial<DocFrontmatter>;
    const slug = filePathToSlug(filePath);

    // Fallback title: humanise the last slug segment, or "Documentation"
    // for the root index. This keeps the loader resilient to authors who
    // forget the title field while still surfacing a non-empty heading.
    const title =
      fm.title ?? (slug.length > 0 ? humaniseSlug(slug[slug.length - 1]) : "Documentation");

    return {
      slug,
      url: slug.length === 0 ? "/docs" : `/docs/${slug.join("/")}`,
      filePath,
      frontmatter: {
        title,
        description: fm.description,
        section: fm.section ?? (slug.length > 0 ? humaniseSlug(slug[0]) : "Overview"),
        order: fm.order ?? 999,
        updated: fm.updated,
      },
      body: parsed.content,
    };
  });

  // Sort by section + order so callers don't need to re-sort. Section is
  // alphabetical fallback when no explicit ordering exists; "Overview"
  // pinned first via case-insensitive ASCII.
  pages.sort((a, b) => {
    const sa = a.frontmatter.section ?? "";
    const sb = b.frontmatter.section ?? "";
    if (sa !== sb) {
      if (sa === "Overview") return -1;
      if (sb === "Overview") return 1;
      return sa.localeCompare(sb);
    }
    return (a.frontmatter.order ?? 999) - (b.frontmatter.order ?? 999);
  });

  _cache = pages;
  return pages;
}

/**
 * getDocBySlug — find one doc page by its URL slug array.
 * Returns undefined when no MDX file maps to that slug (route should 404).
 */
export function getDocBySlug(slug: string[] | undefined): DocPage | undefined {
  const target = (slug ?? []).join("/");
  return getAllDocs().find((p) => p.slug.join("/") === target);
}

/**
 * getDocSlugs — flat list of every URL slug on disk. Used by
 * generateStaticParams to pre-render all docs at build time.
 */
export function getDocSlugs(): string[][] {
  return getAllDocs().map((p) => p.slug);
}

/**
 * SidebarSection — the grouped shape consumed by <DocsSidebar>.
 */
export interface SidebarSection {
  heading: string;
  items: Array<{ title: string; url: string }>;
}

/**
 * getSidebarSections — group all docs by frontmatter `section` for the
 * sidebar nav. Returns sections in the order they first appear in the
 * sorted-by-section pages list (so "Overview" stays pinned to top).
 */
export function getSidebarSections(): SidebarSection[] {
  const sections = new Map<string, SidebarSection["items"]>();
  for (const p of getAllDocs()) {
    const heading = p.frontmatter.section ?? "Misc";
    const arr = sections.get(heading) ?? [];
    arr.push({ title: p.frontmatter.title, url: p.url });
    sections.set(heading, arr);
  }
  return Array.from(sections.entries()).map(([heading, items]) => ({
    heading,
    items,
  }));
}

/**
 * getSearchIndex — flatten all docs into a Fuse.js-ready index.
 * One entry per heading + per page so the cmd-K search can match both
 * page titles and individual headings within pages.
 */
export interface SearchEntry {
  title: string;
  description?: string;
  section: string;
  url: string;
  /** Heading anchor when this entry refers to an h2/h3 inside a page. */
  hash?: string;
  body: string;
}

/**
 * extractHeadings — scan MDX source for `## ` and `### ` ATX headings
 * and produce a list of `{text, slug}` so the TOC and search can deep-link.
 *
 * WHY simple regex (not a full MDX parser): the cost/benefit of running
 * remark just to extract headings is poor — the simple regex catches the
 * 99% case (markdown ATX headings) and skips fenced code blocks reliably
 * by ignoring lines inside ``` fences.
 */
export interface DocHeading {
  level: 2 | 3;
  text: string;
  slug: string;
}

export function extractHeadings(body: string): DocHeading[] {
  const headings: DocHeading[] = [];
  // QA iter-1 (bugs m-4): track seen slugs and dedup with -2/-3/... suffix
  // (mirrors GitHub / rehype-slug behaviour) so two `## Setup` headings on
  // the same page don't produce duplicate IDs (HTML invalid; React key
  // collision in TOC).
  const seen = new Map<string, number>();
  let inFence = false;
  for (const line of body.split("\n")) {
    if (line.startsWith("```")) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = /^(#{2,3})\s+(.+?)\s*$/.exec(line);
    if (!m) continue;
    const level = m[1].length === 2 ? 2 : 3;
    const text = m[2].trim();
    const baseSlug = slugifyHeading(text);
    const count = seen.get(baseSlug) ?? 0;
    seen.set(baseSlug, count + 1);
    const slug = count === 0 ? baseSlug : `${baseSlug}-${count + 1}`;
    headings.push({ level: level as 2 | 3, text, slug });
  }
  return headings;
}

export function getSearchIndex(): SearchEntry[] {
  const entries: SearchEntry[] = [];
  for (const p of getAllDocs()) {
    // Page-level entry — matches the title + description verbatim.
    entries.push({
      title: p.frontmatter.title,
      description: p.frontmatter.description,
      section: p.frontmatter.section ?? "Misc",
      url: p.url,
      body: p.body.slice(0, 500), // first 500 chars for preview match
    });
    // Heading-level entries — let the user jump to a specific h2/h3.
    for (const h of extractHeadings(p.body)) {
      entries.push({
        title: `${p.frontmatter.title} · ${h.text}`,
        description: undefined,
        section: p.frontmatter.section ?? "Misc",
        url: p.url,
        hash: h.slug,
        body: h.text,
      });
    }
  }
  return entries;
}

/**
 * Test/dev only — clear the in-memory cache so a fresh content tree is
 * read on the next call. Used by vitest to test multiple fixture trees.
 */
export function _resetCache(): void {
  _cache = null;
}
