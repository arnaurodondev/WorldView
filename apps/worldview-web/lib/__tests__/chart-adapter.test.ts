/**
 * lib/__tests__/chart-adapter.test.ts — Pure OHLCV bar-normalization contract.
 *
 * Pins the blank-chart guard: lightweight-charts v5 setData() throws
 * "data must be asc ordered by time" on duplicate or out-of-order time keys,
 * which blanks the entire instrument chart. normalizeBars() must dedupe by
 * timestamp (last write wins) and sort strictly ascending so a backend that
 * returns duplicated daily bars (observed live for daily OHLCV after the Alpaca
 * backfill) still renders. It must also drop bars with non-finite OHLC legs or
 * an unparseable timestamp, and coerce a null/NaN volume to 0.
 */

import { describe, it, expect } from "vitest";
import { normalizeBars } from "@/lib/chart-adapter";
import type { OHLCVBar } from "@/types/api";

function bar(timestamp: string, close: number, extra: Partial<OHLCVBar> = {}): OHLCVBar {
  return {
    timestamp,
    open: close - 1,
    high: close + 1,
    low: close - 2,
    close,
    volume: 1000,
    ...extra,
  };
}

describe("normalizeBars", () => {
  it("dedupes duplicate timestamps, keeping the last (refreshed) value", () => {
    // Every date duplicated — the exact shape prod daily OHLCV returns after the
    // Alpaca backfill wrote rows alongside the existing EODHD rows.
    const raw: OHLCVBar[] = [
      bar("2026-06-16T00:00:00Z", 100),
      bar("2026-06-16T00:00:00Z", 101), // same day, refreshed close
      bar("2026-06-17T00:00:00Z", 102),
      bar("2026-06-17T00:00:00Z", 103),
    ];

    const out = normalizeBars(raw);

    expect(out).toHaveLength(2);
    expect(out[0].close).toBe(101); // last write wins
    expect(out[1].close).toBe(103);
  });

  it("produces strictly ascending unique time keys (lightweight-charts contract)", () => {
    const raw: OHLCVBar[] = [
      bar("2026-06-18T00:00:00Z", 5),
      bar("2026-06-16T00:00:00Z", 5), // out of order
      bar("2026-06-16T00:00:00Z", 5), // duplicate
      bar("2026-06-17T00:00:00Z", 5),
    ];

    const times = normalizeBars(raw).map((b) => b.time);

    expect(times).toEqual([...times].sort((a, b) => a - b));
    expect(new Set(times).size).toBe(times.length);
  });

  it("drops bars with non-finite OHLC legs or an unparseable timestamp", () => {
    const raw: OHLCVBar[] = [
      bar("2026-06-16T00:00:00Z", 100),
      bar("2026-06-17T00:00:00Z", Number.NaN), // bad close
      bar("not-a-date", 100), // NaN time key — hard reject in lightweight-charts
    ];

    const out = normalizeBars(raw);

    expect(out).toHaveLength(1);
    expect(out[0].close).toBe(100);
  });

  it("coerces a non-finite volume to 0 rather than dropping the bar", () => {
    const raw: OHLCVBar[] = [
      bar("2026-06-16T00:00:00Z", 100, { volume: Number.NaN }),
    ];

    const out = normalizeBars(raw);

    expect(out).toHaveLength(1);
    expect(out[0].volume).toBe(0);
  });

  it("returns an empty array for empty input", () => {
    expect(normalizeBars([])).toEqual([]);
  });
});
