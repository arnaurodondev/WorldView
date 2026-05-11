/**
 * features/dashboard/lib/__tests__/movers.test.ts — Unit tests for the
 * Watchlist Movers ranking + filtering logic.
 *
 * WHY THESE TESTS EXIST: Before E-5 the same logic lived in inline useMemo
 * blocks that could only be exercised through a full RTL mount with TanStack
 * Query mocks. Pulling the logic into pure functions enabled these focused
 * fixture-driven tests, which catch regressions on:
 *   - 1W/1M OHLCV-based change_pct override (vs 1D pass-through)
 *   - sector-filter "loading row stays visible" rule
 *   - abs(%) ranking + 5/5 top-N partition
 *   - pickFirstWatchlistByCreatedAt deterministic ordering
 */

import { describe, it, expect } from "vitest";
import {
  buildMoverRows,
  applySectorFilter,
  rankByAbsChangePct,
  splitGainersLosers,
  pickFirstWatchlistByCreatedAt,
  type WatchlistMover,
} from "../movers";
import type { WatchlistMoverEnriched, OHLCVResponse } from "@/types/api";

// Tiny WatchlistMover factory — fills the full shape so TS accepts the
// fixtures while leaving every field overrideable. Used by the
// applySectorFilter / rankByAbsChangePct / splitGainersLosers tests.
function mk(overrides: Partial<WatchlistMover> & { ticker: string }): WatchlistMover {
  return {
    instrumentId: overrides.ticker,
    name: overrides.ticker,
    sector: null,
    price: null,
    changePct: null,
    newsCount24h: 0,
    hasActiveAlert: false,
    topNewsTitle: null,
    topNewsUrl: null,
    ...overrides,
  };
}

// ── Fixture builders ──────────────────────────────────────────────────────

function mkEnriched(
  overrides: Partial<WatchlistMoverEnriched> & { instrument_id: string },
): WatchlistMoverEnriched {
  return {
    entity_id: null,
    ticker: "TEST",
    name: "Test Holding",
    sector: "Technology",
    price: 100,
    change_pct: 0,
    news_count_24h: 0,
    has_active_alert: false,
    top_news_title: null,
    top_news_url: null,
    ...overrides,
  };
}

function mkOhlcv(closes: number[]): OHLCVResponse {
  return {
    instrument_id: "i",
    ticker: "T",
    timeframe: "1W",
    bars: closes.map((c, i) => ({
      timestamp: `2026-04-${String(i + 1).padStart(2, "0")}T00:00:00Z`,
      open: c,
      high: c,
      low: c,
      close: c,
      volume: 0,
    })),
  };
}

// ── buildMoverRows ────────────────────────────────────────────────────────

describe("buildMoverRows", () => {
  it("1D path: passes every field straight through from insights", () => {
    const e = mkEnriched({
      instrument_id: "i1",
      ticker: "AAPL",
      change_pct: 2.5,
      price: 188,
      news_count_24h: 3,
      has_active_alert: true,
      top_news_title: "Apple jumps",
    });
    const [row] = buildMoverRows([e], "1D", []);
    expect(row).toEqual({
      instrumentId: "i1",
      ticker: "AAPL",
      name: "Test Holding",
      sector: "Technology",
      price: 188,
      changePct: 2.5,
      newsCount24h: 3,
      hasActiveAlert: true,
      topNewsTitle: "Apple jumps",
      topNewsUrl: null,
    });
  });

  it("1W path: overrides price + changePct from OHLCV first→last close", () => {
    const e = mkEnriched({ instrument_id: "i1", price: 100, change_pct: 99 });
    const ohlcv = mkOhlcv([100, 102, 105, 110]); // last 110, first 100 → +10%
    const [row] = buildMoverRows([e], "1W", [ohlcv]);
    expect(row?.price).toBe(110);
    expect(row?.changePct).toBeCloseTo(10, 5);
  });

  it("1M path: nulls both price + changePct when OHLCV has < 2 bars", () => {
    const e = mkEnriched({ instrument_id: "i1", price: 100, change_pct: 99 });
    const ohlcv = mkOhlcv([100]);
    const [row] = buildMoverRows([e], "1M", [ohlcv]);
    expect(row?.price).toBeNull();
    expect(row?.changePct).toBeNull();
  });

  it("1W path: when bars[0].close <= 0, keeps last price but nulls changePct", () => {
    // Defends against divide-by-zero. The trader still sees the latest mark
    // — only the change% is suppressed.
    const e = mkEnriched({ instrument_id: "i1" });
    const ohlcv = mkOhlcv([0, 10, 20]);
    const [row] = buildMoverRows([e], "1W", [ohlcv]);
    expect(row?.price).toBe(20);
    expect(row?.changePct).toBeNull();
  });

  it("preserves enrichment columns (sector/news/alerts) across 1D/1W/1M", () => {
    const e = mkEnriched({
      instrument_id: "i1",
      sector: "Energy",
      news_count_24h: 5,
      has_active_alert: true,
    });
    const ohlcv = mkOhlcv([100, 110]);
    const [d] = buildMoverRows([e], "1D", []);
    const [w] = buildMoverRows([e], "1W", [ohlcv]);
    expect(d?.sector).toBe("Energy");
    expect(w?.sector).toBe("Energy");
    expect(d?.newsCount24h).toBe(5);
    expect(w?.newsCount24h).toBe(5);
    expect(d?.hasActiveAlert).toBe(true);
    expect(w?.hasActiveAlert).toBe(true);
  });

  it("1W: undefined OHLCV at index produces null price/changePct (loading)", () => {
    const e = mkEnriched({ instrument_id: "i1" });
    const [row] = buildMoverRows([e], "1W", [undefined]);
    expect(row?.price).toBeNull();
    expect(row?.changePct).toBeNull();
  });
});

// ── applySectorFilter ────────────────────────────────────────────────────

describe("applySectorFilter", () => {
  // Note: matchesSectorFilter uses strict equality against the GICS canonical
  // names (e.g. "Information Technology", "Health Care") — see lib/sectors.ts.
  const rows = [
    mk({ ticker: "T", sector: "Information Technology", changePct: 1 }),
    mk({ ticker: "H", sector: "Health Care", changePct: 2 }),
    mk({ ticker: "X", sector: null, changePct: 3 }),
    mk({ ticker: "F", sector: "Financials", changePct: 4 }),
  ];

  it("returns all rows when filter is ALL_SECTORS_VALUE", () => {
    const out = applySectorFilter(rows, "all");
    expect(out).toHaveLength(4);
  });

  it("filters to a single sector (canonical GICS match)", () => {
    const out = applySectorFilter(rows, "Information Technology");
    // Tech row matches; the null-sector row stays visible per the loading guard.
    const sectors = out.map((r) => r.sector);
    expect(sectors).toContain("Information Technology");
    expect(sectors).toContain(null); // loading row preserved
    expect(sectors).not.toContain("Health Care");
    expect(sectors).not.toContain("Financials");
  });

  it("keeps null-sector rows visible while their overview is in flight", () => {
    // Critical: shrinking the list during refetch is a UX bug.
    const out = applySectorFilter(rows, "Energy");
    expect(out.some((r) => r.sector === null)).toBe(true);
  });
});

// ── rankByAbsChangePct ────────────────────────────────────────────────────

describe("rankByAbsChangePct", () => {
  it("sorts descending by absolute change_pct", () => {
    const rows = [
      mk({ ticker: "A", changePct: 1 }),
      mk({ ticker: "B", changePct: -5 }),
      mk({ ticker: "C", changePct: 3 }),
      mk({ ticker: "D", changePct: -2 }),
    ];
    const out = rankByAbsChangePct(rows);
    expect(out.map((r) => r.ticker)).toEqual(["B", "C", "D", "A"]);
  });

  it("places null-changePct rows at the bottom", () => {
    const rows = [
      mk({ ticker: "A", changePct: null }),
      mk({ ticker: "B", changePct: 0.5 }),
    ];
    const out = rankByAbsChangePct(rows);
    expect(out[0]?.ticker).toBe("B");
    expect(out[1]?.ticker).toBe("A");
  });

  it("does not mutate the input array", () => {
    const rows = [
      mk({ ticker: "A", changePct: 1 }),
      mk({ ticker: "B", changePct: 2 }),
    ];
    const before = rows.map((r) => r.ticker).join(",");
    rankByAbsChangePct(rows);
    expect(rows.map((r) => r.ticker).join(",")).toBe(before);
  });
});

// ── splitGainersLosers ────────────────────────────────────────────────────

describe("splitGainersLosers", () => {
  it("partitions into top-5 gainers and top-5 losers (default)", () => {
    const rows = [
      mk({ ticker: "G1", changePct: 5 }),
      mk({ ticker: "L1", changePct: -8 }),
      mk({ ticker: "G2", changePct: 3 }),
      mk({ ticker: "G3", changePct: 1 }),
      mk({ ticker: "L2", changePct: -2 }),
    ];
    const { gainers, losers } = splitGainersLosers(rows);
    expect(gainers.map((r) => r.ticker)).toEqual(["G1", "G2", "G3"]);
    expect(losers.map((r) => r.ticker)).toEqual(["L1", "L2"]);
  });

  it("respects topN parameter", () => {
    const rows = Array.from({ length: 10 }, (_, i) =>
      mk({ ticker: `G${i}`, changePct: i + 1 }),
    );
    const { gainers } = splitGainersLosers(rows, 3);
    expect(gainers).toHaveLength(3);
  });

  it("drops null-changePct rows from BOTH columns", () => {
    // Null rows can't belong to either side — the renderer has no colour to
    // assign them. This guards against rendering a row in the wrong column.
    const rows = [
      mk({ ticker: "G", changePct: 1 }),
      mk({ ticker: "N", changePct: null }),
      mk({ ticker: "L", changePct: -1 }),
    ];
    const { gainers, losers } = splitGainersLosers(rows);
    expect(gainers.find((r) => r.ticker === "N")).toBeUndefined();
    expect(losers.find((r) => r.ticker === "N")).toBeUndefined();
  });

  it("zero-change rows go in NEITHER column", () => {
    const { gainers, losers } = splitGainersLosers([mk({ ticker: "Z", changePct: 0 })]);
    expect(gainers).toEqual([]);
    expect(losers).toEqual([]);
  });
});

// ── pickFirstWatchlistByCreatedAt ─────────────────────────────────────────

describe("pickFirstWatchlistByCreatedAt", () => {
  it("returns null for empty / undefined input", () => {
    expect(pickFirstWatchlistByCreatedAt(undefined)).toBeNull();
    expect(pickFirstWatchlistByCreatedAt([])).toBeNull();
  });

  it("returns the oldest watchlist by created_at", () => {
    const wls = [
      { name: "newer", created_at: "2026-04-15T00:00:00Z" },
      { name: "oldest", created_at: "2026-01-01T00:00:00Z" },
      { name: "middle", created_at: "2026-03-01T00:00:00Z" },
    ];
    expect(pickFirstWatchlistByCreatedAt(wls)?.name).toBe("oldest");
  });

  it("falls back to ISO-string compare when one timestamp is unparseable", () => {
    const wls = [
      { name: "z", created_at: "2026-01-01T00:00:00Z" },
      { name: "a", created_at: "garbage" },
    ];
    // Both unparseable → localeCompare wins; but here only one is bad,
    // so the comparator returns Date.parse - NaN = NaN per branch — falls
    // through to localeCompare. "2026-01-01..." vs "garbage" → "2..." < "g..."
    // so "z" comes first.
    expect(pickFirstWatchlistByCreatedAt(wls)?.name).toBe("z");
  });
});
