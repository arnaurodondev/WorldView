/**
 * components/docs/DocsTableOfContents.tsx — right-rail TOC (T-B-2-04)
 *
 * WHY THIS EXISTS: For pages with more than ~3 sections, a right-rail
 * TOC with scroll-spy is the de-facto standard (Stripe / Vercel /
 * Tailwind / shadcn docs). It lets the reader scan the structure without
 * unfolding the page.
 *
 * WHY CLIENT COMPONENT: scroll-spy requires IntersectionObserver, a
 * client API. Headings are pre-extracted server-side from the raw MDX
 * source (lib/docs.ts:extractHeadings) so this component only handles
 * "which heading is currently in view".
 */

"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import type { DocHeading } from "@/lib/docs";

interface DocsTableOfContentsProps {
  headings: DocHeading[];
}

export function DocsTableOfContents({ headings }: DocsTableOfContentsProps) {
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  useEffect(() => {
    // Edge case: zero headings on the page → no observer needed.
    if (headings.length === 0) return;

    // rootMargin pulls the trigger zone upward so a heading is "active"
    // while it's in the upper third of the viewport — feels natural while
    // reading top-to-bottom. Threshold 0 = fire on any intersection change.
    const observer = new IntersectionObserver(
      (entries) => {
        // Among intersecting headings, pick the topmost (smallest top value)
        // so the active marker doesn't jump around when several headings
        // fall in the trigger zone at once (common on small viewports).
        const visible = entries.filter((e) => e.isIntersecting);
        if (visible.length === 0) return;
        visible.sort(
          (a, b) => a.boundingClientRect.top - b.boundingClientRect.top,
        );
        const id = visible[0].target.id;
        if (id) setActiveSlug(id);
      },
      { rootMargin: "-80px 0px -66% 0px", threshold: 0 },
    );

    // Attach observer to every TOC-eligible heading (h2 + h3) currently
    // rendered. Re-runs when headings prop changes (e.g., navigating
    // between docs without a hard reload).
    const observed: Element[] = [];
    for (const h of headings) {
      const el = document.getElementById(h.slug);
      if (el) {
        observer.observe(el);
        observed.push(el);
      }
    }

    return () => {
      for (const el of observed) observer.unobserve(el);
      observer.disconnect();
    };
  }, [headings]);

  if (headings.length === 0) return null;

  return (
    <aside
      aria-label="On this page"
      // QA iter-1 (design POLISH): top-16 matches the sticky nav (was top-20).
      className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto text-sm"
    >
      <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
        On this page
      </p>
      {/* QA iter-1 (a11y M-A2 + design M-D5): vertical border-l acts as
          the anchor bar; active heading swaps to a 2px primary border so
          the active state is signaled by both color AND a structural
          indicator (WCAG 1.4.1 — color is not the only cue). */}
      <ul className="space-y-1 border-l border-border/30">
        {headings.map((h) => {
          const isActive = activeSlug === h.slug;
          return (
            <li
              key={h.slug}
              // QA iter-1 (design POLISH): pl-2 instead of pl-3 — 12px
              // indent on 12px text was too aggressive.
              className={cn("text-xs", h.level === 3 && "pl-2")}
            >
              <a
                href={`#${h.slug}`}
                aria-current={isActive ? "location" : undefined}
                className={cn(
                  "-ml-px block border-l-2 py-0.5 pl-3 transition-colors",
                  isActive
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:border-border/60 hover:text-foreground",
                )}
              >
                {h.text}
              </a>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
