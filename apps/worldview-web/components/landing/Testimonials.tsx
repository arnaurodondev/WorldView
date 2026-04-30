/**
 * components/landing/Testimonials.tsx — placeholder thesis case studies (T-A-1-10)
 *
 * WHY THIS EXISTS: A thesis-stage product has no real customer testimonials,
 * but the social-proof slot is conventionally there on landing pages and a
 * blank space reads as "no users". Instead, we use the slot to highlight
 * the *use cases* the system was designed for — written as "imagined trader
 * personas" so we get the visual benefit of testimonials without the
 * dishonesty of fake customer quotes.
 *
 * The word "scenario" replaces "testimonial" so we never claim these are
 * real users. This is the same pattern used by other ethically-built
 * pre-launch products (e.g., Cal.com's early landing page).
 */

const SCENARIOS = [
  {
    persona: "Active swing trader · Retail",
    quote:
      "I track 40 names across tech and energy. Worldview's screener + impact-scored news lets me cut my morning routine from 90 minutes (Bloomberg + Finviz + Twitter) to about 15.",
    workflow: "Screener → Watchlist → News intelligence",
  },
  {
    persona: "Multi-strategy analyst · Hedge fund (sub-$500M AUM)",
    quote:
      "Bloomberg is overkill for our team of 3. Worldview gives us the entity graph and AI-grounded research at a fraction of the seat price, with our own data integrations on top.",
    workflow: "Knowledge graph → AI chat → Custom data feeds",
  },
  {
    persona: "Quant researcher · Independent",
    quote:
      "The fact that everything goes through one S9 gateway with documented endpoints means I can prototype factor research in a Jupyter notebook against live and historical data without managing five vendor SDKs.",
    workflow: "API access → Historical pulls → Live alerts",
  },
] as const;

export function Testimonials() {
  return (
    <section
      aria-labelledby="scenarios-heading"
      className="border-b border-border/40 bg-card/30"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            Designed for
          </p>
          <h2
            id="scenarios-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Three traders. Three workflows.
          </h2>
          <p className="mt-3 text-sm text-muted-foreground">
            We built this as a thesis project, not a marketed launch — these
            are the personas the system targets, written as scenarios rather
            than fake testimonials.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {SCENARIOS.map((s) => (
            <figure
              key={s.persona}
              className="flex flex-col rounded-[2px] border border-border/40 bg-card p-6"
            >
              <blockquote className="mb-5 flex-1 text-sm leading-relaxed text-foreground">
                <span className="text-primary">&ldquo;</span>
                {s.quote}
                <span className="text-primary">&rdquo;</span>
              </blockquote>
              <figcaption className="space-y-1.5 border-t border-border/40 pt-4">
                <p className="text-xs font-medium text-foreground">{s.persona}</p>
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70">
                  {s.workflow}
                </p>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
