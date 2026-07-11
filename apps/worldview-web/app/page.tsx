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
 * The one interactive section (FAQAccordion) is isolated as a "use client"
 * leaf so the rest of the page ships zero JS to the client. (The former
 * PricingTiers "use client" toggle was removed in the 2026-07 launch rework —
 * see BetaAccess.tsx.)
 *
 * WHY JSON-LD INLINE: Search engines (Google, Bing) index Organization
 * schema for sitelinks and rich knowledge-panel results. Embedding the JSON
 * directly in the page is the recommended approach per
 * developers.google.com/search/docs/appearance/structured-data.
 *
 * SECTION ORDER (top to bottom) — refreshed by the 2026-06-23 landing
 * redesign (docs/design/2026-06-23-landing-page-redesign.md §6). The three
 * flagship "show, don't tell" showcases are FeatureGrid, KnowledgeGraph-
 * Spotlight, and the refreshed AIDemoSection; HowItWorks adds architecture
 * credibility.
 *   1. LandingNav            — sticky nav with section anchors + auth CTAs
 *   2. HeroSection           — tagline + 2 CTAs + real product screenshot
 *   3. LiveDataStrip         — 6 mock tickers with live-pulse dot
 *   4. SectorHeatmapPreview  — 6 SPDR sector tiles using shared 7-step gradient
 *   5. FeatureGrid           — six-surface map (replaces DifferentiatorsSection)
 *   6. KnowledgeGraphSpotlight — flagship KG + weird-connections showcase
 *   7. AIDemoSection         — grounded chat: slash-commands + cited answer +
 *                              citation-confidence bar
 *   8. WorkflowSection       — 4-step Discover → Analyze → Track → Act
 *   9. HowItWorks            — hybrid-retrieval pipeline + 4 credibility pillars
 *  10. ComparisonTable       — Worldview vs Bloomberg / IBKR / TV / Finviz
 *  11. TrustBadges           — data-source attributions
 *  12. BetaAccess           — "free during beta, no card" access callout
 *  13. Testimonials          — 3 persona scenarios (no fake customer quotes)
 *  14. FAQAccordion          — 11 hardcoded Q&A
 *  15. FinalCTA              — closing "open the terminal" CTA
 *  16. Footer                — 5-column secondary nav + status badge
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md;
 * PLAN-0052 §Wave A (original).
 */

import { headers } from "next/headers";
import { LandingNav } from "@/components/landing/LandingNav";
import { HeroSection } from "@/components/landing/HeroSection";
import { LiveDataStrip } from "@/components/landing/LiveDataStrip";
import { SectorHeatmapPreview } from "@/components/landing/SectorHeatmapPreview";
import { FeatureGrid } from "@/components/landing/FeatureGrid";
import { KnowledgeGraphSpotlight } from "@/components/landing/KnowledgeGraphSpotlight";
import { WorkflowSection } from "@/components/landing/WorkflowSection";
import { AIDemoSection } from "@/components/landing/AIDemoSection";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { ComparisonTable } from "@/components/landing/ComparisonTable";
import { TrustBadges } from "@/components/landing/TrustBadges";
import { BetaAccess } from "@/components/landing/BetaAccess";
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
    "Market intelligence terminal that fuses real-time market data, impact-scored news, and an entity knowledge graph with a grounded, citation-backed AI assistant. Knowledge-graph path discovery, portfolio analytics, and a fundamentals screener in one workspace.",
  // 2026-07 landing rework: removed the placeholder sameAs entry — a bare
  // "https://github.com" is structured-data noise Google treats as a broken
  // profile link. Re-add real profile URLs (GitHub org, X, LinkedIn) when
  // they exist.
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
 * 2026-06-23 landing redesign: added the knowledge-graph path-discovery Q&A
 * (11 total) — kept in lockstep with FAQAccordion.tsx for parity.
 */
const FAQ_JSONLD = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "Is Worldview a real product or a research demo?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "It's a real, live product — a working terminal with 10 production microservices, a Next.js frontend, and live data integrations. It began as a university research project, and that research DNA is why every AI answer must be grounded and cited. You can sign up free and use it today.",
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
      name: "How does the graph find indirect relationships between companies?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Every article and filing is run through entity and relation extraction, building a knowledge graph of typed edges (supplied_by, equipment_from, regulated_by, executive_of, …) over ~80K canonical entities. To connect two names, we run a variable-length path search over the graph and rank the chains by a weirdness score — reliability × unexpectedness × semantic-distance × novelty — so the most surprising, non-obvious connections surface first (e.g. Apple → TSMC → ASML).",
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
      name: "What does the data cover?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "End-of-day and intraday equities from EODHD, fundamentals and corporate events from Finnhub, filings from SEC EDGAR, and prediction-market odds from Polymarket. Inside the app, market data refreshes on a short delay — plenty for research, screening, and end-of-day analysis.",
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
      name: "How much does it cost?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Nothing right now. Worldview is in public beta — every feature is unlocked with no credit card and no trial timer. Paid plans will come later, and we'll give plenty of notice before anything changes; you'll never be charged without explicit confirmation.",
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

export default async function LandingPage() {
  // PLAN-0059 I-6: middleware sets a per-request CSP nonce in the request
  // headers. We attach it to the inline JSON-LD scripts so they pass the
  // strict-dynamic script-src directive. application/ld+json type is
  // structured-data not executable, but modern browsers still enforce CSP
  // on it under script-src — the nonce makes that explicit.
  const headerStore = await headers();
  const nonce = headerStore.get("x-nonce") ?? undefined;

  return (
    <>
      {/* Structured data — see comments above each constant for purpose.
          jsonLd() escapes `<` to `<` so a runaway `</script>` token
          in any future payload cannot break out of the inline script tag. */}
      <script
        type="application/ld+json"
        nonce={nonce}
        dangerouslySetInnerHTML={{ __html: jsonLd(ORG_JSONLD) }}
      />
      <script
        type="application/ld+json"
        nonce={nonce}
        dangerouslySetInnerHTML={{ __html: jsonLd(SITE_JSONLD) }}
      />
      <script
        type="application/ld+json"
        nonce={nonce}
        dangerouslySetInnerHTML={{ __html: jsonLd(FAQ_JSONLD) }}
      />

      <main className="min-h-screen bg-background text-foreground">
        <LandingNav />
        <HeroSection />
        <LiveDataStrip />
        <SectorHeatmapPreview />
        <FeatureGrid />
        <KnowledgeGraphSpotlight />
        <AIDemoSection />
        <WorkflowSection />
        <HowItWorks />
        <ComparisonTable />
        <TrustBadges />
        <BetaAccess />
        <Testimonials />
        <FAQAccordion />
        <FinalCTA />
        <Footer />
      </main>
    </>
  );
}
