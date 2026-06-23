/**
 * components/landing/WeirdPathCard.tsx — path-narrative card (Apple→TSMC→ASML)
 *
 * WHY THIS EXISTS: This is the right-hand half of the Knowledge-Graph spotlight
 * (design spec §5b). It tells the signature "weird connection" story as a
 * static, owner-controlled card: a slash-command query, the actual relation
 * chain (ticker → relation → ticker), the weirdness sub-score breakdown, and a
 * one-line plain-English takeaway.
 *
 * WHY STATIC / SERVER COMPONENT: the public landing route makes NO live S9
 * reads (§2) — the "live" feel comes from real screenshots + this hand-curated
 * narrative. Keeping it static avoids auth/data coupling and an empty-state
 * risk on the marketing funnel.
 *
 * WHY PROPS (not hardcoded internals): the spec calls for a reusable shape so
 * a second example could be dropped in later. The default story (AAPL→TSMC→
 * ASML) is wired in KnowledgeGraphSpotlight.tsx, not here.
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md §5b.
 */

import { ArrowRight } from "lucide-react";
import { WeirdnessScoreBars, type ScoreItem } from "./WeirdnessScoreBars";

/** One hop in the path: `from` --relation--> `to`. */
export interface PathHop {
  from: string;
  to: string;
  /** Relation type, e.g. "supplied_by" — shown small under the arrow. */
  relation: string;
}

export interface WeirdPathCardProps {
  /** The slash-command query that produced this path, e.g. "/path AAPL ASML". */
  query: string;
  /** Ordered hops. Rendered as from₁ ▸ to₁(=from₂) ▸ to₂ … */
  hops: PathHop[];
  /** Weirdness sub-scores (reliability, unexpectedness, …). */
  scores: ScoreItem[];
  /** Composite weirdness score (0..1). */
  composite: number;
  /** One-line plain-English takeaway under the scores. */
  takeaway: string;
}

/**
 * TickerBadge — a mono ticker chip in the path chain. Uses primary/20 so the
 * tickers pop against the card without competing with the CTA.
 */
function TickerBadge({ ticker }: { ticker: string }) {
  return (
    <span className="inline-flex items-center rounded-[2px] bg-primary/20 px-2 py-1 font-mono text-xs font-semibold tabular-nums text-primary">
      {ticker}
    </span>
  );
}

export function WeirdPathCard({
  query,
  hops,
  scores,
  composite,
  takeaway,
}: WeirdPathCardProps) {
  // Flatten the hops into the unique ordered list of node tickers so the chain
  // renders as AAPL ▸ TSMC ▸ ASML (each node once). We assume hops are
  // contiguous (hop[i].to === hop[i+1].from), which the static data guarantees.
  const nodes: string[] = hops.length > 0 ? [hops[0].from] : [];
  for (const hop of hops) nodes.push(hop.to);

  return (
    <div className="rounded-[2px] border border-border/60 bg-card p-5 shadow-xl">
      {/* ── Query row — the slash-command chip ──────────────────────────── */}
      <div className="mb-5 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
          Query
        </span>
        <span className="inline-flex items-center rounded-[2px] border border-primary/30 bg-primary/10 px-2 py-1 font-mono text-xs text-primary">
          {query}
        </span>
      </div>

      {/* ── Path chain — tickers + labelled relation arrows ─────────────── */}
      {/* WHY flex-wrap: on narrow widths the chain wraps cleanly instead of
          forcing horizontal scroll. Each arrow carries its relation label
          underneath in a tiny muted mono caption (§5b). */}
      <div className="mb-6 flex flex-wrap items-start gap-x-2 gap-y-3">
        {nodes.map((node, i) => (
          <div key={`${node}-${i}`} className="flex items-start gap-2">
            <TickerBadge ticker={node} />
            {/* Render the relation arrow AFTER every node except the last. */}
            {i < hops.length && (
              <div className="flex flex-col items-center pt-1">
                <ArrowRight
                  className="h-3.5 w-3.5 text-muted-foreground"
                  aria-hidden="true"
                />
                <span className="mt-0.5 max-w-[5rem] text-center font-mono text-[10px] leading-tight text-muted-foreground">
                  {hops[i].relation}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ── Weirdness sub-score breakdown ───────────────────────────────── */}
      <WeirdnessScoreBars scores={scores} composite={composite} />

      {/* ── Plain-English takeaway ──────────────────────────────────────── */}
      <p className="mt-5 border-t border-border/40 pt-4 text-sm leading-relaxed text-muted-foreground">
        {takeaway}
      </p>
    </div>
  );
}
