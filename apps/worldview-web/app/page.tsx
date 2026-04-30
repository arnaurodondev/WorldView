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

/**
 * JSON-LD Organization schema — surfaced in Google's knowledge panel and
 * sitelinks. Keep it short; Google will infer the rest from page content.
 */
const ORG_JSONLD = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "Worldview",
  alternateName: "Worldview Terminal",
  url: "https://worldview.local",
  logo: "https://worldview.local/icon-512.png",
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
  url: "https://worldview.local",
};

/**
 * JSON-LD FAQPage — Google indexes FAQPage schema for rich snippet results.
 * Mirrors the FAQAccordion entries to keep the page authoritative.
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
        text: "Both. It's a fully working terminal with 10 production microservices, a Next.js frontend, and live data integrations — built as a university final thesis.",
      },
    },
    {
      "@type": "Question",
      name: "What data sources does Worldview use?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "EODHD for equities, Finnhub for fundamentals, SEC EDGAR for filings, Polymarket for prediction markets, and TastyTrade (read-only) for brokerage sync.",
      },
    },
    {
      "@type": "Question",
      name: "Is there a free tier?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Yes. Free tier includes 15-min delayed quotes, 1 watchlist (25 instruments), 5 saved screens, 10 alerts, and 50 AI queries per month — no credit card required.",
      },
    },
  ],
};

export default function LandingPage() {
  return (
    <>
      {/* Structured data — see comments above each constant for purpose. */}
      <script
        type="application/ld+json"
        // dangerouslySetInnerHTML is the canonical Next.js pattern for JSON-LD;
        // strings are safe because we control the input fully.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(ORG_JSONLD) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(SITE_JSONLD) }}
      />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(FAQ_JSONLD) }}
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
