/**
 * components/landing/KnowledgeGraphSpotlight.tsx — flagship KG showcase (§5b)
 *
 * WHY THIS EXISTS: The knowledge graph + indirect path discovery is the single
 * most differentiated, CIKM-novel capability — and was ENTIRELY ABSENT from the
 * old landing page (it only told, never showed). This section shows it: a real
 * sigma.js graph screenshot on the left, and the Apple→TSMC→ASML weirdness
 * story (WeirdPathCard) on the right.
 *
 * WHY id="intelligence": the refreshed LandingNav adds an "Intelligence" anchor
 * and the FeatureGrid "Knowledge-graph intelligence" tile deep-links here.
 *
 * WHY STATIC / SERVER COMPONENT: no live S9 reads on the public route (§2). The
 * graph image is a captured screenshot (capture-landing-shots.mjs); the path
 * narrative is hand-curated static data.
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md §5b
 * ("If only one new section ships, ship this one.").
 */

import { ProductShot } from "./ProductShot";
import { WeirdPathCard } from "./WeirdPathCard";

/**
 * The signature story, as static data. The four sub-scores multiply into the
 * composite weirdness (reliability × unexpectedness × semantic-distance ×
 * novelty) — values are owner-curated representative numbers.
 */
const PATH_HOPS = [
  { from: "AAPL", to: "TSMC", relation: "supplied_by" },
  { from: "TSMC", to: "ASML", relation: "equipment_from" },
];

const WEIRDNESS_SCORES = [
  { label: "Reliability", value: 0.91 },
  { label: "Unexpectedness", value: 0.74 },
  { label: "Semantic dist.", value: 0.68 },
  { label: "Novelty", value: 0.55 },
];

const COMPOSITE = 0.72;

const TAKEAWAY =
  "Apple's exposure to ASML's EUV-lithography monopoly is two hops deep — invisible to a ticker-by-ticker scan.";

export function KnowledgeGraphSpotlight() {
  return (
    <section
      id="intelligence"
      aria-labelledby="kg-spotlight-heading"
      // Full-bleed band on bg-card/30 to set the flagship section apart from
      // the bg-background sections around it.
      className="border-b border-border/40 bg-card/30"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        {/* ── Section heading ─────────────────────────────────────────────── */}
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Signature feature
          </p>
          <h2
            id="kg-spotlight-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            See connections you&apos;d never think to search.
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Ask how two companies relate and the graph returns the actual chain
            — scored by how surprising it is.
          </p>
        </div>

        {/* ── Two-column: graph screenshot · path narrative ───────────────── */}
        <div className="grid items-center gap-10 lg:grid-cols-2 lg:gap-12">
          {/* Left: real sigma.js graph screenshot in window chrome. */}
          <ProductShot
            src="/landing/graph-spotlight.png"
            alt="Worldview knowledge-graph view showing entity nodes (companies, suppliers, regulators) connected by typed relationship edges, with a path highlighted between two selected companies."
            label="connections"
            width={720}
            height={520}
            // TODO(landing-shots): set placeholder={false} once
            // capture-landing-shots.mjs has written public/landing/graph-spotlight.png.
            placeholder
          />

          {/* Right: the Apple→TSMC→ASML weirdness story. */}
          <WeirdPathCard
            query="/path AAPL ASML"
            hops={PATH_HOPS}
            scores={WEIRDNESS_SCORES}
            composite={COMPOSITE}
            takeaway={TAKEAWAY}
          />
        </div>

        {/* ── Proof footer (mono) ─────────────────────────────────────────── */}
        <p className="mx-auto mt-10 max-w-3xl text-center font-mono text-[11px] leading-relaxed text-muted-foreground/70">
          pgvector + AGE + BM25 hybrid retrieval · VLE path search 60–800ms ·
          weirdness = reliability × unexpectedness × semantic-distance × novelty
        </p>
      </div>
    </section>
  );
}
