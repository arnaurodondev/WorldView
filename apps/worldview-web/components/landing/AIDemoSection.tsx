/**
 * components/landing/AIDemoSection.tsx — grounded AI demo (T-A-1-06)
 *
 * WHY THIS EXISTS: Generic "AI-powered" claims are commodity in 2026.
 * What's not commodity: showing the AI's actual output with verifiable
 * citations. This section displays a worked example of the RAG-chat UX
 * with citation chips so visitors see exactly what they get — including
 * the source documents the answer is grounded in.
 *
 * WHY NOT a real live demo: a streaming demo on the marketing page is too
 * heavy (loads the LLM client, streams tokens, costs $) and adds latency.
 * The static mock with realistic citations communicates the same value
 * proposition at zero runtime cost and never goes stale.
 */

import { MessageSquare, ExternalLink } from "lucide-react";
import { scoreBand } from "./WeirdnessScoreBars";

/**
 * SLASH_COMMANDS — the chat power-user shortcuts, shown as a chip row above the
 * question so visitors see the chat is more than a free-text box. The demo
 * question below uses one of them (`/path`). Static / cosmetic (§6).
 */
const SLASH_COMMANDS = ["/quote", "/path", "/compare", "/news", "/portfolio"] as const;

// The demo now leads with a slash-command query (§6) to showcase /path.
const QUESTION = "/path NVDA TSM";

/**
 * CITATION_CONFIDENCE — per-citation grounding confidence (0..1), used to draw
 * the citation-confidence bar under the answer. Mirrors the in-product
 * CitationBar: one segment per source, coloured by band (green ≥0.7 / amber
 * 0.4–0.7 / red <0.4) with a REDUNDANT numeric + sr-only label so it's
 * colour-blind-safe (§6.11b/§6.14). Static representative data.
 */
const CITATION_CONFIDENCE = [
  { n: 1, value: 0.92 },
  { n: 2, value: 0.78 },
  { n: 3, value: 0.41 },
] as const;

/** Map a confidence band to a semantic fill token (secondary cue to the number). */
function confidenceColor(value: number): string {
  const band = scoreBand(value);
  if (band === "high") return "bg-positive";
  if (band === "medium") return "bg-warning";
  return "bg-negative";
}

const ANSWER_PARAGRAPHS: Array<{ text: string; cites: number[] }> = [
  {
    text: "NVDA connects to TSM in two hops: NVDA is fabricated_by TSMC, and TSMC's CoWoS advanced-packaging line gates H100 / H200 output. That dependency surfaced on May 14, 2026, when a Bloomberg report on CoWoS capacity sent NVDA down -4.18% (close $898.41 → $861.30).",
    cites: [1, 2],
  },
  {
    text: "TSM closed -1.87% on the report itself but was bid in the next pre-market session as the constraint validates its pricing power. I can't confirm a longer-term margin impact from the retrieved sources, so I'm flagging that claim as ungrounded rather than asserting it.",
    cites: [2, 3],
  },
];

const CITATIONS = [
  {
    n: 1,
    title: "Bloomberg: TSMC CoWoS capacity tight through Q3",
    src: "Bloomberg",
    date: "2026-05-14 09:42 ET",
  },
  {
    n: 2,
    title: "Worldview impact analysis · NVDA price window t0",
    src: "Worldview NLP",
    date: "2026-05-14 13:00 ET",
  },
  {
    n: 3,
    title: "AMD 10-Q Q1'26 · MI300X production guidance",
    src: "SEC EDGAR",
    date: "2026-04-28",
  },
] as const;

export function AIDemoSection() {
  return (
    <section
      id="ai"
      aria-labelledby="ai-demo-heading"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            AI grounded in your data
          </p>
          <h2
            id="ai-demo-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Ask questions, get cited answers.
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            Every claim links back to the article, filing, or paragraph it came
            from. If it can&apos;t ground a claim, it says so.
          </p>
        </div>

        {/* Chat mock card — mirrors the in-product RAG chat panel */}
        <div className="mx-auto max-w-3xl overflow-hidden rounded-[2px] border border-border/60 bg-card shadow-xl">
          {/* Top label */}
          <div className="flex items-center justify-between border-b border-border/40 bg-muted/30 px-4 py-2">
            <div className="flex items-center gap-2">
              <MessageSquare
                className="h-3.5 w-3.5 text-primary"
                aria-hidden="true"
              />
              <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                AI Chat · Workspace
              </span>
            </div>
            {/* WHY a neutral tag (not a model string): the live chat model has
                moved off Llama 3.1 8B and any pinned model name goes stale. The
                trust signals — grounded, cited, hybrid-RAG — are what matter. */}
            <span className="font-mono text-[10px] text-muted-foreground/60">
              grounded · cited · hybrid-RAG
            </span>
          </div>

          {/* Slash-command chip row — shows the chat is keyboard-first and more
              than a free-text box. The demo question uses one (`/path`). */}
          <div className="flex flex-wrap items-center gap-1.5 border-b border-border/30 bg-muted/20 px-5 py-2.5">
            {SLASH_COMMANDS.map((cmd) => (
              <span
                key={cmd}
                className={`inline-flex items-center rounded-[2px] border px-1.5 py-0.5 font-mono text-[10px] ${
                  // Highlight the command the demo actually uses.
                  cmd === "/path"
                    ? "border-primary/40 bg-primary/15 text-primary"
                    : "border-border/50 text-muted-foreground/80"
                }`}
              >
                {cmd}
              </span>
            ))}
          </div>

          {/* Question bubble */}
          <div className="border-b border-border/30 px-5 py-4">
            <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
              You
            </p>
            <p className="font-mono text-sm text-foreground">{QUESTION}</p>
          </div>

          {/* Answer bubble */}
          <div className="px-5 py-4">
            <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-primary">
              Worldview AI
            </p>
            <div className="space-y-3 text-sm leading-relaxed text-foreground">
              {ANSWER_PARAGRAPHS.map((p, i) => (
                <p key={i}>
                  {p.text}{" "}
                  {p.cites.map((c) => (
                    <sup key={c}>
                      <a
                        href={`#cite-${c}`}
                        className="ml-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-[2px] bg-primary/15 px-1 font-mono text-[9px] font-semibold text-primary hover:bg-primary/25"
                      >
                        {c}
                      </a>
                    </sup>
                  ))}
                </p>
              ))}
            </div>

            {/* ── Citation-confidence bar ─────────────────────────────────
                One segment per citation, coloured by grounding-confidence band
                (green ≥0.7 / amber 0.4–0.7 / red <0.4). Colour is the SECONDARY
                cue — each segment carries a title= tooltip and an sr-only label
                with the numeric value, so it's colour-blind-safe and screen-
                reader friendly (§6.11b/§6.14). The red segment visibly signals
                the low-confidence claim the answer flagged as ungrounded. */}
            <div className="mt-5">
              <p className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                Citation confidence
              </p>
              <div
                role="img"
                aria-label="Citation confidence by source: source 1 high, source 2 medium, source 3 low."
                className="flex gap-1"
              >
                {CITATION_CONFIDENCE.map((c) => (
                  <div
                    key={c.n}
                    title={`Source ${c.n}: ${c.value.toFixed(2)} confidence`}
                    className="flex-1"
                  >
                    <div className="h-1.5 w-full overflow-hidden rounded-[2px] bg-muted">
                      <div
                        className={`h-full rounded-[2px] ${confidenceColor(c.value)}`}
                        style={{ width: `${Math.round(c.value * 100)}%` }}
                      />
                    </div>
                    <span className="mt-1 block text-center font-mono text-[9px] tabular-nums text-muted-foreground">
                      [{c.n}] {c.value.toFixed(2)}
                    </span>
                    <span className="sr-only">
                      Source {c.n} confidence {c.value.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Citation list — explicit, scannable, linkable */}
            <div className="mt-5 rounded-[2px] border border-border/40 bg-muted/30 px-4 py-3">
              <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                Sources
              </p>
              <ol className="space-y-1.5">
                {CITATIONS.map((c) => (
                  <li
                    key={c.n}
                    id={`cite-${c.n}`}
                    className="flex items-start gap-2 text-xs text-muted-foreground"
                  >
                    <span className="mt-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-[2px] bg-primary/15 font-mono text-[9px] font-semibold text-primary">
                      {c.n}
                    </span>
                    <span className="flex-1">
                      <span className="text-foreground">{c.title}</span>
                      <span className="ml-2 text-muted-foreground/70">
                        {c.src} · {c.date}
                      </span>
                    </span>
                    <ExternalLink
                      className="mt-0.5 h-3 w-3 text-muted-foreground/50"
                      aria-hidden="true"
                    />
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </div>

        <p className="mx-auto mt-5 max-w-xl text-center text-xs text-muted-foreground/70">
          Sample answer based on representative data. Live Worldview AI uses
          retrieval-augmented generation against your subscribed data sources;
          no answer ships without citations.
        </p>
      </div>
    </section>
  );
}
