/**
 * components/landing/HeroSection.tsx — landing page hero (T-A-1-01)
 *
 * WHY THIS EXISTS: The first 600px of the landing page must (a) name the
 * product, (b) state the value, (c) give two CTAs, and (d) prove the product
 * is real with a live-feeling terminal mock — all above the fold.
 *
 * WHY SERVER COMPONENT: Fully static; pre-rendered at build time for fast TTFB.
 * The "animation" is pure CSS (animate-pulse on the live dot, transition on
 * hover) — no client JavaScript needed.
 *
 * COMPETITIVE BENCHMARK: Bloomberg.com, IBKR, TradingView all open with a tag
 * line + 2 CTAs + product visual. The terminal mock sets us apart from
 * generic SaaS landing pages by signalling "professional tool, not a toy".
 *
 * DESIGN REFERENCE:
 *   PLAN-0052 Wave A T-A-1-01
 *   docs/audits/2026-04-28-qa-frontend-design-roadmap.md PART B (Phase 4)
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ProductShot } from "./ProductShot";
import { IntelligenceTabMock } from "./mocks";

export function HeroSection() {
  return (
    <section
      id="hero"
      // WHY pt-20 not pt-14: the sticky nav is 56px tall; this gives the hero
      // breathing room below it on desktop without crowding mobile.
      // WHY relative + overflow-hidden: anchor the radial gradient ::before
      // glow inside the section without leaking into adjacent sections.
      className="relative overflow-hidden border-b border-border/40 bg-background"
    >
      {/* WHY two radial glows (top-right + bottom-left): asymmetric ambient light
          gives depth without using a hard background image. The amber tint at top
          right hints at the brand color; the negative-space at bottom-left
          mirrors the data-density message. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 [background:radial-gradient(80%_60%_at_85%_-10%,hsl(var(--primary)/0.08)_0%,transparent_60%),radial-gradient(60%_50%_at_-10%_120%,hsl(var(--positive)/0.05)_0%,transparent_60%)]"
      />

      <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-6 py-20 lg:grid-cols-[minmax(0,1fr),minmax(0,1.1fr)] lg:gap-20 lg:px-8 lg:py-24">
        {/* ── Left column: copy + CTAs ──────────────────────────────────── */}
        <div>
          {/* Eyebrow / kicker — sets product category before the heading.
              Mono small caps mirrors Bloomberg / Refinitiv style guides. */}
          <p className="mb-5 inline-flex items-center gap-2 rounded-[2px] border border-border/60 bg-muted/40 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
            </span>
            Market Intelligence Terminal
          </p>

          {/* WHY this headline structure: short product name first; secondary
              line tells the user what they get. Tested copy pattern from
              Bloomberg Pro, IBKR, and TradingView landing pages. */}
          <h1 className="mb-6 text-4xl font-semibold leading-[1.05] tracking-tight text-foreground sm:text-5xl lg:text-[3.5rem]">
            Bloomberg-grade research,
            <br />
            <span className="text-primary">without the Bloomberg bill.</span>
          </h1>

          <p className="mb-8 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            A finance terminal that fuses market data, impact-scored news, and
            an entity knowledge graph — with a grounded AI assistant that cites
            every claim and a graph that surfaces the connections you&apos;d
            never think to search for.
          </p>

          {/* ── CTA pair ───────────────────────────────────────────────── */}
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/register"
              data-testid="hero-primary-cta"
              className="group inline-flex items-center gap-2 rounded-[2px] bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30"
            >
              Open the terminal free
              <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
            </Link>

            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-[2px] border border-border/60 px-6 py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
            >
              Sign in
            </Link>
          </div>

          {/* Sub-CTA explainer — short risk-reduction copy under the CTAs.
              Conversion best practice: address the "what's the catch?" thought. */}
          {/* QA iter-1 (a11y M3): bumped opacity from /70 → default
              text-muted-foreground for AA contrast on this informational
              sub-CTA copy. */}
          <p className="mt-5 text-xs text-muted-foreground">
            No credit card · 5-minute setup · Free tier included
          </p>
        </div>

        {/* ── Right column: real product screenshot ─────────────────────── */}
        {/* WHY a screenshot (not the old ASCII mock): the redesign (§2) shows
            rather than tells — a real crop of the instrument Intelligence tab
            (entity graph + relations) proves the flagship capability above the
            fold. The reusable ProductShot wraps it in window chrome + LIVE pill
            so it still reads as a real terminal. Captured by
            capture-landing-shots.mjs → public/landing/hero-intelligence.png. */}
        <div className="relative">
          {/* WHY -inset-2 + blur: subtle amber halo behind the card lifts it
              off the page without resorting to drop-shadow which often looks
              cheap on dark backgrounds. */}
          <div
            aria-hidden
            className="pointer-events-none absolute -inset-2 rounded-[2px] bg-primary/10 opacity-50 blur-2xl"
          />

          <ProductShot
            src="/landing/hero-intelligence.png"
            alt="Stylized preview of the Worldview instrument Intelligence tab: an entity knowledge graph with the Apple to TSMC to ASML supply-chain path highlighted, alongside Apple's top related entities (sample data)."
            label="intelligence"
            width={640}
            height={440}
            live
            priority
            // 2026-07 landing rework: hand-built CSS/SVG illustration until
            // capture-landing-shots.mjs produces the real production PNG —
            // never show "screenshot pending capture" to real visitors.
            // TODO(landing-shots): drop `mock` once the capture pipeline runs.
            mock={<IntelligenceTabMock />}
          />
        </div>
      </div>
    </section>
  );
}
