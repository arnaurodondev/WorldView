/**
 * components/landing/SectorHeatmapPreview.tsx — landing 6-tile heatmap (T-A-1-03)
 *
 * WHY THIS EXISTS: A static SPDR sector snapshot using the same heatCellColor
 * 7-step gradient as the live screener. Visitors see exactly how the live
 * heatmap looks before signing up — no other landing page (Bloomberg / IBKR /
 * TradingView) shows real product visualization on the marketing site, so
 * this is a differentiator.
 *
 * WHY heatCellColor (shared util): keeps the marketing snapshot in sync with
 * the in-product heatmap automatically — when the design system updates the
 * 7-step gradient, the landing page picks it up without code changes.
 */

import { heatCellColor } from "@/lib/utils";

/**
 * SECTORS — the 11 GICS sectors are too dense for a marketing snapshot;
 * we show the 6 highest-volume SPDRs as the canonical snapshot.
 *
 * Numbers are illustrative end-of-day moves; we use representative values
 * across the 7-step range so the visual showcases the full gradient.
 */
const SECTORS = [
  { symbol: "XLK", name: "Technology", change: 2.41 },
  { symbol: "XLF", name: "Financials", change: 0.82 },
  { symbol: "XLV", name: "Health Care", change: -0.34 },
  { symbol: "XLE", name: "Energy", change: -2.18 },
  { symbol: "XLY", name: "Consumer Disc.", change: 1.15 },
  { symbol: "XLI", name: "Industrials", change: -1.42 },
] as const;

export function SectorHeatmapPreview() {
  return (
    <section
      aria-label="Sector heatmap preview"
      className="border-b border-border/40 bg-background"
    >
      <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20">
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Live in your dashboard
            </p>
            <h2 className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              7-step sector heatmap
            </h2>
            <p className="mt-2 max-w-xl text-sm text-muted-foreground">
              Real-time GICS sector performance with the same color scale used
              across the screener and watchlist views — no toggling palettes.
            </p>
          </div>
          {/* Legend tile — six ticks of the gradient as a single bar so visitors
              can map the colors to ranges without hunting for a key. */}
          <div className="hidden items-center gap-1 sm:flex" aria-hidden>
            {[-3, -2, -1, 0, 1, 2, 3].map((step) => {
              const c = heatCellColor(step);
              return (
                <span
                  key={step}
                  className="h-3 w-5 rounded-[1px]"
                  style={{ background: c.background }}
                />
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {SECTORS.map((s) => {
            const c = heatCellColor(s.change);
            return (
              <div
                key={s.symbol}
                className="flex flex-col gap-1 rounded-[2px] border border-border/40 p-3 transition-colors hover:border-primary/30"
                style={{ background: c.background, color: c.color }}
              >
                <div className="flex items-baseline justify-between">
                  <span className="font-mono text-[11px] font-medium tracking-wider">
                    {s.symbol}
                  </span>
                  <span className="font-mono text-[10px] tabular-nums">
                    {s.change >= 0 ? "+" : ""}
                    {s.change.toFixed(2)}%
                  </span>
                </div>
                <span className="text-[10px] opacity-80">{s.name}</span>
              </div>
            );
          })}
        </div>

        <p className="mt-3 text-center text-[10px] text-muted-foreground/60">
          Sample data · sector tiles tint from -3% (red) through neutral to
          +3% (green), matching the in-product screener
        </p>
      </div>
    </section>
  );
}
