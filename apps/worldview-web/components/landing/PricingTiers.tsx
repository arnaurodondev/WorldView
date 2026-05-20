/**
 * components/landing/PricingTiers.tsx — 3-tier pricing card (T-A-1-09)
 *
 * WHY THIS EXISTS: Even on a thesis project, pricing tiers communicate
 *"this is a real product, not a demo". They also let us show a free tier
 * up front to remove price as a sign-up objection.
 *
 * WHY 3 TIERS (not 4): canonical SaaS pattern — Free → Pro → Enterprise.
 * Three is the highest-converting count (Hick's law: more options = more
 * paralysis). Pro is highlighted as the recommended tier per industry
 * pricing-page best practice (Stripe, Linear, Vercel all do this).
 *
 * WHY CLIENT COMPONENT: the monthly/annual toggle requires React state.
 * Everything else (copy, CTA hrefs) is static and hydrates from props.
 */

"use client";

import { useState } from"react";
import Link from"next/link";
import { Check } from"lucide-react";

type Billing ="monthly" |"annual";

interface Tier {
 name: string;
 tagline: string;
 // Prices are intentionally illustrative for the thesis demo;
 // annual saves 17% (matches industry-standard ~2-month-free framing).
 monthly: number;
 annual: number;
 cta: { label: string; href: string };
 features: string[];
 highlight?: boolean;
}

const TIERS: Tier[] = [
 {
 name:"Free",
 tagline:"Everything a serious retail trader needs to evaluate the product.",
 monthly: 0,
 annual: 0,
 cta: { label:"Get started", href:"/register" },
 features: [
"Real-time market data (15-min delay)",
"1 watchlist · up to 25 instruments",
"5 saved screens · 10 alerts",
"AI chat · 50 queries / month",
"Community Discord & docs",
 ],
 },
 {
 name:"Pro",
 tagline:"For active traders and analysts running daily research workflows.",
 monthly: 29,
 annual: 24, // 24 × 12 = 288/yr ≈ 17% off vs 29 × 12 = 348
 cta: { label:"Start 14-day trial", href:"/register?plan=pro" },
 features: [
"Real-time market data (no delay)",
"Unlimited watchlists & screens",
"Unlimited alerts · all channels",
"AI chat · 1,000 queries / month",
"Brokerage sync (TastyTrade)",
"Knowledge graph queries",
"Priority support · email + chat",
 ],
 highlight: true,
 },
 {
 name:"Enterprise",
 tagline:"Teams, funds, and institutions with custom data and access controls.",
 monthly: 0, // 0 sentinel ="Custom"
 annual: 0,
 cta: { label:"Talk to us", href:"mailto:hello@worldview.local" },
 features: [
"Everything in Pro",
"SSO · SAML · audit logs",
"Multi-tenant workspaces",
"Custom data feeds & vendors",
"On-prem / private cloud option",
"Dedicated account manager",
"SLA-backed uptime",
 ],
 },
];

export function PricingTiers() {
 const [billing, setBilling] = useState<Billing>("annual");

 return (
 <section
 id="pricing"
 aria-labelledby="pricing-heading"
 className="border-b border-border/40 bg-background"
 >
 <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
 <div className="mx-auto mb-10 max-w-2xl text-center">
 <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
 Pricing
 </p>
 <h2
 id="pricing-heading"
 className="text-[30px] font-semibold tracking-tight text-foreground sm:text-[36px]"
 >
 One terminal. No tier-locked data.
 </h2>
 <p className="mt-3 text-[14px] text-muted-foreground">
 Start free with sample data. Upgrade when you&apos;re ready for real-time
 feeds, brokerage sync, and unlimited AI queries.
 </p>
 </div>

 {/* Billing toggle — annual selected by default to anchor on the
 discounted price. Pattern from Linear / Stripe / Vercel.
 WHY aria-pressed (not role="tab"): the buttons toggle a UI mode,
 they don't switch between tabpanels — using role="tab" without
 corresponding role="tabpanel" + aria-controls creates a broken
 ARIA contract (screen readers announce tabs that lead nowhere).
 aria-pressed is the correct idiom for two-state toggle buttons.
 Fixed in PLAN-0052 Wave A QA iter-1. */}
 <div
 role="group"
 aria-label="Billing period"
 className="mb-10 flex items-center justify-center"
 >
 <div className="inline-flex rounded-[2px] border border-border/60 bg-card p-0.5">
 <button
 type="button"
 aria-pressed={billing ==="monthly"}
 onClick={() => setBilling("monthly")}
 className={
"rounded-[2px] px-4 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors" +
 (billing ==="monthly"
 ?"bg-primary text-primary-foreground"
 :"text-muted-foreground hover:text-foreground")
 }
 >
 Monthly
 </button>
 <button
 type="button"
 aria-pressed={billing ==="annual"}
 onClick={() => setBilling("annual")}
 className={
"rounded-[2px] px-4 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors" +
 (billing ==="annual"
 ?"bg-primary text-primary-foreground"
 :"text-muted-foreground hover:text-foreground")
 }
 >
 Annual <span className="ml-1 text-[9px] opacity-70">−17%</span>
 </button>
 </div>
 </div>

 <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
 {TIERS.map((tier) => {
 const price = billing ==="annual" ? tier.annual : tier.monthly;
 const isCustom = tier.name ==="Enterprise";
 return (
 <div
 key={tier.name}
 className={
"relative flex flex-col rounded-[2px] border p-6 transition-color-only" +
 (tier.highlight
 ?"border-primary/50 bg-card"
 :"border-border/40 bg-card hover:border-border/70")
 }
 >
 {tier.highlight ? (
 <span className="absolute -top-3 left-6 rounded-[2px] bg-primary px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-primary-foreground">
 Most popular
 </span>
 ) : null}

 <h3 className="mb-2 text-[18px] font-semibold text-foreground">
 {tier.name}
 </h3>
 <p className="mb-5 min-h-[40px] text-[14px] leading-relaxed text-muted-foreground">
 {tier.tagline}
 </p>

 <div className="mb-5 flex items-baseline gap-1">
 {isCustom ? (
 <span className="text-[30px] font-semibold tracking-tight text-foreground">
 Custom
 </span>
 ) : (
 <>
 <span className="font-mono text-[36px] font-semibold tabular-nums tracking-tight text-foreground">
 ${price}
 </span>
 {/* QA iter-1: $0 has no annual concept — show"/mo"
 regardless of billing toggle for the Free tier. */}
 <span className="font-mono text-xs text-muted-foreground">
 /
 {price === 0 || billing ==="monthly"
 ?"mo"
 :"mo billed annually"}
 </span>
 </>
 )}
 </div>

 <Link
 href={tier.cta.href}
 className={
"mb-6 inline-flex items-center justify-center rounded-[2px] px-4 py-2.5 text-[14px] font-medium transition-colors" +
 (tier.highlight
 ?"bg-primary text-primary-foreground shadow hover:bg-primary/90"
 :"border border-border/60 text-foreground hover:border-primary/40 hover:text-primary")
 }
 >
 {tier.cta.label}
 </Link>

 <ul className="space-y-2.5 text-[14px]">
 {tier.features.map((f) => (
 <li
 key={f}
 className="flex items-start gap-2 text-muted-foreground"
 >
 <Check
 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-positive"
 aria-hidden="true"
 />
 <span>{f}</span>
 </li>
 ))}
 </ul>
 </div>
 );
 })}
 </div>
 </div>
 </section>
 );
}
