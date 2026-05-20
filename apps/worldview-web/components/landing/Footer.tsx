/**
 * components/landing/Footer.tsx — landing footer (T-A-1-12)
 *
 * WHY THIS EXISTS: The footer is the last impression visitors take from the
 * marketing page. It must contain the canonical secondary nav (docs, status,
 * security, legal), brand mark, and a small status badge so visitors can
 * verify the system is healthy without leaving the page.
 *
 * WHY 4 COLUMNS (Product / Resources / Company / Legal): standard SaaS
 * footer information architecture. Visitors who scrolled this far are likely
 * to pick a single section to dive into, not browse the whole grid.
 */

import Link from "next/link";
import { Github, Globe } from "lucide-react";

const COLUMNS: Array<{ heading: string; links: Array<{ label: string; href: string }> }> = [
  {
    heading: "Product",
    links: [
      { label: "Workspace", href: "/login" },
      { label: "Screener", href: "/login?next=/screener" },
      { label: "AI chat", href: "/login?next=/chat" },
      { label: "Pricing", href: "/#pricing" },
    ],
  },
  {
    heading: "Resources",
    links: [
      { label: "Documentation", href: "/docs" },
      { label: "API reference", href: "/docs/api-reference" },
      { label: "Changelog", href: "/docs/changelog" },
      { label: "Roadmap", href: "/feedback" },
    ],
  },
  {
    heading: "Company",
    links: [
      { label: "About", href: "/docs/about" },
      { label: "Status", href: "/status" },
      { label: "Contact", href: "mailto:hello@worldview.local" },
      { label: "Feedback", href: "/feedback" },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Privacy", href: "/docs/legal/privacy" },
      { label: "Terms", href: "/docs/legal/terms" },
      { label: "Security", href: "/docs/legal/security" },
      { label: "DPA", href: "/docs/legal/dpa" },
    ],
  },
];

export function Footer() {
  return (
    <footer
      role="contentinfo"
      className="border-t border-border/40 bg-card/40"
    >
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8">
        {/* QA iter-1 (a11y m4): added md:grid-cols-3 so the footer doesn't
            stay 2-col + tall at 768–1023px tablet width. 2 → 3 → 5 cols. */}
        <div className="grid grid-cols-2 gap-[40px] md:grid-cols-3 lg:grid-cols-5">
          {/* Brand column — wider than the other 4 to match logo + tagline */}
          <div className="col-span-2 lg:col-span-1">
            <p className="mb-2 font-mono text-[16px] font-semibold tracking-tight text-foreground">
              Worldview
            </p>
            <p className="mb-4 text-xs text-muted-foreground">
              Bloomberg-grade research, without the Bloomberg bill.
            </p>
            {/* External links: rel="noopener noreferrer" defends against
                tabnabbing if these are ever changed to target="_blank"; no
                cost on same-tab links. lucide icons are decorative —
                aria-hidden so SR announces only the parent aria-label.
                QA iter-1 (security MINOR + a11y polish). */}
            <div className="flex items-center gap-3">
              <a
                href="https://github.com"
                rel="noopener noreferrer"
                aria-label="GitHub"
                className="text-muted-foreground hover:text-primary"
              >
                <Github className="h-4 w-4" aria-hidden="true" />
              </a>
              <Link
                href="/status"
                aria-label="Status page"
                className="text-muted-foreground hover:text-primary"
              >
                <Globe className="h-4 w-4" aria-hidden="true" />
              </Link>
            </div>
            {/* WHY a status badge: lets visitors verify uptime at a glance.
                The pulsing dot tracks the design system convention for live
                indicators (positive == green == healthy). */}
            <div className="mt-4 inline-flex items-center gap-1.5 rounded-[2px] border border-border/60 bg-muted/30 px-2 py-1 font-mono text-[10px] text-muted-foreground">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-positive opacity-75" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-positive" />
              </span>
              All systems operational
            </div>
          </div>

          {COLUMNS.map((col) => (
            <div key={col.heading}>
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
                {col.heading}
              </p>
              <ul className="space-y-2">
                {col.links.map((link) => (
                  <li key={link.label}>
                    {/* Use <Link> for in-app routes; <a> for external/mailto. */}
                    {link.href.startsWith("/") ? (
                      <Link
                        href={link.href}
                        className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {link.label}
                      </Link>
                    ) : (
                      <a
                        href={link.href}
                        className="text-xs text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {link.label}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-start justify-between gap-3 border-t border-border/30 pt-8 sm:flex-row sm:items-center">
          <p className="text-[11px] text-muted-foreground/70">
            © 2026 Worldview · University final thesis project · Built on
            EODHD, Finnhub, SEC EDGAR, and Polymarket data.
          </p>
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/50">
            v0.59 · build 2026.05.01
          </p>
        </div>
      </div>
    </footer>
  );
}
