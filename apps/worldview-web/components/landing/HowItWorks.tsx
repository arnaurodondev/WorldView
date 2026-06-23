/**
 * components/landing/HowItWorks.tsx — under-the-hood architecture (§8)
 *
 * WHY THIS EXISTS: Converts the FAQ "is this a real product?" question into a
 * confidence-building architecture moment, tied to the thesis/CIKM framing. It
 * shows the hybrid-retrieval pipeline (BM25 + pgvector + AGE → Reciprocal-Rank
 * Fusion → grounded synthesis → cited answer) and four credibility pillars.
 *
 * WHY STATIC / SERVER COMPONENT: pure copy + a flex/Separator pipeline strip;
 * no new chart lib, no client JS.
 *
 * DESIGN REFERENCE: docs/design/2026-06-23-landing-page-redesign.md §8.
 */

import { Boxes, Server, Lock, Link2, type LucideIcon } from "lucide-react";

/**
 * Pipeline steps rendered as mono boxes joined by arrows. The three retrieval
 * arms (BM25 / pgvector / AGE) are grouped, then fused (RRF), then synthesised.
 * Kept as plain strings so the strip is pure flex — no diagram library (§0).
 */
const PIPELINE: string[] = [
  "Query",
  "BM25 keyword",
  "pgvector semantic",
  "AGE graph",
  "Reciprocal-Rank Fusion",
  "Grounded synthesis",
  "Cited answer",
];

interface Pillar {
  icon: LucideIcon;
  title: string;
  body: string;
}

const PILLARS: Pillar[] = [
  {
    icon: Boxes,
    title: "10 event-driven microservices",
    body: "Kafka outbox, idempotent consumers, at-least-once delivery — no dual-write bugs.",
  },
  {
    icon: Server,
    title: "Single S9 API gateway",
    body: "55+ documented endpoints; the frontend never touches a backend service directly.",
  },
  {
    icon: Lock,
    title: "Externalized LLMs, your data stays yours",
    body: "We send the prompt and store the response, nothing else. Brokerage sync is read-only.",
  },
  {
    icon: Link2,
    title: "Full citation chain",
    body: "Every claim traces to a source document and offset — auditable end to end.",
  },
];

export function HowItWorks() {
  return (
    <section
      id="how-it-works"
      aria-labelledby="how-heading"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Under the hood
          </p>
          <h2
            id="how-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Built like infrastructure, not a demo.
          </h2>
        </div>

        {/* ── Retrieval-pipeline strip ────────────────────────────────────── */}
        {/* WHY a role="img" wrapper with aria-label: a screen reader announces
            the whole pipeline as one sentence rather than reading disconnected
            box labels and bare "▸" arrows. The visible boxes are the sighted
            user's version of the same information. */}
        <div
          role="img"
          aria-label="Retrieval pipeline: query fans out to BM25 keyword, pgvector semantic, and AGE graph retrieval, which are combined by Reciprocal-Rank Fusion, then grounded synthesis produces a cited answer."
          className="mx-auto mb-14 flex max-w-4xl flex-wrap items-center justify-center gap-x-2 gap-y-3"
        >
          {PIPELINE.map((step, i) => (
            <div key={step} className="flex items-center gap-2">
              <span className="inline-flex items-center rounded-[2px] border border-border/50 bg-muted/30 px-2.5 py-1.5 font-mono text-[10px] text-muted-foreground">
                {step}
              </span>
              {/* Arrow after every box except the last. */}
              {i < PIPELINE.length - 1 && (
                <span aria-hidden className="font-mono text-xs text-primary/60">
                  ▸
                </span>
              )}
            </div>
          ))}
        </div>

        {/* ── 4 credibility pillars ───────────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 md:grid-cols-4">
          {PILLARS.map((pillar) => {
            const Icon = pillar.icon;
            return (
              <div
                key={pillar.title}
                className="rounded-[2px] border border-border/40 bg-card p-5"
              >
                <span className="mb-3 flex h-8 w-8 items-center justify-center rounded-[2px] border border-primary/30 bg-primary/10">
                  <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                </span>
                <h3 className="mb-2 text-sm font-semibold text-foreground">
                  {pillar.title}
                </h3>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {pillar.body}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
