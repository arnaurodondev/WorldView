/**
 * components/docs/DocsSidebar.tsx — sidebar nav tree (T-B-2-03)
 *
 * WHY THIS EXISTS: Long-form docs need a persistent left rail to navigate
 * between sections. The sidebar is grouped by frontmatter `section` and
 * the active page is highlighted so the visitor always knows where they
 * are in the doc set.
 *
 * WHY CLIENT COMPONENT: needs `usePathname()` to highlight the active
 * link as the user navigates between docs. Server-rendering would freeze
 * the highlight to whatever route was last hit at build time.
 */

"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import type { SidebarSection } from "@/lib/docs";

interface DocsSidebarProps {
  sections: SidebarSection[];
}

export function DocsSidebar({ sections }: DocsSidebarProps) {
  const pathname = usePathname();
  // QA iter-1 (a11y M-A1): auto-scroll the active link into view on mount
  // / pathname change. Long sidebars (50+ pages) otherwise leave the
  // active page below the fold.
  const navRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const active = navRef.current?.querySelector('[aria-current="page"]');
    if (active && "scrollIntoView" in active) {
      (active as HTMLElement).scrollIntoView({ block: "nearest" });
    }
  }, [pathname]);

  return (
    <nav
      ref={navRef}
      aria-label="Documentation sections"
      // sticky-top with overflow so a long sidebar can scroll inside its
      // own scroll container instead of pushing the page out of view.
      // QA iter-1 (design POLISH): top-16 matches the actual sticky nav
      // height (~52-56px) — was top-20 = 80px = 24px dead band.
      className="sticky top-16 max-h-[calc(100vh-5rem)] overflow-y-auto pr-4 text-sm"
    >
      {sections.map((section) => (
        <div key={section.heading} className="mb-6">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
            {section.heading}
          </p>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const isActive = pathname === item.url;
              return (
                <li key={item.url}>
                  <Link
                    href={item.url}
                    aria-current={isActive ? "page" : undefined}
                    // QA iter-1 (design M-D4): dropped bg-primary/5 — the
                    // border-l-2 + font-medium combo is sufficient signal
                    // for the active state without the second amber cue.
                    className={cn(
                      "block rounded-[2px] border-l-2 py-1 pl-3 pr-2 transition-colors",
                      isActive
                        ? "border-primary text-foreground font-medium"
                        : "border-transparent text-muted-foreground hover:border-border/60 hover:text-foreground",
                    )}
                  >
                    {item.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
