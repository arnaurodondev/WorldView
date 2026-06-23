/**
 * components/landing/WorkflowSection.tsx — 4-step user workflow (T-A-1-05)
 *
 * WHY THIS EXISTS: Trader workflow is the product narrative. Showing the
 * 4 canonical steps (Discover → Analyze → Track → Act) lets visitors see
 * themselves using the product end-to-end. Each step ties to a real product
 * surface so the marketing matches the actual UX.
 *
 * WHY VERTICAL STEPS (not a horizontal stepper at md+): vertical reads better
 * on a long-form landing page. Horizontal steppers force fixed copy lengths
 * and look like onboarding wizards rather than product tours.
 */

import { Search, BarChart3, Bell, Workflow } from "lucide-react";

const STEPS = [
  {
    icon: Search,
    title: "Discover",
    body: "Start with the screener — ranks 8K+ instruments by market impact, news velocity, technical signal, and fundamental trends. Faceted filters by sector, mkt-cap, and price action let you drill from market to single name in seconds.",
    surface: "Screener · /screener",
  },
  {
    icon: BarChart3,
    title: "Analyze",
    body: "Click any ticker to land in the 3-tab instrument page — Quote, Financials, Intelligence. Live quote and 52-week range, a dense fundamentals grid, and the entity knowledge graph (suppliers, executives, regulators, indirect paths) all in one place.",
    surface: "Instrument · /instruments/{id}",
  },
  {
    icon: Bell,
    title: "Track",
    body: "Add the instrument to a watchlist. Configure rule-based alerts on price, technical levels, fundamental changes, or news impact. Notifications via in-app, email, or webhook — so you never miss the move.",
    surface: "Watchlists & Alerts · /alerts",
  },
  {
    icon: Workflow,
    title: "Act",
    body: "Track the position in portfolio analytics — equity curve, realized P&L, sector allocation, and cash-vs-invested exposure against the same intelligence layer that surfaced the trade. Optionally connect a brokerage (TastyTrade) to sync positions read-only.",
    surface: "Portfolio · /portfolio",
  },
] as const;

export function WorkflowSection() {
  return (
    <section
      id="workflow"
      aria-labelledby="workflow-heading"
      className="border-b border-border/40 bg-card/30"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-14 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            How traders use Worldview
          </p>
          <h2
            id="workflow-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Discover → Analyze → Track → Act.
            <br />
            <span className="text-muted-foreground">
              In one terminal, no tab-juggling.
            </span>
          </h2>
        </div>

        {/* WHY relative + connecting line: a vertical line behind the icons
            joins the 4 steps into a single visual journey. Hidden on mobile
            (md:block) where the steps are stacked anyway. */}
        <div className="relative mx-auto max-w-3xl">
          <div
            aria-hidden
            className="pointer-events-none absolute left-[27px] top-8 hidden h-[calc(100%-4rem)] w-px bg-gradient-to-b from-primary/40 via-border/40 to-transparent md:block"
          />

          <ol className="space-y-10 md:space-y-14">
            {STEPS.map((step, i) => {
              const Icon = step.icon;
              return (
                <li
                  key={step.title}
                  className="relative grid grid-cols-[auto,1fr] items-start gap-5"
                >
                  {/* Step badge — circle with icon + step number */}
                  <div className="relative">
                    <div className="flex h-14 w-14 items-center justify-center rounded-full border border-primary/30 bg-card">
                      <Icon
                        className="h-5 w-5 text-primary"
                        aria-hidden="true"
                      />
                    </div>
                    <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary font-mono text-[10px] font-semibold text-primary-foreground">
                      {i + 1}
                    </span>
                  </div>

                  <div className="flex-1 pt-1">
                    <h3 className="mb-2 text-lg font-semibold text-foreground">
                      {step.title}
                    </h3>
                    <p className="mb-3 text-sm leading-relaxed text-muted-foreground">
                      {step.body}
                    </p>
                    <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
                      {step.surface}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </section>
  );
}
