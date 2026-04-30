/**
 * app/page.tsx — Public landing page (PLAN-0052 Wave A)
 *
 * WHY THIS EXISTS: The root route "/" is the unauthenticated marketing
 * surface. PLAN-0052 Wave A redesigns it as 11 sections benchmarked against
 * Bloomberg.com / IBKR / TradingView / Finviz, with explicit competitive
 * differentiation (knowledge graph, AI-grounded research, prediction
 * markets, multi-source fusion) over generic "AI-powered" claims.
 *
 * WHY SERVER COMPONENT: All sections are static; pre-rendered at build time.
 * The two interactive sections (PricingTiers monthly/annual toggle,
 * FAQAccordion) are isolated as "use client" leaves so the rest of the page
 * ships zero JS to the client.
 *
 * WHY JSON-LD INLINE: Search engines (Google, Bing) index Organization
 * schema for sitelinks and rich knowledge-panel results. Embedding the JSON
 * directly in the page is the recommended approach per
 * developers.google.com/search/docs/appearance/structured-data.
 *
 * SECTION ORDER (top to bottom):
 *   1. LandingNav         — sticky nav with section anchors + auth CTAs
 *   2. HeroSection        — tagline + 2 CTAs + animated terminal mock
 *   3. LiveDataStrip      — 6 mock tickers with live-pulse dot
 *   4. SectorHeatmapPreview — 6 SPDR sector tiles using shared 7-step gradient
 *   5. DifferentiatorsSection — 3-column News / KG / Multi-source
 *   6. WorkflowSection    — 4-step Discover → Analyze → Track → Act
 *   7. AIDemoSection      — example Q + cited answer + sources box
 *   8. ComparisonTable    — Worldview vs Bloomberg / IBKR / TV / Finviz
 *   9. TrustBadges        — data-source attributions
 *  10. PricingTiers       — Free / Pro / Enterprise + monthly/annual toggle
 *  11. Testimonials       — 3 persona scenarios (no fake customer quotes)
 *  12. FAQAccordion       — 10 hardcoded Q&A
 *  13. FinalCTA           — closing "open the terminal" CTA
 *  14. Footer             — 5-column secondary nav + status badge
 *
 * DESIGN REFERENCE: PLAN-0052 §Wave A; docs/audits/2026-04-28-qa-frontend-design-roadmap.md
 */

import { LandingNav } from "@/components/landing/LandingNav";
import { HeroSection } from "@/components/landing/HeroSection";
import { LiveDataStrip } from "@/components/landing/LiveDataStrip";
import { SectorHeatmapPreview } from "@/components/landing/SectorHeatmapPreview";
import { DifferentiatorsSection } from "@/components/landing/DifferentiatorsSection";
import { WorkflowSection } from "@/components/landing/WorkflowSection";
import { AIDemoSection } from "@/components/landing/AIDemoSection";
import { ComparisonTable } from "@/components/landing/ComparisonTable";
import { TrustBadges } from "@/components/landing/TrustBadges";
import { PricingTiers } from "@/components/landing/PricingTiers";
import { Testimonials } from "@/components/landing/Testimonials";
import { FAQAccordion } from "@/components/landing/FAQAccordion";
import { FinalCTA } from "@/components/landing/FinalCTA";
import { Footer } from "@/components/landing/Footer";

// QA iter-1 (SEO M2): thread NEXT_PUBLIC_SITE_URL into JSON-LD so prod
// schema URLs match canonical sitemap baseUrl. Keep `worldview.local` as
// the dev fallback — same convention used by sitemap.ts and robots.ts.
const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "https://worldview.local";

/**
 * JSON-LD Organization schema — surfaced in Google's knowledge panel and
 * sitelinks. Keep it short; Google will infer the rest from page content.
 */
const ORG_JSONLD = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "Worldview",
  alternateName: "Worldview Terminal",
  url: SITE_URL,
  logo: `${SITE_URL}/icon-512.png`,
  description:
    "Bloomberg-grade market intelligence terminal. Real-time market data, AI-powered news intelligence, knowledge graph, and prediction markets in one workspace.",
  sameAs: ["https://github.com"],
};

/**
 * JSON-LD WebSite schema — enables Google's Sitelinks Search Box if
 * we ever expose a /search route. Harmless to include now.
 */
const SITE_JSONLD = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Worldview",
  url: SITE_URL,
};

/**
 * JSON-LD FAQPage — Google indexes FAQPage schema for rich snippet results.
 * Mirrors ALL FAQAccordion entries to keep the page authoritative.
 *
 * QA iter-1 (SEO M1): expanded from 3 → 10 entries to match the visible
 * FAQAccordion. Google penalises structured-data / page-content mismatches
 * as "structured data misuse" and downranks the rich snippet eligibility.
 */
const FAQ_JSONLD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is Worldview a real product or a thesis demo?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Both. It's a fully working terminal with 10 production microservices, a Next.js frontend, and live data integrations — built as a university final thesis demonstrating modern microservice architecture and AI integration. You can sign up free and use it today.",
      },
    },
    {
      "@type": "Question",
      name: "What data sources do you actually use?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "EODHD for end-of-day and intraday equities, Finnhub for fundamentals and corporate events, SEC EDGAR for filings, Polymarket for prediction-market odds, and TastyTrade (read-only) for brokerage sync.",
      },
    },
    {
      "@type": "Question",
      name: "Where do my data and queries go? Is my brokerage data sold?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "No data is sold. Brokerage sync is read-only and the access token never leaves the platform. Articles and chat queries are processed against externalized LLM endpoints; we send the prompt and store the response, nothing else.",
      },
    },
    {
      "@type": "Question",
      name: "How accurate is the AI? Does it hallucinate tickers or numbers?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Every AI answer is grounded in retrieval — articles, filings, and structured data points retrieved from your subscribed sources. The model cites the source for each claim; if it can't ground a claim, it says so. We don't ship answers without citations.",
      },
    },
    {
      "@type": "Question",
      name: "Can I trust the news impact scores?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "The impact score is the model's prediction of price movement in the 4 windows after publication (t0/t1/t2/t5). It's based on price-window labelling against a curated training set. We expose the underlying t0/t1/t2/t5 returns so you can verify the model against real outcomes.",
      },
    },
    {
      "@type": "Question",
      name: "Do you support real-time data?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes on Pro and Enterprise. The free tier uses 15-min delayed quotes (sufficient for end-of-day analysis and screening). Pro upgrades to live tick data via EODHD's WebSocket feed.",
      },
    },
    {
      "@type": "Question",
      name: "Can I export to CSV or connect to my own scripts?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. Every list view (screener, watchlists, transactions, alerts) has CSV / Excel / PDF export. The S9 API gateway exposes 55+ documented endpoints so you can pull data into Python / Jupyter / Excel directly.",
      },
    },
    {
      "@type": "Question",
      name: "What if I don't have a brokerage to connect?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "You don't need one. The terminal is fully usable for research, screening, alerts, and news intelligence without a connected brokerage. The brokerage sync is purely an optional convenience.",
      },
    },
    {
      "@type": "Question",
      name: "Is there a free trial for Pro?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes — 14 days, no credit card required. After 14 days your account reverts to the Free tier automatically. You'll never be charged without explicit confirmation.",
      },
    },
    {
      "@type": "Question",
      name: "How do I report a bug or request a feature?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Use the floating feedback button in the bottom-right of any authenticated page. Bugs, feature requests, and roadmap voting all flow into the public roadmap at /feedback.",
      },
    },
  ],
};

/**
 * jsonLd — render JSON-LD as a CSP-safe script with `</` escape so any
 * future content containing `</script>` cannot break out of the script tag.
 *
 * QA iter-1 (bug audit #3 hardening): even though current payloads are
 * pure constants, the escape costs ~zero and prevents a regression vector
 * if dynamic data ever flows into these constants.
 */
function jsonLd(payload: object): string {
  return JSON.stringify(payload).replace(/</g, "\\u003c");
}

export default function LandingPage() {
  return (
    <>
      {/* Structured data — see comments above each constant for purpose.
          jsonLd() escapes `<` to `<` so a runaway `</script>` token
          in any future payload cannot break out of the inline script tag. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(ORG_JSONLD) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(SITE_JSONLD) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(FAQ_JSONLD) }}
      />

      <main className="min-h-screen bg-background text-foreground">
        <LandingNav />
        <HeroSection />
        <LiveDataStrip />
        <SectorHeatmapPreview />
        <DifferentiatorsSection />
        <WorkflowSection />
        <AIDemoSection />
        <ComparisonTable />
        <TrustBadges />
        <PricingTiers />
        <Testimonials />
        <FAQAccordion />
        <FinalCTA />
        <Footer />
      </main>
    </>
  );
}
