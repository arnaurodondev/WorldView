/**
 * components/landing/BetaAccess.tsx — beta-access callout (replaces PricingTiers)
 *
 * WHY THIS EXISTS: The old PricingTiers section advertised paid Free / Pro /
 * Enterprise tiers with dollar amounts, a 14-day trial, and "real-time on Pro"
 * gating — none of which is backed by a real billing system. Showing invented
 * prices to real, paying-attention finance users is a trust-killer (and, on a
 * live product, arguably deceptive). The 2026-07 launch rework removes all of
 * that and replaces it with the single honest message: the product is free
 * during beta, no card required, everything unlocked.
 *
 * WHY SERVER COMPONENT (was "use client"): the pricing card needed React state
 * for the monthly/annual toggle. This callout is fully static, so it ships zero
 * client JavaScript and pre-renders at build time — faster and simpler.
 *
 * WHY id="access" (was id="pricing"): the section no longer sells anything, so
 * "pricing" would be a misleading anchor. LandingNav + Footer point here with
 * an "Access" label instead.
 *
 * WHY WE STILL KEEP A SECTION (rather than deleting outright): high-intent
 * visitors expect a "what does it cost?" answer before they sign up. Answering
 * it plainly ("free, no card") removes the objection more effectively than an
 * absent section, and gives the long page a natural pre-CTA beat.
 */

import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";

// What a beta account unlocks. WHY no tiers: during beta everyone gets the
// same access — this is the list of real, shipping surfaces (verified against
// docs/PRODUCT_CONTEXT.md journeys J1–J10), NOT a paywall matrix.
const INCLUDED: string[] = [
  "Full market data, charts & fundamentals",
  "Grounded AI research chat with citations",
  "Knowledge graph & entity path discovery",
  "Screener, watchlists, portfolio & alerts",
  "Read-only brokerage sync (optional)",
  "S9 API access — 55+ documented endpoints",
];

export function BetaAccess() {
  return (
    <section
      id="access"
      aria-labelledby="access-heading"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-4xl px-6 py-20 lg:px-8 lg:py-24">
        {/* The callout card — a single centered panel with a subtle primary
            wash so it reads as the page's "offer", not just another band. */}
        <div className="relative overflow-hidden rounded-[2px] border border-primary/40 bg-card p-8 shadow-lg shadow-primary/10 lg:p-12">
          {/* Soft radial glow anchored top-right — same ambient-light language
              as the hero, ties the page's first and last "offer" moments. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 [background:radial-gradient(70%_60%_at_90%_-10%,hsl(var(--primary)/0.10)_0%,transparent_60%)]"
          />

          <div className="relative">
            {/* Beta badge — sets honest expectations before the headline. */}
            <p className="mb-4 inline-flex items-center gap-2 rounded-[2px] border border-primary/40 bg-primary/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.18em] text-primary">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" />
              Public beta
            </p>

            <h2
              id="access-heading"
              className="mb-3 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
            >
              Free while we&apos;re in beta.
            </h2>
            <p className="mb-8 max-w-xl text-base leading-relaxed text-muted-foreground">
              Every feature is unlocked, with no credit card and no trial timer.
              We&apos;re building in the open and want your feedback — pricing
              comes later, and we&apos;ll give plenty of notice before anything
              changes.
            </p>

            {/* Two-column inclusion list — proof that "free" means the whole
                product, not a stripped demo. Single column on mobile. */}
            <ul className="mb-9 grid grid-cols-1 gap-x-8 gap-y-2.5 sm:grid-cols-2">
              {INCLUDED.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2.5 text-sm text-muted-foreground"
                >
                  <Check
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive"
                    aria-hidden="true"
                  />
                  <span>{item}</span>
                </li>
              ))}
            </ul>

            {/* CTA pair — mirrors the hero so the page's action is consistent
                end to end. Primary → register, secondary → sign in. */}
            <div className="flex flex-wrap items-center gap-3">
              <Link
                href="/register"
                data-testid="access-primary-cta"
                className="group inline-flex items-center gap-2 rounded-[2px] bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30"
              >
                Create your free account
                <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </Link>
              <Link
                href="/login"
                className="inline-flex items-center gap-2 rounded-[2px] border border-border/60 px-6 py-3 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                Sign in
              </Link>
            </div>

            <p className="mt-5 font-mono text-[11px] text-muted-foreground/70">
              No credit card · cancel anytime · your data is never sold
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
