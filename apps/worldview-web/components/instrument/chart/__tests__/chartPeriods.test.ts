/**
 * components/instrument/chart/__tests__/chartPeriods.test.ts
 *
 * WHY THIS EXISTS (Round-1 Foundation): the period → fetch-params presets are
 * the contract between the chart toolbar and the S9 price-history endpoint.
 * These tests pin two load-bearing invariants:
 *   1. The cache-sharing scheme — 1M/3M/1Y MUST share the daily-bar resolution
 *      and the SAME fetch window so switching among them never refetches
 *      (requirement 5). If a preset edit splits the window, switching periods
 *      silently starts firing extra network calls.
 *   2. The fetch window always covers the visible window — otherwise the
 *      chart would window a range with no data in it (blank canvas class).
 */

import { describe, it, expect } from "vitest";
import {
  CHART_PERIODS,
  CHART_PERIOD_PRESETS,
  DEFAULT_CHART_PERIOD,
  periodStartIso,
} from "@/components/instrument/chart/chartPeriods";

describe("chartPeriods presets", () => {
  it("exposes exactly the 6 backend-supported periods in display order", () => {
    // 2026-06-15: the set is now backend-honest — every period maps to a
    // resolution S3 actually stores. 1W (hourly, sparse) and 5Y (weekly, NOT
    // stored — rendered empty) are gone; 5D (intraday) and 6M (daily) replace
    // them. See chartPeriods.ts for the live-verified data-availability table.
    expect(CHART_PERIODS).toEqual(["1D", "5D", "1M", "3M", "6M", "1Y"]);
  });

  it("only maps to resolutions the backend actually stores (5M or 1D — never 1H/1W/1M)", () => {
    // ROOT-CAUSE GUARD: the old 1W→1H and 5Y→1W mappings hit resolutions with
    // ~10 or ZERO stored bars. Pin that NO period may ever map to those again.
    const allowed = new Set(["5M", "1D"]);
    for (const period of CHART_PERIODS) {
      expect(allowed.has(CHART_PERIOD_PRESETS[period].timeframe)).toBe(true);
    }
  });

  it("1M / 3M / 6M / 1Y share one daily-bar cache slot (same timeframe + fetch window)", () => {
    const daily = ["1M", "3M", "6M", "1Y"] as const;
    for (const p of daily) {
      // Same timeframe → same qk.instruments.ohlcv(id, tf) cache key.
      expect(CHART_PERIOD_PRESETS[p].timeframe).toBe("1D");
      // Same fetch window → identical queryFn params → one shared fetch.
      expect(CHART_PERIOD_PRESETS[p].fetchDaysBack).toBe(CHART_PERIOD_PRESETS["1Y"].fetchDaysBack);
    }
  });

  it("1D / 5D share one intraday (5M) cache slot (same timeframe + fetch window)", () => {
    // The two intraday periods must share a slot too — switching 1D↔5D is a
    // client-side re-window of the same 5-minute series, never a refetch.
    expect(CHART_PERIOD_PRESETS["1D"].timeframe).toBe("5M");
    expect(CHART_PERIOD_PRESETS["5D"].timeframe).toBe("5M");
    expect(CHART_PERIOD_PRESETS["1D"].fetchDaysBack).toBe(CHART_PERIOD_PRESETS["5D"].fetchDaysBack);
  });

  it("every preset fetches at least as far back as it shows (no empty window)", () => {
    for (const period of CHART_PERIODS) {
      const preset = CHART_PERIOD_PRESETS[period];
      expect(preset.fetchDaysBack).toBeGreaterThanOrEqual(preset.visibleDays);
    }
  });

  it("periodStartIso returns a UTC date-only string N days back", () => {
    // Fixed clock so the assertion is deterministic.
    const now = new Date("2026-06-10T12:00:00Z");
    // 1D preset now fetches 8 days back (was 3 — too narrow, landed on sparse
    // sessions and produced the "~10 bars" bug) → 2026-06-02.
    expect(periodStartIso("1D", now)).toBe("2026-06-02");
    // Date-only format (stable query-string within a calendar day).
    expect(periodStartIso("1Y", now)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  // ── Wave-4 default-view contract (2026-06-12) ──────────────────────────────
  // The default view must load ~500 bars and show ~200. These tests pin the
  // preset values that make that true so a future preset edit can't silently
  // revert to the old sparse 1D/5M default.

  it("DEFAULT_CHART_PERIOD is a daily-bar period (not the sparse 5M intraday default)", () => {
    // The old default ("1D" → 5M) showed only ~10-30 candles. The new default
    // must use the daily resolution so a meaningful price history loads.
    expect(CHART_PERIOD_PRESETS[DEFAULT_CHART_PERIOD].timeframe).toBe("1D");
  });

  it("the default period windows the visible range to ~200 BARS (not days)", () => {
    // visibleBars is the bar-count window the chart applies via
    // setVisibleLogicalRange — the only way to promise an exact opening candle
    // count regardless of how many calendar days those bars span.
    expect(CHART_PERIOD_PRESETS[DEFAULT_CHART_PERIOD].visibleBars).toBe(200);
  });

  it("the daily-bar fetch window is wide enough to load ~500 bars behind the visible window", () => {
    // ~500 trading days needs ~730 calendar days (markets closed ~30% of days).
    // A window narrower than this could never load 500 daily bars, so panning
    // back from the ~200 visible bars would hit the start of the data
    // immediately — the regression this guards against.
    const preset = CHART_PERIOD_PRESETS[DEFAULT_CHART_PERIOD];
    expect(preset.fetchDaysBack).toBeGreaterThanOrEqual(700);
    // The fetch window must exceed the visible bar budget with room to pan.
    // (730 calendar days ≈ 500 trading days ≫ the 200 visible bars.)
    expect(preset.visibleBars).toBeLessThan(preset.fetchDaysBack);
  });

  it("intraday periods window by BAR COUNT (robust to sparse/irregular sessions)", () => {
    // 2026-06-15: 1D / 5D now use a bar-COUNT visible window (visibleBars), NOT
    // a calendar-day window. WHY the change: a day-window can land on a sparse
    // session (verified live: 11 bars one day, 60 the next) and reproduce the
    // "~10 bars" bug. A fixed bar count always shows a dense, consistent number
    // of the most-recent candles regardless of how the sessions fell.
    expect(CHART_PERIOD_PRESETS["1D"].visibleBars).toBe(80);
    expect(CHART_PERIOD_PRESETS["5D"].visibleBars).toBe(390);
  });

  it("EVERY period now declares an explicit visibleBars budget", () => {
    // The visible-range effect in OHLCVChart prefers visibleBars (exact candle
    // count) over visibleDays (calendar window). Pin that every period opts in
    // so none can silently fall back to the day-window class of bug.
    for (const period of CHART_PERIODS) {
      expect(CHART_PERIOD_PRESETS[period].visibleBars).toBeGreaterThan(0);
    }
  });
});
