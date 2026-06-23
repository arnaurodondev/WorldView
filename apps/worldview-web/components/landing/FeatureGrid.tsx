/**
 * components/landing/FeatureGrid.tsx — six-surface feature map (§5)
 *
 * WHY THIS EXISTS: Replaces the old 3-card DifferentiatorsSection (which
 * over-indexed on prediction markets and never showed anything). This grid is
 * an at-a-glance map of the SIX real product surfaces — each tile is a one-line
 * value prop + a real screenshot thumbnail + a mono proof-point. The first two
 * tiles deep-link down to the showcases (#intelligence, #ai), so the grid also
 * doubles as a table of contents.
 *
 * WHY STATIC / SERVER COMPONENT: no live data; all six thumbnails are captured
 * screenshots (capture-landing-shots.mjs). Pre-rendered for fast TTFB.
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md §5.
 */

import Link from "next/link";
import {
  Network,
  MessageSquare,
  LineChart,
  SlidersHorizontal,
  Newspaper,
  LayoutGrid,
  type LucideIcon,
} from "lucide-react";
import { ProductShot } from "./ProductShot";

interface Feature {
  icon: LucideIcon;
  title: string;
  body: string;
  proof: string;
  /** Public path to the 16:10 thumbnail screenshot. */
  img: string;
  /** Mono label for the screenshot's window chrome. */
  label: string;
  /** Optional in-page anchor this tile deep-links to (tiles 1 & 2). */
  href?: string;
}

const FEATURES: Feature[] = [
  {
    icon: Network,
    title: "Knowledge-graph intelligence",
    body: "Entities, suppliers, executives and regulators as a queryable graph — plus path discovery between any two names.",
    proof: "AGE graph · ~80K canonical entities · weirdness-ranked paths",
    img: "/landing/feat-graph.png",
    label: "intelligence",
    href: "#intelligence",
  },
  {
    icon: MessageSquare,
    title: "Grounded AI chat",
    body: "Cited answers with a per-source confidence bar; if it can't ground a claim, it says so.",
    proof: "Hybrid RAG · citation confidence · slash-commands",
    img: "/landing/feat-chat.png",
    label: "chat",
    href: "#ai",
  },
  {
    icon: LineChart,
    title: "Portfolio analytics",
    body: "Equity curve, realized P&L, sector allocation and cash-vs-invested exposure against the same intelligence layer.",
    proof: "Equity curve · realized P&L · colour-blind-safe",
    img: "/landing/feat-portfolio.png",
    label: "portfolio",
  },
  {
    icon: SlidersHorizontal,
    title: "Fundamentals screener",
    body: "Faceted filters, saved screens, inline sparklines, CSV/Excel/PDF export.",
    proof: "8K+ instruments · saved screens · 1-click export",
    img: "/landing/feat-screener.png",
    label: "screener",
  },
  {
    icon: Newspaper,
    title: "News intelligence",
    body: "Impact-scored headlines across four price windows, ranked by a market + LLM + routing relevance blend.",
    proof: "Impact windows t0/t1/t2/t5 · Top-Today ranking",
    img: "/landing/feat-news.png",
    label: "news",
  },
  {
    icon: LayoutGrid,
    title: "Instrument detail",
    body: "Quote, Financials and Intelligence in one 3-tab page — live quote, 52-wk range, fundamentals, indicators, entity graph.",
    proof: "Quote · Financials · Intelligence",
    img: "/landing/feat-instrument.png",
    label: "instrument",
  },
];

/**
 * Tile — one feature card. WHY conditionally wrap in <Link>: tiles 1 & 2 are
 * navigable (anchor down to the showcases); the rest are static. We keep the
 * markup identical so the grid stays visually uniform.
 */
function Tile({ feature }: { feature: Feature }) {
  const Icon = feature.icon;

  const inner = (
    <div className="flex h-full flex-col rounded-[2px] border border-border/40 bg-card p-5 transition-colors hover:border-primary/30">
      <div className="mb-3 flex items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-[2px] border border-primary/30 bg-primary/10">
          <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
        </span>
        <h3 className="text-sm font-semibold text-foreground">
          {feature.title}
        </h3>
      </div>

      <p className="mb-4 flex-1 text-sm leading-relaxed text-muted-foreground">
        {feature.body}
      </p>

      {/* 16:10 thumbnail in window chrome. Lazy-loaded (all below the fold). */}
      <ProductShot
        src={feature.img}
        alt={`${feature.title} — screenshot of the Worldview ${feature.label} surface.`}
        label={feature.label}
        width={640}
        height={400}
        // TODO(landing-shots): flip placeholder off once
        // capture-landing-shots.mjs has written these PNGs.
        placeholder
        className="shadow-none"
      />

      <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
        {feature.proof}
      </p>
    </div>
  );

  if (feature.href) {
    return (
      <Link
        href={feature.href}
        className="group block h-full rounded-[2px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        aria-label={`${feature.title} — jump to section`}
      >
        {inner}
      </Link>
    );
  }
  return inner;
}

export function FeatureGrid() {
  return (
    <section
      id="features"
      aria-labelledby="features-heading"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Everything in one terminal
          </p>
          <h2
            id="features-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Six surfaces. One coherent intelligence layer.
          </h2>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((feature) => (
            <Tile key={feature.title} feature={feature} />
          ))}
        </div>
      </div>
    </section>
  );
}
