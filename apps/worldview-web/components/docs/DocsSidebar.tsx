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

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import type { SidebarSection } from "@/lib/docs";

interface DocsSidebarProps {
  sections: SidebarSection[];
}

export function DocsSidebar({ sections }: DocsSidebarProps) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Documentation sections"
      // sticky-top with overflow so a long sidebar can scroll inside its
      // own scroll container instead of pushing the page out of view.
      className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto pr-4 text-sm"
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
                    className={cn(
                      "block rounded-[2px] border-l-2 py-1 pl-3 pr-2 transition-colors",
                      isActive
                        ? "border-primary bg-primary/5 text-foreground"
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
