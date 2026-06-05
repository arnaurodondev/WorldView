/**
 * components/landing/FinalCTA.tsx — bottom-of-page conversion CTA
 *
 * WHY THIS EXISTS: High-intent visitors who scrolled the entire landing page
 * should not need to scroll back up to the hero CTA to convert. Mirrors the
 * hero CTA visually so visual rhythm carries through to the final action.
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function FinalCTA() {
  return (
    <section
      aria-labelledby="final-cta-heading"
      className="relative overflow-hidden border-b border-border/40 bg-background"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 [background:radial-gradient(60%_60%_at_50%_50%,hsl(var(--primary)/0.08)_0%,transparent_70%)]"
      />
      <div className="relative mx-auto max-w-3xl px-6 py-24 text-center lg:px-8">
        <h2
          id="final-cta-heading"
          className="mb-4 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
        >
          Ready to trade with intelligence?
        </h2>
        <p className="mb-10 text-base text-muted-foreground">
          Open the terminal in 5 minutes — no credit card, no demo request,
          no waitlist.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/register"
            data-testid="final-primary-cta"
            className="group inline-flex items-center gap-2 rounded-[2px] bg-primary px-7 py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/25 transition-all hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30"
          >
            Open the terminal free
            <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 rounded-[2px] border border-border/60 px-7 py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
          >
            Sign in
          </Link>
        </div>
      </div>
    </section>
  );
}
