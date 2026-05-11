/**
 * features/portfolio/lib/__tests__/kpi.test.ts — Unit tests for the
 * portfolio KPI / allocation / scope-hint pure functions.
 *
 * WHY THESE TESTS EXIST: These functions used to live as inline useMemo
 * blocks in portfolio/page.tsx — exercising them required a full RTL
 * mount + 8 mocked queries. Now we hand-build minimal fixtures and
 * assert on numeric outputs. Critical regressions caught here:
 *
 *   - F-202 (PLAN-0048 QA iter-1): "all positions profitable" must NOT
 *     label the smallest gainer as Top Loser
 *   - B-2 (BP-related): delisted instrument with price=0 must fall back
 *     to current_price/average_cost, NOT compute pnlPct = -100%
 *   - BP-265 awareness: "transactions still loading" must surface as
 *     realizedPnl=null (UI shows "—"), NOT $0
 */

import { describe, it, expect } from "vitest";
import {
  computePortfolioKPI,
  computeAllocations,
  computeScopeHint,
  livePriceFor,
  formatStalenessAwarePrice,
} from "../kpi";
import type { Holding, Quote, Transaction, Portfolio } from "@/types/api";

// ── Fixture builders ──────────────────────────────────────────────────────

/**
 * mkHolding — minimal Holding factory. We only fill the fields the KPI
 * functions read; the rest stay as their type defaults.
 */
function mkHolding(overrides: Partial<Holding> & { instrument_id: string }): Holding {
  return {
    holding_id: `h-${overrides.instrument_id}`,
    portfolio_id: "p-1",
    instrument_id: overrides.instrument_id,
    entity_id: overrides.entity_id ?? `entity-${overrides.instrument_id}`,
    ticker: overrides.ticker ?? "TEST",
    name: overrides.name ?? "Test Holding",
    quantity: overrides.quantity ?? 0,
    average_cost: overrides.average_cost ?? 0,
    current_price: overrides.current_price ?? null,
    unrealised_pnl: null,
    unrealised_pnl_pct: null,
    portfolio_weight: null,
  };
}

function mkQuote(overrides: Partial<Quote> & { instrument_id: string }): Quote {
  // WHY spread first then defaults: spreading `overrides` first means the
  // explicit fallback fields below win, but TypeScript still sees the
  // `instrument_id` override and the field-with-default. Using spread first
  // avoids the TS2783 "specified more than once" warning.
  return {
    ticker: "TEST",
    price: 100,
    change: 0,
    change_pct: 0,
    timestamp: "2026-05-02T00:00:00Z",
    volume: null,
    ...overrides,
  };
}

function mkTx(overrides: Partial<Transaction> & { instrument_id: string }): Transaction {
  return {
    transaction_id: `tx-${Math.random()}`,
    portfolio_id: "p-1",
    instrument_id: overrides.instrument_id,
    ticker: overrides.ticker ?? "TEST",
    type: overrides.type ?? "SELL",
    quantity: overrides.quantity ?? 1,
    price: overrides.price ?? 100,
    fee: 0,
    amount: null,
    asset_class: null,
    currency: "USD",
    executed_at: "2026-05-02T00:00:00Z",
    notes: null,
  };
}

function mkPortfolio(overrides: Partial<Portfolio> & { portfolio_id: string }): Portfolio {
  return {
    portfolio_id: overrides.portfolio_id,
    name: overrides.name ?? "Test",
    currency: "USD",
    owner_id: "user-1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    kind: overrides.kind,
  };
}

// ── livePriceFor ──────────────────────────────────────────────────────────

describe("livePriceFor", () => {
  it("uses live quote price when > 0", () => {
    const h = mkHolding({ instrument_id: "i1", current_price: 50, average_cost: 40 });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 100 }) };
    expect(livePriceFor(h, quotes)).toBe(100);
  });

  it("falls back to current_price when quote is missing", () => {
    const h = mkHolding({ instrument_id: "i1", current_price: 50, average_cost: 40 });
    expect(livePriceFor(h, {})).toBe(50);
  });

  it("falls back to average_cost when neither quote nor current_price set", () => {
    const h = mkHolding({ instrument_id: "i1", current_price: null, average_cost: 40 });
    expect(livePriceFor(h, {})).toBe(40);
  });

  it("treats price=0 as missing (B-2 delisted-instrument fix)", () => {
    // WHY: delisted positions return price:0 from the batch endpoint. The
    // earlier nullish-chain treated 0 as a real value and computed pnlPct=-100%.
    const h = mkHolding({ instrument_id: "i1", current_price: 50, average_cost: 40 });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 0 }) };
    expect(livePriceFor(h, quotes)).toBe(50); // skips quote.price=0, uses current_price
  });
});

// ── computePortfolioKPI ───────────────────────────────────────────────────

describe("computePortfolioKPI", () => {
  it("returns zeros for an empty portfolio with no transactions", () => {
    const k = computePortfolioKPI([], {}, undefined);
    expect(k.totalValue).toBe(0);
    // totalCost is not on the public KPI interface; covered indirectly by
    // unrealisedPnl which equals totalValue - totalCost.
    expect(k.unrealisedPnl).toBe(0);
    expect(k.unrealisedPnlPct).toBe(0);
    expect(k.dayPnl).toBeNull();
    expect(k.topGainer).toBeNull();
    expect(k.topLoser).toBeNull();
    expect(k.positionCount).toBe(0);
    expect(k.realizedPnl).toBeNull(); // transactions undefined → null (not 0)
  });

  it("computes total value from live-quote * quantity", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 10, average_cost: 100 });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 150, change: 5 }) };
    const k = computePortfolioKPI([h], quotes, { transactions: [] });
    expect(k.totalValue).toBe(1500); // 10 × 150
    expect(k.unrealisedPnl).toBe(500); // (150-100) × 10
    expect(k.unrealisedPnlPct).toBeCloseTo(0.5, 5);
    expect(k.dayPnl).toBe(50); // 5 × 10
    expect(k.positionCount).toBe(1);
  });

  it("dayPnl stays null when NO quote has change", () => {
    // BP-265 awareness: don't conflate "loading" with "$0 change"
    const h = mkHolding({ instrument_id: "i1", quantity: 10, average_cost: 100 });
    const k = computePortfolioKPI([h], {}, { transactions: [] });
    expect(k.dayPnl).toBeNull();
  });

  it("top-gainer: only positions with pnlPct > 0 are eligible", () => {
    const h = mkHolding({
      instrument_id: "i1",
      ticker: "AAPL",
      quantity: 5,
      average_cost: 100,
    });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 110 }) };
    const k = computePortfolioKPI([h], quotes, { transactions: [] });
    expect(k.topGainer).toEqual({ ticker: "AAPL", pnlPct: 10 });
    expect(k.topLoser).toBeNull(); // single positive position → no loser
  });

  it("top-loser stays null when EVERY position is profitable (F-202)", () => {
    // The earlier inline implementation used Math.min and would have
    // selected MSFT +1.7% as "Top Loser" — strictly wrong. Symmetric
    // pnlPct < 0 guard keeps it null.
    const holdings = [
      mkHolding({ instrument_id: "a", ticker: "AAPL", quantity: 1, average_cost: 100 }),
      mkHolding({ instrument_id: "b", ticker: "MSFT", quantity: 1, average_cost: 100 }),
    ];
    const quotes = {
      a: mkQuote({ instrument_id: "a", price: 105 }), // +5%
      b: mkQuote({ instrument_id: "b", price: 102 }), // +2%
    };
    const k = computePortfolioKPI(holdings, quotes, { transactions: [] });
    expect(k.topGainer).toEqual({ ticker: "AAPL", pnlPct: 5 });
    expect(k.topLoser).toBeNull();
  });

  it("top-loser identifies steepest decliner when one exists", () => {
    const holdings = [
      mkHolding({ instrument_id: "a", ticker: "GAIN", quantity: 1, average_cost: 100 }),
      mkHolding({ instrument_id: "b", ticker: "DROP", quantity: 1, average_cost: 100 }),
    ];
    const quotes = {
      a: mkQuote({ instrument_id: "a", price: 110 }), // +10%
      b: mkQuote({ instrument_id: "b", price: 80 }), // -20%
    };
    const k = computePortfolioKPI(holdings, quotes, { transactions: [] });
    expect(k.topGainer).toEqual({ ticker: "GAIN", pnlPct: 10 });
    expect(k.topLoser).toEqual({ ticker: "DROP", pnlPct: -20 });
  });

  it("realizedPnl: sums (sell_price - avg_cost) * qty for SELL transactions", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 10, average_cost: 100 });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 100 }) };
    const txs: Transaction[] = [
      mkTx({ instrument_id: "i1", type: "SELL", quantity: 5, price: 120 }), // +20 × 5 = 100
      mkTx({ instrument_id: "i1", type: "BUY", quantity: 3, price: 90 }), // skipped
      mkTx({ instrument_id: "i1", type: "SELL", quantity: 2, price: 110 }), // +10 × 2 = 20
    ];
    const k = computePortfolioKPI([h], quotes, { transactions: txs });
    expect(k.realizedPnl).toBe(120);
  });

  it("realizedPnl: skips SELLs of unknown/closed positions (no avgCost match)", () => {
    const h = mkHolding({ instrument_id: "open", quantity: 1, average_cost: 100 });
    const txs: Transaction[] = [
      mkTx({ instrument_id: "closed", type: "SELL", quantity: 1, price: 200 }), // skipped
      mkTx({ instrument_id: "open", type: "SELL", quantity: 1, price: 150 }), // +50
    ];
    const k = computePortfolioKPI([h], {}, { transactions: txs });
    expect(k.realizedPnl).toBe(50);
  });

  it("realizedPnl is null when transactions arg is undefined (loading state)", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 1, average_cost: 100 });
    const k = computePortfolioKPI([h], {}, undefined);
    expect(k.realizedPnl).toBeNull();
  });

  it("realizedPnl is 0 (not null) when transactions loaded but empty array", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 1, average_cost: 100 });
    const k = computePortfolioKPI([h], {}, { transactions: [] });
    expect(k.realizedPnl).toBe(0);
  });

  it("unrealisedPnlPct guards against divide-by-zero when totalCost is 0", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 0, average_cost: 0 });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 100 }) };
    const k = computePortfolioKPI([h], quotes, { transactions: [] });
    expect(k.unrealisedPnlPct).toBe(0); // not NaN
  });
});

// ── computeAllocations ────────────────────────────────────────────────────

describe("computeAllocations", () => {
  it("returns empty arrays for empty holdings", () => {
    const a = computeAllocations([], {}, {});
    expect(a.bySector).toEqual([]);
    expect(a.byType).toEqual([]);
  });

  it("returns empty arrays when overviews map is undefined (loading)", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 1, average_cost: 100 });
    const a = computeAllocations([h], undefined, {});
    expect(a.bySector).toEqual([]);
    expect(a.byType).toEqual([]);
  });

  it("returns empty arrays when totalValue is 0 (avoids NaN%)", () => {
    const h = mkHolding({ instrument_id: "i1", quantity: 0, average_cost: 0 });
    const overviews = { i1: { sector: "Technology", ticker: "T", name: "T", entity_id: "e" } };
    const a = computeAllocations([h], overviews, {});
    expect(a.bySector).toEqual([]);
    expect(a.byType).toEqual([]);
  });

  it("groups holdings by GICS sector with correct percentages", () => {
    const holdings = [
      mkHolding({ instrument_id: "a", quantity: 10, average_cost: 100 }), // val=1000
      mkHolding({ instrument_id: "b", quantity: 5, average_cost: 200 }), // val=1000
      mkHolding({ instrument_id: "c", quantity: 4, average_cost: 250 }), // val=1000
    ];
    const overviews = {
      a: { sector: "Technology", ticker: "A", name: "A", entity_id: "ea" },
      b: { sector: "Technology", ticker: "B", name: "B", entity_id: "eb" },
      c: { sector: "Healthcare", ticker: "C", name: "C", entity_id: "ec" },
    };
    const a = computeAllocations(holdings, overviews, {});
    expect(a.bySector).toHaveLength(2);
    expect(a.bySector[0]).toEqual({
      label: "Technology",
      value: 2000,
      pct: expect.closeTo(66.66666, 3) as number,
    });
    expect(a.bySector[1]).toEqual({
      label: "Healthcare",
      value: 1000,
      pct: expect.closeTo(33.33333, 3) as number,
    });
  });

  it("buckets holdings with missing overview into 'Unknown' sector", () => {
    const holdings = [mkHolding({ instrument_id: "i1", quantity: 1, average_cost: 100 })];
    const a = computeAllocations(holdings, {}, {});
    expect(a.bySector[0]?.label).toBe("Unknown");
  });

  it("byType is currently a single 100% Equity bar", () => {
    const holdings = [mkHolding({ instrument_id: "i1", quantity: 10, average_cost: 100 })];
    const overviews = { i1: { sector: "Technology", ticker: "T", name: "T", entity_id: "e" } };
    const a = computeAllocations(holdings, overviews, {});
    expect(a.byType).toEqual([{ label: "Equity", value: 1000, pct: 100 }]);
  });

  it("uses live-quote price for sector valuation (matches KPI total)", () => {
    // If sector calc used average_cost while KPI used live quote, the totals
    // would diverge — the regression this guards against.
    const h = mkHolding({ instrument_id: "i1", quantity: 10, average_cost: 100 });
    const quotes = { i1: mkQuote({ instrument_id: "i1", price: 200 }) };
    const overviews = { i1: { sector: "Technology", ticker: "T", name: "T", entity_id: "e" } };
    const a = computeAllocations([h], overviews, quotes);
    expect(a.bySector[0]?.value).toBe(2000); // 10 × 200, not 10 × 100
  });
});

// ── computeScopeHint ──────────────────────────────────────────────────────

describe("computeScopeHint", () => {
  it("returns null when there's no active portfolio", () => {
    expect(computeScopeHint(undefined, false, undefined, 0)).toBeNull();
  });

  it("returns null for a manual portfolio (selector name is enough)", () => {
    const p = mkPortfolio({ portfolio_id: "p1", kind: "manual" });
    expect(computeScopeHint(p, false, [p], 5)).toBeNull();
  });

  it("returns 'Brokerage portfolio' for a brokerage portfolio", () => {
    const p = mkPortfolio({ portfolio_id: "p1", kind: "brokerage" });
    expect(computeScopeHint(p, false, [p], 5)).toBe("Brokerage portfolio");
  });

  it("for root portfolio: counts non-root sub-portfolios + position count", () => {
    const root = mkPortfolio({ portfolio_id: "root", kind: "root" });
    const sub1 = mkPortfolio({ portfolio_id: "p1", kind: "manual" });
    const sub2 = mkPortfolio({ portfolio_id: "p2", kind: "brokerage" });
    expect(computeScopeHint(root, true, [root, sub1, sub2], 14)).toBe(
      "Viewing All Accounts — 2 portfolios, 14 unique positions",
    );
  });

  it("singularises 'portfolio' and 'position' when count is 1", () => {
    const root = mkPortfolio({ portfolio_id: "root", kind: "root" });
    const sub1 = mkPortfolio({ portfolio_id: "p1", kind: "manual" });
    expect(computeScopeHint(root, true, [root, sub1], 1)).toBe(
      "Viewing All Accounts — 1 portfolio, 1 unique position",
    );
  });

  it("handles 0 sub-portfolios gracefully", () => {
    const root = mkPortfolio({ portfolio_id: "root", kind: "root" });
    expect(computeScopeHint(root, true, [root], 0)).toBe(
      "Viewing All Accounts — 0 portfolios, 0 unique positions",
    );
  });
});

// ── formatStalenessAwarePrice ─────────────────────────────────────────────

describe("formatStalenessAwarePrice", () => {
  it("renders price without prefix when freshness is 'live'", () => {
    expect(formatStalenessAwarePrice(185.42, "live")).toBe("$185.42");
  });

  it("renders price without prefix when freshness is undefined", () => {
    expect(formatStalenessAwarePrice(185.42, undefined)).toBe("$185.42");
  });

  it("prefixes '~' when freshness is 'recent' / 'delayed' / 'stale'", () => {
    expect(formatStalenessAwarePrice(185.42, "recent")).toBe("~$185.42");
    expect(formatStalenessAwarePrice(185.42, "delayed")).toBe("~$185.42");
    expect(formatStalenessAwarePrice(185.42, "stale")).toBe("~$185.42");
  });
});
