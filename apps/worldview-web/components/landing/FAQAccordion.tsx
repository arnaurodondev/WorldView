/**
 * components/landing/FAQAccordion.tsx — landing FAQ (T-A-1-11)
 *
 * WHY THIS EXISTS: An FAQ block at the bottom of the landing page absorbs
 * the lingering questions a high-intent visitor still has after scrolling
 * everything else. It's also good SEO — search engines surface FAQ snippets
 * in result pages.
 *
 * WHY ACCORDION (vs. flat Q+A): 8-10 questions flat would push the final CTA
 * below the fold on mobile. Accordion keeps the page short while letting
 * users expand only the questions that matter to them.
 */

"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

interface FAQ {
  q: string;
  a: string;
}

const FAQS: FAQ[] = [
  // 2026-07 landing rework: launch framing — lead with "real, live product",
  // keep the research origin as the honest second beat. MUST stay in lockstep
  // with FAQ_JSONLD in app/page.tsx (structured-data parity, see that file).
  {
    q: "Is Worldview a real product or a research demo?",
    a: "It's a real, live product — a working terminal with 10 production microservices, a Next.js frontend, and live data integrations. It began as a university research project, and that research DNA is why every AI answer must be grounded and cited. You can sign up free and use it today.",
  },
  {
    q: "What data sources do you actually use?",
    a: "EODHD for end-of-day and intraday equities, Finnhub for fundamentals and corporate events, SEC EDGAR for filings, Polymarket for prediction-market odds, and TastyTrade (read-only) for brokerage sync. All sources are listed in the data-sources docs.",
  },
  {
    q: "Where do my data and queries go? Is my brokerage data sold?",
    a: "No data is sold. Brokerage sync is read-only and the access token never leaves the platform. Articles and chat queries are processed against externalized LLM endpoints (DeepInfra) — we send the prompt and store the response; nothing else. Full data flow is documented in the security FAQ.",
  },
  {
    q: "How accurate is the AI? Does it hallucinate tickers or numbers?",
    a: "Every AI answer is grounded in retrieval — articles, filings, and structured data points retrieved from your subscribed sources. The model cites the source for each claim; if it can't ground a claim, it says so. We don't ship answers without citations.",
  },
  {
    q: "How does the graph find indirect relationships between companies?",
    a: "Every article and filing is run through entity extraction and relation extraction, building a knowledge graph of typed edges (supplied_by, equipment_from, regulated_by, executive_of, …) over ~80K canonical entities. To connect two names, we run a variable-length path search over the graph and rank the resulting chains by a weirdness score — reliability × unexpectedness × semantic-distance × novelty — so the most surprising, non-obvious connections surface first (e.g. Apple → TSMC → ASML).",
  },
  {
    q: "Can I trust the news impact scores?",
    a: "The impact score is the model's prediction of price movement in the 4 windows after publication (t0/t1/t2/t5). It's based on price-window labelling against a curated training set. We expose the underlying t0/t1/t2/t5 returns so you can verify the model against real outcomes.",
  },
  {
    q: "Do you support real-time data?",
    a: "Yes on Pro and Enterprise. The free tier uses 15-min delayed quotes (sufficient for end-of-day analysis and screening). Pro upgrades to live tick data via EODHD's WebSocket feed.",
  },
  {
    q: "Can I export to CSV / connect to my own scripts?",
    a: "Yes. Every list view (screener, watchlists, transactions, alerts) has CSV / Excel / PDF export. The S9 API gateway exposes 55+ documented endpoints so you can pull data into Python / Jupyter / Excel directly. API access is included on Pro and Enterprise tiers.",
  },
  {
    q: "What if I don't have a brokerage to connect?",
    a: "You don't need one. The terminal is fully usable for research, screening, alerts, and news intelligence without a connected brokerage. The brokerage sync is purely an optional convenience for tracking real positions alongside research.",
  },
  {
    q: "Is there a free trial for Pro?",
    a: "Yes — 14 days, no credit card required. After 14 days your account reverts to the Free tier automatically (you'll never be charged without explicit confirmation).",
  },
  {
    q: "How do I report a bug or request a feature?",
    a: "Use the floating feedback button in the bottom-right of any authenticated page. Bugs, feature requests, and roadmap voting all flow into the public roadmap at /feedback. Direct contact: hello@worldview-labs.com.",
  },
];

export function FAQAccordion() {
  return (
    <section
      id="faq"
      aria-labelledby="faq-heading"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-3xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mb-10 text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Frequently asked
          </p>
          <h2
            id="faq-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Everything else you might be wondering.
          </h2>
        </div>

        <Accordion type="single" collapsible className="w-full">
          {FAQS.map((item, i) => (
            <AccordionItem key={item.q} value={`faq-${i}`}>
              <AccordionTrigger>{item.q}</AccordionTrigger>
              <AccordionContent>{item.a}</AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>

        <p className="mt-10 text-center text-xs text-muted-foreground">
          Didn&apos;t find your answer?{" "}
          <a
            href="mailto:hello@worldview-labs.com"
            className="text-primary hover:underline"
          >
            hello@worldview-labs.com
          </a>
        </p>
      </div>
    </section>
  );
}
