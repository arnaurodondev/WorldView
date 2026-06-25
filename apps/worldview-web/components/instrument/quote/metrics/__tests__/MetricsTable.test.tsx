/**
 * components/instrument/quote/metrics/__tests__/MetricsTable.test.tsx
 *
 * WHY THIS EXISTS: MetricsTable is the right-rail Statistics panel
 * (PRD-0088 §6.7.2 / PLAN-0090 §T-B-03). The Wave-2 redesign (2026-06-10)
 * PORTS the original label smoke contract and ADDS the data-wiring pins that
 * would have caught the all-dash sidebar bug:
 *
 *  PORTED:
 *   1. the "MARKET CAP" label renders even with zero data (labels are the
 *      structural skeleton of the table).
 *
 *  NEW (Wave-2):
 *   2. DATA WIRING — when the hook returns the full transformed Fundamentals
 *      (which, post-fix, it reads from the bundle-seeded cache), the
 *      valuation/margin/consensus VALUES render — not "—". This is the
 *      regression guard for the 2026-06-10 screenshot where MARKET CAP,
 *      P/E, ROE, TARGET etc. were all dashes while seeded rows rendered.
 *   3. SECTIONED LAYOUT — the accent-bar section headers (Valuation /
 *      Profitability / Ownership / Technicals / Analyst Consensus) exist.
 *
 * WHY mock useMetricsTableData (not the gateway): the hook is the single
 * data dependency MetricsTable has (PLAN-0090 forbids inline useQuery).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Fundamentals, Quote } from "@/types/api";

// Hoisted mutable state — each test sets the hook payload it needs.
const hookState = vi.hoisted(() => ({
  value: {
    fundamentals: undefined as unknown,
    snapshot: undefined as unknown,
    technicals: undefined as unknown,
    shareStats: undefined as unknown,
    isLoading: false,
    isError: false,
  },
}));

vi.mock("@/components/instrument/hooks/useMetricsTableData", () => ({
  useMetricsTableData: () => hookState.value,
}));

// eslint-disable-next-line import/first
import { MetricsTable } from "@/components/instrument/quote/metrics/MetricsTable";

// ── Fixtures (mirror the LIVE AAPL values verified 2026-06-10) ───────────────

/** The flat shape transformFundamentalsSections produces from the bundle. */
const FULL_FUNDAMENTALS = {
  instrument_id: "i-1",
  ticker: "AAPL",
  name: "Apple Inc.",
  market_cap: 4_308_095_467_520,
  pe_ratio: 35.468,
  forward_pe: 32.7869,
  price_to_book: 39.1944,
  price_to_sales: 9.543,
  ev_to_ebitda: 26.1918,
  gross_margin: 0.4786,
  operating_margin: 0.3228,
  net_margin: 0.2715,
  roe: 1.4147,
  roa: 0.2623,
  revenue_growth_yoy: 0.166,
  earnings_growth_yoy: 0.218,
  dividend_yield: 0.0036,
  payout_ratio: 0.1258,
  debt_to_equity: null,
  current_ratio: null,
  quick_ratio: null,
  week_52_high: 294.76,
  week_52_low: 192.8731,
  daily_return: null,
  analyst_strong_buy_count: 25,
  analyst_buy_count: 6,
  analyst_hold_count: 15,
  analyst_sell_count: 1,
  analyst_strong_sell_count: 1,
  analyst_rating: 4.1042,
  analyst_target_price: 303.3762,
  updated_at: "2026-06-10T00:00:00Z",
} satisfies Fundamentals;

const QUOTE = {
  instrument_id: "i-1",
  ticker: "AAPL",
  price: 290.65,
  change: -25.03,
  change_pct: -7.93,
  timestamp: "2026-06-10T13:00:00Z",
  volume: null,
} satisfies Quote;

beforeEach(() => {
  hookState.value = {
    fundamentals: undefined,
    snapshot: undefined,
    technicals: undefined,
    shareStats: undefined,
    isLoading: false,
    isError: false,
  };
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("MetricsTable", () => {
  // PORTED smoke contract — labels are the structural skeleton.
  it("renders the MARKET CAP label even with no data loaded", () => {
    render(<MetricsTable instrumentId="i-1" fundamentals={null} quote={null} />);
    expect(screen.getByText("MARKET CAP")).toBeInTheDocument();
  });

  // NEW: the all-dash regression guard.
  it("renders VALUES (not dashes) when the hook supplies full fundamentals", () => {
    hookState.value = {
      ...hookState.value,
      fundamentals: FULL_FUNDAMENTALS,
      // Technicals leg in S3 section-envelope shape (EODHD keys).
      technicals: {
        security_id: "i-1",
        records: [{ section: "technicals_snapshot", data: { "50DayMA": 275.5951, "200DayMA": 263.3148, ShortPercent: 0.0092 } }],
      },
      snapshot: { instrument_id: "i-1", eps_ttm: 8.26, beta: 1.086, avg_volume_30d: 26_698_293 },
    };
    render(<MetricsTable instrumentId="i-1" fundamentals={null} quote={QUOTE} />);

    // Valuation values — the rows that were "—" in the broken screenshot.
    expect(screen.getByText("$4.31T")).toBeInTheDocument();   // MARKET CAP
    expect(screen.getByText("35.47")).toBeInTheDocument();    // P/E
    expect(screen.getByText("32.79")).toBeInTheDocument();    // FWD P/E
    // Consensus: target + the colour-coded analyst breakdown (31 = 25SB + 6B).
    expect(screen.getByText(/\$303\.38/)).toBeInTheDocument(); // TARGET
    expect(screen.getByText("31 Buy")).toBeInTheDocument();
    expect(screen.getByText("48 analysts")).toBeInTheDocument();
    // Technicals: MA50 with the ↑ trend arrow (290.65 ≥ 275.60 = uptrend).
    expect(screen.getByText(/\$275\.60 ↑/)).toBeInTheDocument();
    // No analyst-coverage empty state must NOT render when data exists.
    expect(screen.queryByText("No analyst coverage")).not.toBeInTheDocument();
  });

  // NEW (UI roadmap 2026-06-19 item #1): teal/red are reserved for DIRECTIONAL
  // values. Non-directional LEVELS (P/E, ROE, net margin) render neutral; the
  // directional growth row keeps its sign colour.
  it("colours only DIRECTIONAL values; levels are neutral (item #1)", () => {
    hookState.value = { ...hookState.value, fundamentals: FULL_FUNDAMENTALS };
    render(<MetricsTable instrumentId="i-1" fundamentals={null} quote={QUOTE} />);

    // P/E 35.47 was previously amber ("expensive") — now neutral. A coloured
    // P/E miscommunicates: amber/red must mean a move, not a valuation opinion.
    const pe = screen.getByText("35.47").className;
    expect(pe).not.toContain("text-positive");
    expect(pe).not.toContain("text-negative");
    expect(pe).not.toContain("text-warning");

    // ROE 141.47% (a quality level) is unsigned + neutral — no "+" and no teal.
    const roe = screen.getByText("141.47%").className;
    expect(roe).not.toContain("text-positive");
    expect(roe).not.toContain("text-negative");

    // REV GROWTH YOY +16.60% is DIRECTIONAL → keeps the positive token + "+".
    const rev = screen.getByText("+16.60%").className;
    expect(rev).toContain("text-positive");
  });

  // NEW: hook data must WIN over the slim bundle prop (the rich shape carries
  // margins/consensus the 5-field prop lacks).
  it("prefers hook fundamentals over the slim prop seed", () => {
    hookState.value = { ...hookState.value, fundamentals: FULL_FUNDAMENTALS };
    const slimProp = { ...FULL_FUNDAMENTALS, market_cap: 1 } as Fundamentals;
    render(<MetricsTable instrumentId="i-1" fundamentals={slimProp} quote={QUOTE} />);
    // $4.31T (hook) renders; the prop's $1 must not.
    expect(screen.getByText("$4.31T")).toBeInTheDocument();
  });

  // NEW: sectioned layout — the accent-bar headers exist.
  it("renders the accent-bar section headers", () => {
    render(<MetricsTable instrumentId="i-1" fundamentals={null} quote={null} />);
    for (const label of [
      "Valuation",
      "Profitability",
      "Leverage & Yield",
      "52-Week Range",
      "Ownership",
      "Technicals",
      "Analyst Consensus",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
