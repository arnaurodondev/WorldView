/**
 * components/landing/LandingNav.tsx — sticky landing navigation
 *
 * WHY THIS EXISTS: The landing page needs a sticky top nav with section
 * anchors and the auth CTAs. Lives in its own component so the marketing
 * nav doesn't leak into authenticated routes (which use the AppShell sidebar
 * instead, not a top nav).
 *
 * WHY SERVER COMPONENT: pure render, no client state. Anchor links scroll
 * via native browser behavior; no JS required.
 */

import Link from"next/link";

const NAV_ITEMS: Array<{ label: string; href: string }> = [
 { label:"Differentiators", href:"/#differentiators" },
 { label:"Workflow", href:"/#workflow" },
 { label:"AI", href:"/#ai" },
 { label:"Compare", href:"/#compare" },
 { label:"Pricing", href:"/#pricing" },
 { label:"FAQ", href:"/#faq" },
];

export function LandingNav() {
 return (
 <nav
 aria-label="Primary"
 className="sticky top-0 z-40 border-b border-border/40 bg-background/85 backdrop-blur-md"
 >
 {/* Skip-to-main link — WCAG 2.4.1. Visually hidden until keyboard focus
 lands on it; then becomes a regular focusable button at the top of
 the nav. Targets `#hero` (the first content section). Added in
 PLAN-0052 Wave A QA iter-1. */}
 <a
 href="#hero"
 className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-[2px] focus:bg-primary focus:px-3 focus:py-1.5 focus:font-mono focus:text-[11px] focus:font-semibold focus:text-primary-foreground"
 >
 Skip to main content
 </a>
 <div className="mx-auto flex max-w-7xl items-center justify-between gap-[24px] px-6 py-3 lg:px-8">
 {/* Brand mark — always returns to landing root */}
 <Link
 href="/"
 className="flex items-baseline gap-2 text-foreground"
 >
 <span className="font-mono text-[16px] font-semibold tracking-tight">
 Worldview
 </span>
 <span className="hidden font-mono text-[10px] uppercase tracking-wider text-muted-foreground sm:inline">
 terminal
 </span>
 </Link>

 {/* WHY hidden on mobile (lg:flex): inline anchor list reads as clutter
 on small screens; at lg+ width it gives visitors a quick TOC for
 the long marketing page. We rely on the visible CTAs (Sign In /
 Get Started) for mobile actions. */}
 <ul className="hidden items-center gap-7 lg:flex">
 {NAV_ITEMS.map((item) => (
 <li key={item.href}>
 <a
 href={item.href}
 className="text-xs text-muted-foreground transition-colors hover:text-foreground"
 >
 {item.label}
 </a>
 </li>
 ))}
 </ul>

 <div className="flex items-center gap-2">
 <Link
 href="/docs"
 className="hidden rounded-[2px] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground sm:inline-flex"
 >
 Docs
 </Link>
 <Link
 href="/login"
 className="rounded-[2px] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
 >
 Sign in
 </Link>
 <Link
 href="/register"
 className="inline-flex items-center rounded-[2px] bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition-color-only hover:bg-primary/90"
 >
 Get started
 </Link>
 </div>
 </div>
 </nav>
 );
}
