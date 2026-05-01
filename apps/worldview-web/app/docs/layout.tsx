/**
 * app/docs/layout.tsx — /docs route group layout (T-B-2-03)
 *
 * WHY THIS EXISTS: All /docs/* routes share the same chrome — top nav with
 * the docs search, left sidebar nav tree, right TOC rail. This layout
 * wraps every doc page so that chrome is consistent and only the central
 * MDX content area changes between pages.
 *
 * WHY a separate layout (not part of the root layout): the root layout
 * is shared with the marketing landing and the authenticated app shell.
 * Mounting the docs sidebar there would leak into both.
 *
 * WHY SERVER COMPONENT: pure composition; the interactive bits
 * (DocsSidebar, DocsSearch) carry their own "use client" islands.
 */

import Link from "next/link";
import { getSidebarSections, getSearchIndex } from "@/lib/docs";
import { DocsSidebar } from "@/components/docs/DocsSidebar";
import { DocsSearch } from "@/components/docs/DocsSearch";

export const metadata = {
  title: {
    template: "%s | Worldview Docs",
    default: "Documentation",
  },
  description:
    "Worldview documentation — getting started, API reference, dashboard widgets, screener filters, and more.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  // Build the sidebar + search index server-side so the static payload is
  // self-contained — no runtime fetch on the client. The data is small
  // (~few KB even for ~50 pages) so embedding it is cheaper than a round-trip.
  const sections = getSidebarSections();
  const searchIndex = getSearchIndex();

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ── Top header — sticky brand mark + cmd-K search ───────────── */}
      <header className="sticky top-0 z-40 border-b border-border/40 bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-3 lg:px-8">
          <div className="flex items-center gap-6">
            <Link href="/" className="font-mono text-base font-semibold text-foreground">
              Worldview
            </Link>
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
              Documentation
            </span>
          </div>
          <div className="flex items-center gap-2">
            <DocsSearch index={searchIndex} />
            <Link
              href="/login"
              className="hidden rounded-[2px] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground sm:inline-flex"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="inline-flex items-center rounded-[2px] bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition-all hover:bg-primary/90"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      {/* ── 3-column layout: sidebar / content / TOC ──────────────────
          The content column hosts the MDX body + the page-level TOC
          which is rendered inside the dynamic page (not here) so it can
          read per-page heading data. */}
      <div className="mx-auto grid max-w-7xl gap-8 px-6 py-10 lg:grid-cols-[220px,minmax(0,1fr)] lg:gap-10 lg:px-8 xl:grid-cols-[220px,minmax(0,1fr),200px]">
        <DocsSidebar sections={sections} />
        <main className="min-w-0">{children}</main>
      </div>
    </div>
  );
}
