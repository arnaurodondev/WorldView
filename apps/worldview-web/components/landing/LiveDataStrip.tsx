/**
 * components/landing/LiveDataStrip.tsx — landing live-data ticker (T-A-1-02)
 *
 * WHY THIS EXISTS: A single horizontal strip of representative tickers
 * communicates "we have data" within 1 second of the page rendering. Modeled
 * on Bloomberg.com's top-of-page strip, Reuters terminal, and Finviz quote bar.
 *
 * WHY STATIC MOCK: This is a Server Component rendered at build time. Real
 * quotes go stale within seconds and would require a client fetch + skeleton
 * which is overkill for a marketing page. We label the strip "Sample Market
 * Data" to be honest about provenance and avoid misleading visitors.
 *
 * WHY 6 TICKERS (not 4): better visual rhythm at desktop widths; the strip
 * needs to feel like a real Bloomberg tape, not a sparse demo.
 */

const TICKERS = [
  { symbol: "SPY", name: "S&P 500 ETF", price: "550.32", change: 0.23 },
  { symbol: "QQQ", name: "Nasdaq 100 ETF", price: "458.71", change: -0.12 },
  { symbol: "VIX", name: "Volatility Index", price: "14.82", change: -3.4 },
  { symbol: "BTC", name: "Bitcoin", price: "67,240", change: 1.82 },
  { symbol: "TLT", name: "20Y Treasury", price: "92.14", change: -0.55 },
  { symbol: "GLD", name: "Gold", price: "248.91", change: 0.41 },
] as const;

export function LiveDataStrip() {
  return (
    <section
      aria-label="Sample live market data"
      className="border-b border-border/40 bg-card/40"
    >
      <div className="mx-auto flex max-w-7xl items-stretch gap-2 px-6 py-2 lg:px-8">
        {/* "LIVE" pill — matches the Bloomberg / Reuters convention */}
        <div className="flex shrink-0 items-center gap-1.5 border-r border-border/40 pr-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-positive opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-positive" />
          </span>
          Sample data
        </div>

        {/* Quote row — flex-wrap on mobile so the tape never overflows.
            The order is intentional: indexes / volatility / commodities to
            cover equity + risk + alt-asset coverage in 6 ticks. */}
        <div className="flex flex-1 flex-wrap items-center gap-x-6 gap-y-1.5 overflow-x-auto">
          {TICKERS.map((t) => (
            <div key={t.symbol} className="flex items-baseline gap-2">
              <span
                title={t.name}
                className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/70"
              >
                {t.symbol}
              </span>
              <span className="font-mono text-[12px] tabular-nums text-foreground">
                {t.price}
              </span>
              <span
                className={
                  "font-mono text-[10px] tabular-nums " +
                  (t.change >= 0 ? "text-positive" : "text-negative")
                }
              >
                {t.change >= 0 ? "+" : ""}
                {t.change.toFixed(2)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
