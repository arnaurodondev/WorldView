/**
 * components/docs/DocsBreadcrumb.tsx — page-top breadcrumb (T-B-2-06)
 *
 * WHY THIS EXISTS: Multi-level docs hierarchies need an explicit "you are
 * here" trail at the top of each page. Helps with:
 *   - quick navigation back up the tree
 *   - visual confirmation of the URL slug at the current page
 *   - SEO (Google renders breadcrumbs in result snippets)
 *
 * WHY SERVER COMPONENT: pure render — slug is a build-time prop.
 */

import Link from "next/link";
import { ChevronRight } from "lucide-react";

interface DocsBreadcrumbProps {
  /** URL slug array — same shape as DocPage.slug. Empty for /docs root. */
  slug: string[];
  /** Final-segment title to display at the end of the trail. */
  title: string;
}

/**
 * humanise — turn "getting-started" → "Getting started" for breadcrumb
 * intermediate segments where we don't have explicit titles cached.
 */
function humanise(s: string): string {
  return s
    .split("-")
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function DocsBreadcrumb({ slug, title }: DocsBreadcrumbProps) {
  // Build the segments array: ["Docs", "Getting started", "Sign up"]
  // with hrefs pointing to the cumulative path of each segment.
  const segments: Array<{ label: string; href: string; current: boolean }> = [
    { label: "Docs", href: "/docs", current: slug.length === 0 },
  ];

  let acc = "/docs";
  slug.forEach((seg, i) => {
    acc = `${acc}/${seg}`;
    const isLast = i === slug.length - 1;
    segments.push({
      label: isLast ? title : humanise(seg),
      href: acc,
      current: isLast,
    });
  });

  return (
    <nav aria-label="Breadcrumb" className="mb-4">
      <ol className="flex flex-wrap items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
        {segments.map((s, i) => (
          <li key={s.href} className="flex items-center gap-1">
            {i > 0 ? (
              <ChevronRight
                className="h-3 w-3 text-muted-foreground/50"
                aria-hidden="true"
              />
            ) : null}
            {s.current ? (
              <span aria-current="page" className="text-foreground">
                {s.label}
              </span>
            ) : (
              <Link
                href={s.href}
                className="transition-colors hover:text-foreground"
              >
                {s.label}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
