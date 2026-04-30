/**
 * components/landing/TrustBadges.tsx — data-source attribution row (T-A-1-08)
 *
 * WHY THIS EXISTS: Sophisticated finance buyers (PMs, analysts, quants)
 * evaluate data provenance before reading marketing copy. Listing the actual
 * data vendors (EODHD, Finnhub, SEC EDGAR, Polymarket) up-front reduces the
 * "where does this data come from?" friction that would otherwise drive
 * visitors to bounce.
 */

const SOURCES = [
  { name: "EODHD", role: "End-of-day & intraday equity data" },
  { name: "Finnhub", role: "Fundamentals & corporate events" },
  { name: "SEC EDGAR", role: "Regulatory filings" },
  { name: "Polymarket", role: "Prediction-market odds" },
  { name: "TastyTrade", role: "Brokerage sync (read-only)" },
] as const;

export function TrustBadges() {
  return (
    <section
      aria-label="Trusted data sources"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-7xl px-6 py-12 lg:px-8 lg:py-14">
        <p className="mb-6 text-center font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground/70">
          Data sources & integrations
        </p>

        <div className="flex flex-wrap items-center justify-center gap-x-10 gap-y-5">
          {SOURCES.map((s) => (
            <div
              key={s.name}
              className="flex items-baseline gap-2 text-foreground"
            >
              <span className="font-mono text-base font-semibold tracking-tight">
                {s.name}
              </span>
              <span className="hidden text-[10px] uppercase tracking-wider text-muted-foreground/60 sm:inline">
                · {s.role}
              </span>
            </div>
          ))}
        </div>

        <p className="mt-6 text-center text-[11px] text-muted-foreground/60">
          All vendor names are trademarks of their respective owners. Worldview
          is not affiliated with, sponsored, or endorsed by any vendor listed.
        </p>
      </div>
    </section>
  );
}
