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

const QUESTION = "Why did NVDA drop 4% on May 14? What's the impact on AMD and TSM?";

const ANSWER_PARAGRAPHS: Array<{ text: string; cites: number[] }> = [
  {
    text: "NVDA traded down -4.18% on May 14, 2026 (close $898.41 → $861.30) following a Bloomberg report citing supply constraints in TSMC's CoWoS advanced packaging line, which gates H100 / H200 production through Q3.",
    cites: [1, 2],
  },
  {
    text: "Knock-on impact: AMD also closed -2.34% as the same packaging bottleneck constrains MI300X shipments. TSM closed -1.87% on the report itself but appears bid in pre-market the next session as the constraint validates pricing power.",
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
            Every claim links back to the article, filing, or filing-paragraph
            it came from. No hallucinated tickers, no made-up dates.
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
            <span className="font-mono text-[10px] text-muted-foreground/60">
              llama-3.1-8b · grounded
            </span>
          </div>

          {/* Question bubble */}
          <div className="border-b border-border/30 px-5 py-4">
            <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
              You
            </p>
            <p className="text-sm text-foreground">{QUESTION}</p>
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
