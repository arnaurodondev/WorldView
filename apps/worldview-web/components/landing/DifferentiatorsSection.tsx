/**
 * components/landing/DifferentiatorsSection.tsx — 3 differentiators (T-A-1-04)
 *
 * WHY THIS EXISTS: Visitors comparing 5 finance terminals will skim until
 * something differentiates Worldview. We pick the three sharpest claims:
 *   1. News intelligence (impact-scored, not just headline aggregation)
 *   2. Knowledge graph (entity relations, not just stock tickers)
 *   3. Multi-source aggregation (EODHD + SEC + Polymarket + Finnhub fused)
 *
 * Anything more dilutes the message; anything less feels thin.
 *
 * WHY 3 cards (not 4): proven conversion best-practice — 3 columns scan as
 * "complete trio" while 4 reads as "list". Bloomberg, Stripe, Linear all
 * use 3-column differentiator grids on their landing pages.
 */

import { Sparkles, Network, Layers } from "lucide-react";

const DIFFERENTIATORS = [
  {
    icon: Sparkles,
    title: "News intelligence, not aggregation",
    body: "Every headline gets a market-impact score driven by NLP relevance + price-window labelling. Surface stories that actually move a stock — not the 200 daily duplicates.",
    proofPoint: "10K+ articles/day · price impact in 4 windows (t0/t1/t2/t5)",
  },
  {
    icon: Network,
    title: "Knowledge graph over flat tickers",
    body: "Companies, executives, suppliers, regulators, and prediction markets connected as a queryable graph. Ask 'what relates to NVDA earnings risk?' instead of bouncing between 6 tabs.",
    proofPoint: "AGE graph extension · ~80K canonical entities · Cypher queries",
  },
  {
    icon: Layers,
    title: "Multi-source data fusion",
    body: "EODHD market data, SEC EDGAR filings, Finnhub fundamentals, Polymarket prediction odds — fused into a single timeline per entity. One coherent view, not five logins.",
    proofPoint: "5 vendors · single GraphQL gateway · sub-second cross-source joins",
  },
] as const;

export function DifferentiatorsSection() {
  return (
    <section
      id="differentiators"
      aria-labelledby="differentiators-heading"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            What&apos;s different
          </p>
          <h2
            id="differentiators-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Three things every other terminal gets wrong.
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {DIFFERENTIATORS.map((d) => {
            const Icon = d.icon;
            return (
              <div
                key={d.title}
                className="group flex flex-col rounded-[2px] border border-border/40 bg-card p-6 transition-colors hover:border-primary/30"
              >
                <Icon
                  className="mb-5 h-5 w-5 text-primary"
                  aria-hidden="true"
                />
                <h3 className="mb-3 text-base font-semibold text-foreground">
                  {d.title}
                </h3>
                <p className="mb-5 flex-1 text-sm leading-relaxed text-muted-foreground">
                  {d.body}
                </p>
                <p className="border-t border-border/40 pt-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
                  {d.proofPoint}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
