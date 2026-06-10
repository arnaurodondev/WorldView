/**
 * KeyStatsBar.test.tsx — Quote-tab Key Stats bar (Round-2 item 1).
 *
 * CONTRACTS PINNED:
 *   1. All five labels render (MKT CAP / P/E / EPS / DIV YLD / BETA).
 *   2. Values format correctly from the prop fallbacks (slim bundle shapes).
 *   3. Nulls render as em-dash ("—") — never "0" / "NaN" / blank.
 *   4. The rich cache slot WINS over the slim prop once hydrated (the
 *      passive-subscription upgrade path) — and the component itself never
 *      fires a network request (enabled:false contract).
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { KeyStatsBar } from "@/components/instrument/quote/stats/KeyStatsBar";
import { qk } from "@/lib/query/keys";
import type { Fundamentals, FundamentalsSnapshot } from "@/types/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function wrap(qc: QueryClient, children: ReactNode) {
  return render(<QueryClientProvider client={qc}>{children}</QueryClientProvider>);
}

/** Slim bundle-style fundamentals — only the fields the page bundle carries. */
function slimFundamentals(overrides: Partial<Fundamentals> = {}): Fundamentals {
  return {
    instrument_id: "i-1",
    ticker: "AAPL",
    name: "Apple Inc.",
    market_cap: 4_308_095_467_520,
    pe_ratio: 35.468,
    forward_pe: null,
    price_to_book: null,
    price_to_sales: null,
    ev_to_ebitda: null,
    gross_margin: null,
    operating_margin: null,
    net_margin: null,
    roe: null,
    roa: null,
    revenue_growth_yoy: null,
    earnings_growth_yoy: null,
    dividend_yield: null,
    payout_ratio: null,
    debt_to_equity: null,
    current_ratio: null,
    quick_ratio: null,
    week_52_high: null,
    week_52_low: null,
    daily_return: null,
    analyst_strong_buy_count: null,
    analyst_buy_count: null,
    analyst_hold_count: null,
    analyst_sell_count: null,
    analyst_strong_sell_count: null,
    analyst_rating: null,
    analyst_target_price: null,
    updated_at: null,
    ...overrides,
  };
}

function snapshot(overrides: Partial<FundamentalsSnapshot> = {}): FundamentalsSnapshot {
  return {
    instrument_id: "i-1",
    eps_ttm: 8.27,
    beta: 1.086,
    avg_volume_30d: null,
    operating_cash_flow: null,
    capex: null,
    free_cash_flow: null,
    fcf_margin: null,
    interest_coverage: null,
    net_debt_to_ebitda: null,
    credit_rating: null,
    updated_at: null,
    ...overrides,
  };
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("KeyStatsBar", () => {
  it("renders all five stat labels", () => {
    wrap(makeClient(), <KeyStatsBar instrumentId="i-1" />);
    for (const label of ["MKT CAP", "P/E", "EPS", "DIV YLD", "BETA"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("formats values from the prop fallbacks", () => {
    wrap(
      makeClient(),
      <KeyStatsBar
        instrumentId="i-1"
        fundamentals={slimFundamentals({ dividend_yield: 0.0044 })}
        snapshot={snapshot()}
      />,
    );
    expect(screen.getByText("$4.31T")).toBeInTheDocument(); // market cap (compact)
    expect(screen.getByText("35.47")).toBeInTheDocument(); // P/E ratio (2dp, no suffix)
    expect(screen.getByText("$8.27")).toBeInTheDocument(); // EPS TTM (price format)
    expect(screen.getByText("0.44%")).toBeInTheDocument(); // div yield (unsigned %)
    expect(screen.getByText("1.09")).toBeInTheDocument(); // beta (2dp)
  });

  it("renders em-dash for every null field (no props, empty cache)", () => {
    wrap(makeClient(), <KeyStatsBar instrumentId="i-1" />);
    // 5 stats, all unknown → 5 em-dashes. Asserting the exact count guards
    // against a formatter regression that renders "NaN"/"$0.00" for nulls.
    expect(screen.getAllByText("—")).toHaveLength(5);
  });

  it("prefers the rich cache slot over the slim prop (passive upgrade path)", () => {
    const qc = makeClient();
    // Simulate MetricsTable's useMetricsTableData having hydrated the shared
    // cache slots with richer data than the slim prop carries.
    qc.setQueryData(
      qk.instruments.fundamentals("i-1"),
      slimFundamentals({ market_cap: 999_000_000_000, dividend_yield: 0.01 }),
    );
    qc.setQueryData(qk.instruments.fundamentalsSnapshot("i-1"), snapshot({ beta: 2.5 }));

    wrap(
      qc,
      <KeyStatsBar
        instrumentId="i-1"
        fundamentals={slimFundamentals({ market_cap: 1 })}
        snapshot={snapshot({ beta: 0.1 })}
      />,
    );

    // Cache wins: $999.00B (not the prop's $1) and beta 2.50 (not 0.10).
    expect(screen.getByText("$999.00B")).toBeInTheDocument();
    expect(screen.getByText("2.50")).toBeInTheDocument();
    expect(screen.getByText("1.00%")).toBeInTheDocument(); // div yield from cache
  });

  it("renders numeric values in font-mono per ADR-F-15", () => {
    wrap(
      makeClient(),
      <KeyStatsBar instrumentId="i-1" fundamentals={slimFundamentals()} snapshot={snapshot()} />,
    );
    const value = screen.getByText("$4.31T");
    expect(value.className).toContain("font-mono");
    expect(value.className).toContain("tabular-nums");
  });
});
