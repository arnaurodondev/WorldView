/**
 * components/landing/ComparisonTable.tsx — feature parity matrix (T-A-1-07)
 *
 * WHY THIS EXISTS: A direct comparison table forces visitors to position the
 * product mentally vs. competitors they already know. Even without any
 * advantage on every row, just appearing alongside Bloomberg in a structured
 * comparison anchors Worldview as "in the same league".
 *
 * WHY THESE 4 COMPETITORS: Bloomberg = institutional gold-standard;
 * Interactive Brokers = retail brokerage with research; TradingView = retail
 * charting; Finviz = retail screener. Together they cover the four buckets
 * a target user might be using today.
 *
 * WHY HONEST CHECKMARKS: claiming features Worldview doesn't have damages
 * trust on any sophisticated visitor. The checkmarks below match the actual
 * product surface (∂ = partial, ◯ = absent, ● = present).
 */

import { Check, X, Minus } from "lucide-react";

type Cell = "yes" | "partial" | "no";

interface Row {
  feature: string;
  worldview: Cell;
  bloomberg: Cell;
  ibkr: Cell;
  tradingview: Cell;
  finviz: Cell;
}

const ROWS: Row[] = [
  {
    feature: "Real-time market data",
    worldview: "yes",
    bloomberg: "yes",
    ibkr: "yes",
    tradingview: "yes",
    finviz: "partial",
  },
  {
    feature: "News with market-impact scoring",
    worldview: "yes",
    bloomberg: "partial",
    ibkr: "no",
    tradingview: "no",
    finviz: "no",
  },
  {
    feature: "Knowledge graph (entity relations)",
    worldview: "yes",
    bloomberg: "partial",
    ibkr: "no",
    tradingview: "no",
    finviz: "no",
  },
  {
    feature: "AI-powered research with citations",
    worldview: "yes",
    bloomberg: "no",
    ibkr: "no",
    tradingview: "no",
    finviz: "no",
  },
  {
    feature: "Prediction-market integration",
    worldview: "yes",
    bloomberg: "no",
    ibkr: "no",
    tradingview: "no",
    finviz: "no",
  },
  {
    feature: "Configurable terminal workspace",
    worldview: "yes",
    bloomberg: "yes",
    ibkr: "partial",
    tradingview: "yes",
    finviz: "no",
  },
  {
    feature: "Brokerage sync (positions / P&L)",
    worldview: "yes",
    bloomberg: "no",
    ibkr: "yes",
    tradingview: "partial",
    finviz: "no",
  },
  {
    feature: "Open architecture / API",
    worldview: "yes",
    bloomberg: "partial",
    ibkr: "yes",
    tradingview: "partial",
    finviz: "no",
  },
  {
    feature: "Estimated monthly cost",
    // Tagged as 'partial' so it renders text instead of a checkmark.
    // Custom rendering below interprets the feature label.
    worldview: "yes",
    bloomberg: "no",
    ibkr: "yes",
    tradingview: "partial",
    finviz: "yes",
  },
];

const PRICES = {
  worldview: "$0–49",
  bloomberg: "$2,000+",
  ibkr: "$0",
  tradingview: "$15–60",
  finviz: "$25",
} as const;

function CellIcon({ value }: { value: Cell }) {
  if (value === "yes") {
    return (
      <Check
        className="mx-auto h-4 w-4 text-positive"
        aria-label="Yes"
      />
    );
  }
  if (value === "partial") {
    return (
      <Minus
        className="mx-auto h-4 w-4 text-muted-foreground"
        aria-label="Partial"
      />
    );
  }
  return (
    <X
      className="mx-auto h-4 w-4 text-negative/70"
      aria-label="No"
    />
  );
}

export function ComparisonTable() {
  return (
    <section
      id="compare"
      aria-labelledby="compare-heading"
      className="border-b border-border/40 bg-card/30"
    >
      <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8 lg:py-24">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <p className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            How we compare
          </p>
          <h2
            id="compare-heading"
            className="text-3xl font-semibold tracking-tight text-foreground sm:text-4xl"
          >
            Feature parity, side by side.
          </h2>
        </div>

        <div className="overflow-x-auto rounded-[2px] border border-border/40 bg-card">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="border-b border-border/40 bg-muted/30">
                <th
                  scope="col"
                  className="px-4 py-3 font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
                >
                  Feature
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-center text-xs font-semibold text-primary"
                >
                  Worldview
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-center text-xs font-medium text-foreground"
                >
                  Bloomberg
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-center text-xs font-medium text-foreground"
                >
                  IBKR
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-center text-xs font-medium text-foreground"
                >
                  TradingView
                </th>
                <th
                  scope="col"
                  className="px-4 py-3 text-center text-xs font-medium text-foreground"
                >
                  Finviz
                </th>
              </tr>
            </thead>
            <tbody>
              {ROWS.slice(0, -1).map((row) => (
                <tr
                  key={row.feature}
                  className="border-b border-border/20 last:border-b-0 hover:bg-muted/20"
                >
                  <td className="px-4 py-3 text-xs text-foreground">
                    {row.feature}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <CellIcon value={row.worldview} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <CellIcon value={row.bloomberg} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <CellIcon value={row.ibkr} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <CellIcon value={row.tradingview} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <CellIcon value={row.finviz} />
                  </td>
                </tr>
              ))}
              {/* Custom price row at the bottom — renders text instead of icons. */}
              <tr className="border-t-2 border-border/60 bg-muted/30">
                <td className="px-4 py-3 text-xs font-medium text-foreground">
                  Estimated monthly cost
                </td>
                <td className="px-4 py-3 text-center font-mono text-xs tabular-nums text-primary">
                  {PRICES.worldview}
                </td>
                <td className="px-4 py-3 text-center font-mono text-xs tabular-nums text-muted-foreground">
                  {PRICES.bloomberg}
                </td>
                <td className="px-4 py-3 text-center font-mono text-xs tabular-nums text-muted-foreground">
                  {PRICES.ibkr}
                </td>
                <td className="px-4 py-3 text-center font-mono text-xs tabular-nums text-muted-foreground">
                  {PRICES.tradingview}
                </td>
                <td className="px-4 py-3 text-center font-mono text-xs tabular-nums text-muted-foreground">
                  {PRICES.finviz}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p className="mt-4 text-center text-[11px] text-muted-foreground/70">
          Comparisons reflect public marketing and product documentation as of
          2026-05. Figures are illustrative.
        </p>
      </div>
    </section>
  );
}
